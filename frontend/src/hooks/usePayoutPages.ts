'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { capturePrivateTask } from '@/lib/private-task';
import { payoutService, type Payout } from '@/services/payout.service';

export const PAYOUT_PAGE_SIZE = 50;
export const PAYOUT_FILTER_STATUSES = ['PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO'] as const;
export type PayoutFilterStatus = 'ALL' | typeof PAYOUT_FILTER_STATUSES[number];
interface Query { status: PayoutFilterStatus; offset: number; cursors: (string | null)[] }
interface Snapshot extends Query { rows: Payout[]; nextCursor: string | null; hasNext: boolean; loaded: boolean; revision: number }
const initial: Snapshot = { rows: [], status: 'ALL', offset: 0, cursors: [null], nextCursor: null, hasNext: false, loaded: false, revision: 0 };
class ChangedPageError extends Error {}

/** Offset is only a local page label. HTTP navigation uses server cursors. */
export function usePayoutPages(enabled = true) {
  const [snapshot, setSnapshot] = useState<Snapshot>(initial);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [pendingStatus, setPendingStatus] = useState<PayoutFilterStatus | null>(null);
  const latest = useRef(initial), attempt = useRef<Query>(initial);
  const alive = useRef(false), sequence = useRef(0), busy = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const load = useCallback(async (query: Query) => {
    if (!enabled || !alive.current) return;
    const ticket = ++sequence.current, previous = latest.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    attempt.current = query;
    busy.current = true;
    setIsLoading(true); setError(null); setPendingStatus(query.status);
    try {
      task = capturePrivateTask();
      const response = await payoutService.getPage({ limit: PAYOUT_PAGE_SIZE, cursor: query.cursors[query.offset / PAYOUT_PAGE_SIZE],
        status: query.status === 'ALL' ? undefined : query.status });
      task.assertCurrent();
      if (!current()) return;
      const rows = response.items;
      // A contradictory server page or a changed backward read must not silently
      // duplicate rows. A cursor does not freeze mutable statuses or timestamps.
      if (previous.loaded && previous.status === query.status && Math.abs(previous.offset - query.offset) === PAYOUT_PAGE_SIZE) {
        const previousIds = new Set(previous.rows.map(row => row.id));
        if (rows.some(row => previousIds.has(row.id))) throw new ChangedPageError();
      }
      const next: Snapshot = { ...query, rows, nextCursor: response.next_cursor, hasNext: response.next_cursor !== null, loaded: true, revision: previous.revision + 1 };
      latest.current = next; setSnapshot(next);
    } catch (failure) {
      if (current()) setError(failure instanceof ChangedPageError
        ? 'El historial cambió entre páginas. Vuelve al inicio para consultarlo de nuevo.'
        : 'No se pudo cargar la consulta de retiros. Se conservan los últimos datos disponibles.');
    } finally {
      if (current()) { busy.current = false; setIsLoading(false); setPendingStatus(null); }
    }
  }, [enabled]);

  useEffect(() => {
    if (enabled) void load({ status: 'ALL', offset: 0, cursors: [null] });
    else {
      sequence.current++; busy.current = false; latest.current = initial;
      setSnapshot(initial); setError(null); setPendingStatus(null); setIsLoading(false);
    }
  }, [enabled, load]);

  const next = useCallback(() => {
    const s = latest.current;
    if (!busy.current && s.loaded && s.nextCursor) return load({ status: s.status, offset: s.offset + PAYOUT_PAGE_SIZE, cursors: [...s.cursors, s.nextCursor] });
  }, [load]);
  const previous = useCallback(() => {
    const s = latest.current;
    if (!busy.current && s.offset > 0) return load({ status: s.status, offset: s.offset - PAYOUT_PAGE_SIZE, cursors: s.cursors.slice(0, -1) });
  }, [load]);
  const first = useCallback(() => load({ status: latest.current.status, offset: 0, cursors: [null] }), [load]);
  const refresh = useCallback(() => load(latest.current), [load]);
  const retry = useCallback(() => load(attempt.current), [load]);
  const setStatus = useCallback((value: string) => {
    if (value !== 'ALL' && !PAYOUT_FILTER_STATUSES.includes(value as never)) return;
    return load({ status: value as PayoutFilterStatus, offset: 0, cursors: [null] });
  }, [load]);

  return { ...snapshot, isLoading, error, selectedStatus: pendingStatus ?? snapshot.status, next, previous, first, refresh, retry, setStatus };
}

export type PayoutPages = ReturnType<typeof usePayoutPages>;
