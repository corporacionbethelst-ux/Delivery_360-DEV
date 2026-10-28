/** Tracking transport bound to the verified account, credential generation and socket instance. */
'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getStoredTokens } from '@/lib/auth-session';
import {
  useRealtimeIdentity,
  currentRealtimeIdentity,
  RealtimeIdentity,
} from '@/hooks/useRealtimeIdentity';
import {
  realtimeUrl,
  trackingChannel,
  readPosition,
  mergePositions,
  boundedInteger,
  RiderPosition,
} from '@/lib/realtime-client';
export type { RiderPosition } from '@/lib/realtime-client';
interface Options {
  reconnectIntervalMs?: number;
  maxRetries?: number;
  heartbeatSec?: number;
  enabled?: boolean;
  openTimeoutMs?: number;
  maxPositions?: number;
}
interface Snapshot {
  identity: RealtimeIdentity;
  channel: string;
  positions: RiderPosition[];
  lastUpdate: Date | null;
  isConnected: boolean;
  error: string | null;
  latencyMs: number | null;
}
const empty = {
  positions: [] as RiderPosition[],
  lastUpdate: null,
  isConnected: false,
  error: null,
  latencyMs: null,
};
export function useTrackingWebSocket(channel: string, options: Options = {}) {
  const { enabled = true } = options;
  const heartbeatSec = boundedInteger(options.heartbeatSec ?? 30, 30, 1, 300);
  const maxRetries = boundedInteger(options.maxRetries ?? 5, 5, 0, 10);
  const intervalMs = boundedInteger(options.reconnectIntervalMs ?? 3000, 3000, 1, 15000);
  const openTimeoutMs = boundedInteger(options.openTimeoutMs ?? 10000, 10000, 1, 30000);
  const maxPositions = boundedInteger(options.maxPositions ?? 1000, 1000, 1, 5000);
  const { userId, revision, generation, tokenRevision } = useRealtimeIdentity();
  const logical = trackingChannel(channel);
  const [state, setState] = useState<Snapshot>({
    ...empty,
    identity: { userId: null, revision, generation, tokenRevision },
    channel: '',
  });
  const manual = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!enabled || !userId || !logical) return;
    const identity = { userId, revision, generation, tokenRevision };
    if (!currentRealtimeIdentity(identity) || !getStoredTokens().accessToken) return;
    let active = true,
      socket: WebSocket | null = null,
      retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let openDeadline: ReturnType<typeof setTimeout> | undefined;
    let pingAt: number | null = null;
    const current = () => active && currentRealtimeIdentity(identity);
    const update = (apply: (snapshot: Snapshot) => Snapshot) => {
      if (!current()) return;
      setState((previous) =>
        current()
          ? apply(
              previous.channel === logical &&
                previous.identity.userId === userId &&
                previous.identity.revision === revision &&
                previous.identity.generation === generation
                ? { ...previous, identity }
                : { ...empty, identity, channel: logical }
            )
          : previous
      );
    };
    const close = () => {
      clearTimeout(openDeadline);
      clearInterval(heartbeat);
      pingAt = null;
      const old = socket;
      socket = null;
      if (old) {
        old.onopen = old.onmessage = old.onclose = old.onerror = null;
        try {
          old.close();
        } catch {
          /* Also retire CONNECTING sockets. */
        }
      }
    };
    const schedule = () => {
      if (!current()) return;
      clearTimeout(reconnectTimer);
      if (retry >= maxRetries) {
        update((s) => ({ ...s, error: 'Se agotaron los reintentos de tracking' }));
        return;
      }
      const delay = Math.min(intervalMs * 2 ** retry++, 15000);
      reconnectTimer = setTimeout(connect, delay);
    };
    const connect = () => {
      if (!current()) return;
      clearTimeout(reconnectTimer);
      close();
      const token = getStoredTokens().accessToken;
      if (!token || !current()) return;
      update((s) => ({ ...s, isConnected: false, error: null, latencyMs: null }));
      let next: WebSocket;
      try {
        next = new WebSocket(realtimeUrl('tracking', token, logical));
      } catch {
        update((s) => ({ ...s, error: 'No se pudo abrir la conexión de tracking' }));
        schedule();
        return;
      }
      socket = next;
      const live = () => socket === next && current() && getStoredTokens().accessToken === token;
      openDeadline = setTimeout(() => {
        if (!live()) return;
        close();
        update((s) => ({
          ...s,
          isConnected: false,
          error: 'La conexión de tracking no respondió',
        }));
        schedule();
      }, openTimeoutMs);
      next.onopen = () => {
        if (!live()) return;
        clearTimeout(openDeadline);
        update((s) => ({ ...s, isConnected: true, error: null }));
        heartbeat = setInterval(() => {
          if (!live() || next.readyState !== WebSocket.OPEN) return;
          try {
            pingAt = performance.now();
            next.send(JSON.stringify({ action: 'ping' }));
          } catch {
            close();
            update((s) => ({
              ...s,
              isConnected: false,
              error: 'Se interrumpió la conexión de tracking',
            }));
            schedule();
          }
        }, heartbeatSec * 1000);
      };
      next.onmessage = (event) => {
        if (!live() || typeof event.data !== 'string' || event.data.length > 262144) return;
        try {
          const data = JSON.parse(event.data);
          if (!data || typeof data !== 'object') return;
          if (data.type === 'CONNECTED') {
            retry = 0;
            return;
          }
          if (data.type === 'pong' && pingAt !== null) {
            const latency = Math.max(0, Math.round(performance.now() - pingAt));
            pingAt = null;
            update((s) => ({ ...s, latencyMs: latency }));
            return;
          }
          if (data.type === 'error') {
            update((s) => ({ ...s, error: 'El servidor no pudo procesar el mensaje de tracking' }));
            return;
          }
          const payloads =
            data.type === 'POSITION_UPDATE'
              ? [data.payload]
              : data.type === 'BATCH_UPDATE' && Array.isArray(data.payload)
                ? data.payload.slice(0, maxPositions * 2)
                : [];
          const positions = payloads
            .map(readPosition)
            .filter((p: RiderPosition | null): p is RiderPosition => p !== null);
          if (positions.length)
            update((s) => ({
              ...s,
              positions: mergePositions(s.positions, positions, maxPositions),
              lastUpdate: new Date(),
            }));
        } catch {
          /* Malformed payloads cannot replace authorized map data. */
        }
      };
      next.onerror = () => {
        if (live()) update((s) => ({ ...s, error: 'Error en la conexión de tracking' }));
      };
      next.onclose = (event) => {
        if (!live()) return;
        close();
        update((s) => ({ ...s, isConnected: false, latencyMs: null }));
        if ([1008, 4001].includes(event.code)) {
          update((s) => ({
            ...s,
            positions: [],
            lastUpdate: null,
            error: 'No autorizado para este canal de tracking',
          }));
          return;
        }
        schedule();
      };
    };
    update((s) => ({ ...s, isConnected: false, error: null }));
    const reconnect = () => {
      if (current()) {
        retry = 0;
        connect();
      }
    };
    manual.current = reconnect;
    connect();
    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      close();
      if (manual.current === reconnect) manual.current = null;
    };
  }, [
    enabled,
    userId,
    revision,
    generation,
    tokenRevision,
    logical,
    heartbeatSec,
    maxRetries,
    intervalMs,
    openTimeoutMs,
    maxPositions,
  ]);
  const visible =
    enabled &&
    logical &&
    userId &&
    state.channel === logical &&
    state.identity.userId === userId &&
    state.identity.revision === revision &&
    state.identity.generation === generation
      ? state
      : empty;
  const reconnect = useCallback(() => {
    if (
      enabled &&
      logical &&
      currentRealtimeIdentity({ userId, revision, generation, tokenRevision })
    )
      manual.current?.();
  }, [enabled, logical, userId, revision, generation, tokenRevision]);
  return {
    positions: visible.positions,
    lastUpdate: visible.lastUpdate,
    isConnected: visible.isConnected && state.identity.tokenRevision === tokenRevision,
    error: !logical && enabled && userId ? 'Canal de tracking no válido' : visible.error,
    latencyMs: visible.latencyMs,
    reconnect,
  };
}
