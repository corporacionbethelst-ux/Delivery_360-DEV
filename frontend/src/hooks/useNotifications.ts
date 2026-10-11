/**
 * Fase 9 - Hook de Notificaciones Omnicanal (IN_APP + tiempo real).
 *
 * Clona la arquitectura de useTrackingWebSocket.ts (misma carpeta src/hooks):
 *  - WebSocket manual con JWT en query string: ws(s)://<host>/api/v1/notifications/ws?token=<jwt>
 *  - Heartbeat ping cada 30s (el backend responde pong; tolerante si no hay respuesta)
 *  - Reconexión con backoff exponencial (300ms -> máx 15s, máximo de reintentos configurable)
 *  - Close code 1008 = token inválido/expirado => NO re-intenta (evita bucle infinito)
 *  - Fallback polling: GET /notifications/inbox cada 60s cuando el WS no está activo
 *  - Mensajes esperados del backend:
 *      {type:"CONNECTED", unread_count}        -> snapshot inicial
 *      {type:"NEW_NOTIFICATION", ...payload}   -> push en vivo (canal Redis notifications:user:{id})
 *      {type:"pong"}                            -> respuesta a heartbeat
 *  - Limpieza completa en unmount (clearTimeout/clearInterval/ws.close)
 *
 * Regla anti-error: NO abre un segundo pool WS propio del servidor; se conecta al
 * endpoint único /notifications/ws que hace fan-out desde el manager existente.
 */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export interface InboxNotification {
  id: string;
  template_code?: string | null;
  channel: string; // PUSH | SMS | EMAIL | IN_APP
  status: string;  // PENDIENTE | ENVIADO | ENTREGADO | FALLIDO | LEIDO
  title?: string | null;
  body?: string | null;
  created_at?: string | null;
  read_at?: string | null;
}

interface UseNotificationsOptions {
  enabled?: boolean;
  reconnectIntervalMs?: number;
  maxRetries?: number;
  heartbeatSec?: number;
  pollFallbackSec?: number;
  inboxSize?: number;
}

interface UseNotificationsReturn {
  items: InboxNotification[];
  unreadCount: number;
  isConnected: boolean;
  error: string | null;
  markRead: (id: string) => Promise<void>;
  refreshInbox: () => Promise<void>;
}

// ---------- helpers (mismos patrones que useTrackingWebSocket) ----------

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed?.token || parsed?.access_token || raw;
    } catch {
      return raw;
    }
  } catch {
    return null;
  }
}

function getWsBaseUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_NOTIFICATIONS_WS;
  if (explicit) {
    return explicit.replace(/\/notifications\/ws\/?$/, '').replace(/\/$/, '');
  }
  if (process.env.WS_BASE_URL) {
    return process.env.WS_BASE_URL.replace(/\/$/, '');
  }
  const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
  return api.replace(/^http/, 'ws').replace(/\/$/, '');
}

function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
}

async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(input, { ...init, headers });
}

// ---------- hook ----------

export function useNotifications(options: UseNotificationsOptions = {}): UseNotificationsReturn {
  const {
    enabled = true,
    reconnectIntervalMs = 3000,
    maxRetries = 5,
    heartbeatSec = 30,
    pollFallbackSec = 60,
    inboxSize = 10,
  } = options;

  const [items, setItems] = useState<InboxNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const closedRef = useRef(false);

  // -------- REST: inbox (también usado como fallback de polling) --------
  const refreshInbox = useCallback(async () => {
    if (typeof window === 'undefined') return;
    try {
      const res = await authFetch(`${getApiBase()}/notifications/inbox?page=1&size=${inboxSize}`);
      if (!res.ok) throw new Error(`inbox HTTP ${res.status}`);
      const data = await res.json();
      setItems((data.items ?? []) as InboxNotification[]);
      setUnreadCount(Number(data.unread_count ?? 0));
      setError(null);
    } catch (e) {
      // Silencioso si hay WS activo; el error solo importa si tampoco hay WS
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [inboxSize]);

  // -------- marcar leído con optimistic update --------
  const markRead = useCallback(async (id: string) => {
    let wasUnread = false;
    setItems((prev) =>
      prev.map((n) => {
        if (n.id === id && n.status !== 'LEIDO') {
          wasUnread = true;
          return { ...n, status: 'LEIDO', read_at: new Date().toISOString() };
        }
        return n;
      })
    );
    if (wasUnread) setUnreadCount((c) => Math.max(0, c - 1));
    try {
      const res = await authFetch(`${getApiBase()}/notifications/${id}/read`, { method: 'PATCH' });
      if (!res.ok) throw new Error(`read HTTP ${res.status}`);
    } catch (e) {
      console.warn('markRead fallback:', e);
      refreshInbox(); // reintento por consistencia
    }
  }, [refreshInbox]);

  // -------- WebSocket con heartbeat + backoff (patrón tracking) --------
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      const token = getToken();
      if (!token) {
        setError('Sin token: notificaciones en modo polling');
        return;
      }
      let socket: WebSocket;
      try {
        socket = new WebSocket(`${getWsBaseUrl()}/notifications/ws?token=${encodeURIComponent(token)}`);
      } catch (e) {
        setError(String(e));
        scheduleReconnect();
        return;
      }
      wsRef.current = socket;

      socket.onopen = () => {
        setIsConnected(true);
        retriesRef.current = 0;
        setError(null);
        // Heartbeat 30s igual que tracking
        heartbeatTimerRef.current = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            try { socket.send(JSON.stringify({ type: 'ping' })); } catch { /* noop */ }
          }
        }, heartbeatSec * 1000);
      };

      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'CONNECTED') {
            if (typeof msg.unread_count === 'number') setUnreadCount(msg.unread_count);
          } else if (msg.type === 'NEW_NOTIFICATION') {
            const payload: InboxNotification = {
              id: String(msg.id ?? msg.data?.id ?? crypto.randomUUID()),
              template_code: msg.template_code ?? msg.data?.template_code ?? null,
              channel: String(msg.channel ?? msg.data?.channel ?? 'IN_APP'),
              status: String(msg.status ?? msg.data?.status ?? 'PENDIENTE'),
              title: msg.title ?? msg.data?.title ?? null,
              body: msg.body ?? msg.data?.body ?? null,
              created_at: msg.created_at ?? msg.data?.created_at ?? new Date().toISOString(),
              read_at: msg.read_at ?? msg.data?.read_at ?? null,
            };
            setItems((prev) => {
              if (prev.some((n) => n.id === payload.id)) return prev;
              return [payload, ...prev].slice(0, 50);
            });
            if (payload.status !== 'LEIDO') setUnreadCount((c) => c + 1);
          }
          // pong: nada que hacer (mantiene la conexión viva)
        } catch {
          /* mensaje no JSON: ignorar */
        }
      };

      socket.onerror = () => setError('Error de WebSocket de notificaciones');

      socket.onclose = (ev) => {
        setIsConnected(false);
        if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
        if (closedRef.current) return;
        if (ev.code === 1008) {
          // Token inválido/expirado: NO reintentar (regla heredada), depender de polling
          setError('Token inválido o expirado para WS de notificaciones');
          return;
        }
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closedRef.current) return;
      if (retriesRef.current >= maxRetries) {
        setError('Notificaciones en modo polling (WS agotó reintentos)');
        return;
      }
      const delay = Math.min(300 * Math.pow(2, retriesRef.current), 15000);
      retriesRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    connect();

    // Fallback polling cada 60s (solo refresca si el WS no está vivo)
    pollTimerRef.current = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        refreshInbox();
      }
    }, pollFallbackSec * 1000);

    // Snapshot inicial inmediato
    refreshInbox();

    return () => {
      closedRef.current = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      try { wsRef.current?.close(); } catch { /* noop */ }
      wsRef.current = null;
    };
  }, [enabled, maxRetries, heartbeatSec, pollFallbackSec, reconnectIntervalMs, refreshInbox]);

  return { items, unreadCount, isConnected, error, markRead, refreshInbox };
}
