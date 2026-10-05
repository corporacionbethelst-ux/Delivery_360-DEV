/**
 * Fase 8 - Hook de WebSocket para tracking en tiempo real.
 *
 * Conexión al backend FastAPI: ws(s)://<host>/api/v1/tracking/ws/{channel}?token=<jwt>
 * Características:
 *  - Reconexión con backoff exponencial (300ms -> máx 15s, máximo de reintentos configurable)
 *  - Heartbeat ping cada 30s para mantener la conexión viva
 *  - Maneja mensajes POSITION_UPDATE / BATCH_UPDATE / CONNECTED / pong
 */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export interface RiderPosition {
  riderId: string;
  lat: number;
  lng: number;
  speedKmh?: number | null;
  headingDegrees?: number | null;
  accuracyMeters?: number | null;
  timestamp?: string | null;
}

interface UseTrackingWebSocketOptions {
  reconnectIntervalMs?: number;
  maxRetries?: number;
  heartbeatSec?: number;
  enabled?: boolean;
}

interface UseTrackingWebSocketReturn {
  positions: RiderPosition[];
  lastUpdate: Date | null;
  isConnected: boolean;
  error: string | null;
  reconnect: () => void;
  latencyMs: number | null;
}

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!raw) return null;
    // Soporta tanto JWT plano como JSON envuelto {"token": "..."}
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
  const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
  return api.replace(/^http/, 'ws').replace(/\/$/, '');
}

export function useTrackingWebSocket(
  channel: string, // p.ej. "dashboard", "rider:<uuid>", "order:<uuid>"
  options: UseTrackingWebSocketOptions = {}
): UseTrackingWebSocketReturn {
  const {
    reconnectIntervalMs = 3000,
    maxRetries = 5,
    heartbeatSec = 30,
    enabled = true,
  } = options;

  const [positions, setPositions] = useState<RiderPosition[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const heartbeatRef = useRef<NodeJS.Interval | null>(null);
  const pingSentAtRef = useRef<number | null>(null);

  const updateOrAddPosition = useCallback((pos: RiderPosition) => {
    setPositions((prev) => {
      const idx = prev.findIndex((p) => p.riderId === pos.riderId);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = pos;
        return next;
      }
      return [...prev, pos];
    });
    setLastUpdate(new Date());
  }, []);

  const connect = useCallback(() => {
    if (typeof window === 'undefined' || !enabled) return;

    const token = getToken();
    if (!token) {
      setError('Sin token de autenticación para WebSocket');
      return;
    }

    const url = `${getWsBaseUrl()}/tracking/ws/${encodeURIComponent(channel)}?token=${encodeURIComponent(token)}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e: any) {
      setError(`No se pudo abrir WebSocket: ${e?.message || e}`);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setError(null);
      retriesRef.current = 0;

      // Heartbeat: ping periódico para evitar cierres por inactividad
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          pingSentAtRef.current = performance.now();
          ws.send(JSON.stringify({ action: 'ping' }));
        }
      }, heartbeatSec * 1000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'POSITION_UPDATE' && data.payload) {
          updateOrAddPosition(data.payload as RiderPosition);
        } else if (data.type === 'BATCH_UPDATE' && Array.isArray(data.payload)) {
          data.payload.forEach((p: RiderPosition) => updateOrAddPosition(p));
        } else if (data.type === 'pong' && pingSentAtRef.current) {
          setLatencyMs(Math.round(performance.now() - pingSentAtRef.current));
          pingSentAtRef.current = null;
        } else if (data.type === 'error') {
          setError(data.message || 'Error reportado por el servidor');
        }
      } catch {
        /* mensaje no JSON: ignorar */
      }
    };

    ws.onerror = () => setError('Error en la conexión WebSocket');

    ws.onclose = (ev) => {
      setIsConnected(false);
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      // No reconectar si el servidor cerró por política (4001/1008: auth inválida)
      const authClosed = ev.code === 1008 || ev.code === 4001;
      if (authClosed) {
        setError('No autorizado para este canal de tracking');
        return;
      }
      if (retriesRef.current < maxRetries) {
        const delay = Math.min(
          reconnectIntervalMs * Math.pow(2, retriesRef.current),
          15000
        );
        retriesRef.current += 1;
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      } else {
        setError('Se agotaron los reintentos de conexión. Recarga la página.');
      }
    };
  }, [channel, enabled, heartbeatSec, maxRetries, reconnectIntervalMs, updateOrAddPosition]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { positions, lastUpdate, isConnected, error, reconnect: connect, latencyMs };
}
