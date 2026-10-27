/** Private IN_APP inbox: each transport and result belongs to a verified session. */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { getStoredTokens } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';

export interface InboxNotification {
  id: string;
  template_code?: string | null;
  channel: string;
  status: string;
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
interface Session {
  userId: string;
  revision: number;
  sequence: number;
  requests: Set<AbortController>;
}
interface Snapshot {
  session: Session | null;
  items: InboxNotification[];
  unreadCount: number;
  isConnected: boolean;
  error: string | null;
}
const empty = { items: [], unreadCount: 0, isConnected: false, error: null };
const apiBase = () =>
  (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');
function wsBase(): string {
  return (
    process.env.NEXT_PUBLIC_NOTIFICATIONS_WS ||
    process.env.WS_BASE_URL ||
    apiBase().replace(/^http/, 'ws')
  )
    .replace(/\/notifications\/ws\/?$/, '')
    .replace(/\/$/, '');
}
const validCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

export function useNotifications(options: UseNotificationsOptions = {}) {
  const {
    enabled = true,
    reconnectIntervalMs = 300,
    maxRetries = 5,
    heartbeatSec = 30,
    pollFallbackSec = 60,
    inboxSize = 10,
  } = options;
  const userId = useAuthStore((s) => (s.isAuthenticated ? s.user?.id : null));
  const revision = useAuthStore((s) => s.sessionRevision);
  const sessionRef = useRef<Session | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>({ ...empty, session: null });

  const current = useCallback((session: Session, token?: string) => {
    const auth = useAuthStore.getState();
    return (
      sessionRef.current === session &&
      auth.isAuthenticated &&
      auth.user?.id === session.userId &&
      auth.sessionRevision === session.revision &&
      (!token || getStoredTokens().accessToken === token)
    );
  }, []);
  const update = useCallback(
    (session: Session, apply: (state: Snapshot) => Snapshot) => {
      setSnapshot((previous) =>
        current(session)
          ? apply(previous.session === session ? previous : { ...empty, session })
          : previous
      );
    },
    [current]
  );

  const refreshInbox = useCallback(async () => {
    const session = sessionRef.current;
    const token = getStoredTokens().accessToken;
    if (!session || !token || !current(session, token)) return;
    const sequence = ++session.sequence;
    const controller = new AbortController();
    session.requests.add(controller);
    try {
      const response = await fetch(`${apiBase()}/notifications/inbox?page=1&size=${inboxSize}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('inbox unavailable');
      const data = await response.json();
      if (!current(session, token) || sequence !== session.sequence) return;
      const items = Array.isArray(data.items)
        ? data.items
            .filter(
              (item: InboxNotification) =>
                item && typeof item.id === 'string' && item.channel === 'IN_APP'
            )
            .slice(0, 50)
        : [];
      update(session, (previous) => ({
        ...previous,
        items,
        unreadCount: validCount(data.unread_count) ? data.unread_count : 0,
        error: null,
      }));
    } catch {
      if (current(session, token) && sequence === session.sequence && !controller.signal.aborted) {
        update(session, (previous) => ({ ...previous, error: 'No se pudo actualizar el inbox' }));
      }
    } finally {
      session.requests.delete(controller);
    }
  }, [inboxSize, current, update]);

  const markRead = useCallback(
    async (id: string) => {
      const session = sessionRef.current;
      const token = getStoredTokens().accessToken;
      if (!id || !session || !token || !current(session, token)) return;
      ++session.sequence;
      update(session, (previous) => {
        const wasUnread = previous.items.some((n) => n.id === id && n.status !== 'LEIDO');
        return {
          ...previous,
          items: previous.items.map((n) =>
            n.id === id ? { ...n, status: 'LEIDO', read_at: new Date().toISOString() } : n
          ),
          unreadCount: Math.max(0, previous.unreadCount - (wasUnread ? 1 : 0)),
        };
      });
      const controller = new AbortController();
      session.requests.add(controller);
      try {
        const response = await fetch(`${apiBase()}/notifications/${encodeURIComponent(id)}/read`, {
          method: 'PATCH',
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('read unavailable');
      } catch {
        if (current(session, token) && !controller.signal.aborted) void refreshInbox();
      } finally {
        session.requests.delete(controller);
      }
    },
    [current, update, refreshInbox]
  );

  useEffect(() => {
    if (!enabled || !userId || typeof window === 'undefined') return;
    const session: Session = { userId, revision, sequence: 0, requests: new Set() };
    sessionRef.current = session;
    setSnapshot({ ...empty, session });
    let retries = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let heartbeatTimer: ReturnType<typeof setInterval> | undefined;
    let pollingRequired = true;
    let socketToken: string | null = null;
    let policyClosed = false;
    const disconnect = () => {
      clearInterval(heartbeatTimer);
      heartbeatTimer = undefined;
      const socket = wsRef.current;
      wsRef.current = null;
      if (socket) {
        socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
        try {
          socket.close();
        } catch {
          /* Already closed. */
        }
      }
    };
    const scheduleReconnect = () => {
      if (!current(session) || retries >= maxRetries || policyClosed) return;
      clearTimeout(reconnectTimer);
      const delay = Math.min(Math.max(1, reconnectIntervalMs) * 2 ** retries++, 15000);
      reconnectTimer = setTimeout(connect, delay);
    };
    const connect = () => {
      if (!current(session)) return;
      clearTimeout(reconnectTimer);
      disconnect();
      pollingRequired = true;
      update(session, (previous) => ({ ...previous, isConnected: false }));
      const token = getStoredTokens().accessToken;
      socketToken = token;
      policyClosed = false;
      if (!token) return;
      let socket: WebSocket;
      try {
        socket = new WebSocket(`${wsBase()}/notifications/ws?token=${encodeURIComponent(token)}`);
      } catch {
        update(session, (previous) => ({
          ...previous,
          error: 'No se pudo conectar con notificaciones',
        }));
        scheduleReconnect();
        return;
      }
      wsRef.current = socket;
      const live = () => wsRef.current === socket && current(session, token);
      socket.onopen = () => {
        if (!live()) return;
        retries = 0;
        update(session, (previous) => ({ ...previous, isConnected: true, error: null }));
        clearInterval(heartbeatTimer);
        heartbeatTimer = setInterval(() => {
          if (live() && socket.readyState === WebSocket.OPEN) {
            try {
              socket.send(JSON.stringify({ type: 'ping' }));
            } catch {
              /* Polling remains available. */
            }
          }
        }, heartbeatSec * 1000);
      };
      socket.onmessage = (event) => {
        if (!live()) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'CONNECTED') {
            pollingRequired = msg.realtime_available === false;
            update(session, (previous) => ({
              ...previous,
              isConnected: !pollingRequired,
              unreadCount: validCount(msg.unread_count) ? msg.unread_count : previous.unreadCount,
              error: pollingRequired
                ? 'Notificaciones en modo polling: tiempo real no disponible'
                : null,
            }));
          } else if (msg.type === 'NEW_NOTIFICATION') {
            const payload = msg.data ?? msg;
            if (typeof payload.id !== 'string' || !payload.id || payload.channel !== 'IN_APP')
              return;
            ++session.sequence;
            const item: InboxNotification = {
              id: payload.id,
              channel: 'IN_APP',
              status: String(payload.status ?? 'PENDIENTE'),
              template_code: payload.template_code ?? null,
              title: payload.title ?? null,
              body: payload.body ?? null,
              created_at: payload.created_at ?? null,
              read_at: payload.read_at ?? null,
            };
            update(session, (previous) => {
              const exists = previous.items.some((n) => n.id === item.id);
              return {
                ...previous,
                items: exists
                  ? previous.items.map((n) => (n.id === item.id ? { ...n, ...item } : n))
                  : [item, ...previous.items].slice(0, 50),
                unreadCount: validCount(msg.unread_count)
                  ? msg.unread_count
                  : previous.unreadCount + (!exists && item.status !== 'LEIDO' ? 1 : 0),
              };
            });
            // A fresh SQL snapshot also recovers history when this event overtook the initial request.
            void refreshInbox();
          }
        } catch {
          /* Malformed events cannot replace the inbox. */
        }
      };
      socket.onerror = () => {
        if (live())
          update(session, (previous) => ({
            ...previous,
            error: 'Error de WebSocket de notificaciones',
          }));
      };
      socket.onclose = (event) => {
        if (!live()) return;
        pollingRequired = true;
        clearInterval(heartbeatTimer);
        heartbeatTimer = undefined;
        policyClosed = event.code === 1008;
        update(session, (previous) => ({ ...previous, isConnected: false }));
        scheduleReconnect();
      };
    };
    connect();
    void refreshInbox();
    const pollTimer = setInterval(() => {
      if (!current(session)) return;
      if (getStoredTokens().accessToken !== socketToken) {
        connect();
        void refreshInbox();
      } else if (pollingRequired || wsRef.current?.readyState !== WebSocket.OPEN) {
        void refreshInbox();
      }
    }, pollFallbackSec * 1000);
    return () => {
      if (sessionRef.current === session) sessionRef.current = null;
      ++session.sequence;
      session.requests.forEach((controller) => controller.abort());
      session.requests.clear();
      clearTimeout(reconnectTimer);
      clearInterval(pollTimer);
      disconnect();
    };
  }, [
    enabled,
    userId,
    revision,
    maxRetries,
    heartbeatSec,
    pollFallbackSec,
    reconnectIntervalMs,
    refreshInbox,
    current,
    update,
  ]);

  const visible =
    enabled &&
    userId &&
    snapshot.session?.userId === userId &&
    snapshot.session?.revision === revision
      ? snapshot
      : empty;
  return {
    items: visible.items,
    unreadCount: visible.unreadCount,
    isConnected: visible.isConnected,
    error: visible.error,
    markRead,
    refreshInbox,
  };
}
