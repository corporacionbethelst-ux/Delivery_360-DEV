'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { transactionService, type Transaction, type TransactionType } from '@/services/transaction.service';
import { TRANSACTION_STATUSES, TRANSACTION_TYPES, transactionCsv } from '@/lib/transaction-contract';
import { capturePrivateTask } from '@/lib/private-task';
import { downloadCSV } from '@/lib/csv-export';

export const TRANSACTION_PAGE_SIZE = 50;
export interface TransactionQuery { type: TransactionType | 'ALL'; status: typeof TRANSACTION_STATUSES[number] | 'ALL'; offset: number; restart?: boolean }
interface Snapshot extends TransactionQuery { rows: Transaction[]; hasNext: boolean; loaded: boolean }
const initial: Snapshot = { type: 'ALL', status: 'ALL', offset: 0, rows: [], hasNext: false, loaded: false };
class ChangedPageError extends Error {}
const matches = (rows: Transaction[], term: string) => rows.filter(row => [row.id, row.rider_id, row.description, row.reference_id, row.source_id].some(value => value?.toLowerCase().includes(term.trim().toLowerCase())));

export function useTransactionHistory() {
  const [snapshot, setSnapshot] = useState(initial), [pending, setPending] = useState<TransactionQuery | null>(initial);
  const [error, setError] = useState<string | null>(null), [exportError, setExportError] = useState<string | null>(null);
  const [search, setSearchState] = useState('');
  const alive = useRef(false), sequence = useRef(0), busy = useRef(false), failed = useRef(false);
  const latest = useRef(initial), attempt = useRef<TransactionQuery>(initial), searchRef = useRef('');
  const load = useCallback(async (query: TransactionQuery) => {
    if (!alive.current) return;
    const ticket = ++sequence.current, previous = latest.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    busy.current = true; attempt.current = query; failed.current = false;
    setPending(query); setError(null); setExportError(null);
    try {
      task = capturePrivateTask();
      const response = await transactionService.getAll({ type: query.type, status: query.status, limit: TRANSACTION_PAGE_SIZE + 1, offset: query.offset });
      task.assertCurrent(); if (!current()) return;
      const rows = response.slice(0, TRANSACTION_PAGE_SIZE);
      if (!query.restart && previous.loaded && previous.type === query.type && previous.status === query.status && Math.abs(previous.offset - query.offset) === TRANSACTION_PAGE_SIZE) {
        const ids = new Set(previous.rows.map(row => row.id));
        if (rows.some(row => ids.has(row.id))) throw new ChangedPageError();
      }
      const next = { ...query, rows, hasNext: response.length > TRANSACTION_PAGE_SIZE, loaded: true };
      latest.current = next; setSnapshot(next);
    } catch (failure) {
      if (current()) {
        failed.current = true;
        setError(failure instanceof ChangedPageError ? 'El historial cambió entre páginas. Vuelve al inicio para consultarlo de nuevo.' : 'No se pudo comprobar la consulta de transacciones. Se conserva la última página confirmada.');
      }
    } finally { if (current()) { busy.current = false; setPending(null); } }
  }, []);
  useEffect(() => { const requestSequence = sequence; alive.current = true; void load(initial); return () => { alive.current = false; requestSequence.current++; }; }, [load]);
  const next = () => { const s = latest.current; if (!busy.current && s.loaded && s.hasNext) return load({ type: s.type, status: s.status, offset: s.offset + TRANSACTION_PAGE_SIZE }); };
  const previous = () => { const s = latest.current; if (!busy.current && s.offset > 0) return load({ type: s.type, status: s.status, offset: s.offset - TRANSACTION_PAGE_SIZE }); };
  const first = () => load({ type: latest.current.type, status: latest.current.status, offset: 0, restart: true });
  const refresh = () => load({ type: latest.current.type, status: latest.current.status, offset: latest.current.offset });
  const retry = () => load(attempt.current);
  const setFilter = (field: 'type' | 'status', value: string) => {
    if (value !== 'ALL' && !(field === 'type' ? TRANSACTION_TYPES : TRANSACTION_STATUSES).includes(value as never)) return;
    const s = busy.current ? attempt.current : latest.current;
    return load({ type: s.type, status: s.status, [field]: value, offset: 0, restart: true } as TransactionQuery);
  };
  const setSearch = (value: string) => { searchRef.current = value; setSearchState(value); setExportError(null); };
  const exportPage = () => {
    const s = latest.current;
    if (busy.current || failed.current || !s.loaded || !alive.current) return;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      const rows = matches(s.rows, searchRef.current);
      if (!rows.length) return;
      const data = transactionCsv(rows, { type: s.type, status: s.status, offset: s.offset, search: searchRef.current });
      task.assertCurrent();
      if (!downloadCSV(data, `transacciones_pagina_${s.offset / TRANSACTION_PAGE_SIZE + 1}_${rows.length}_filas`)) throw new Error('No se generó CSV');
      setExportError(null);
    } catch { if (alive.current && (!task || task.isCurrent())) setExportError('No se pudo generar el CSV de la página. Los datos se conservan.'); }
  };
  return { ...snapshot, selected: pending ?? snapshot, isLoading: pending !== null, error, exportError, search, setSearch,
    visibleRows: matches(snapshot.rows, search), next, previous, first, refresh, retry, setFilter, exportPage };
}
