'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { readAuditCatalogPage } from '@/services/rider-audit-catalog.service';
import { AUDIT_PAGE_SIZE, RIDER_AUDIT_STATUSES } from '@/lib/rider-audit-contract';
import { initialAuditCatalogQuery, auditCatalogCsv, searchAuditCatalog, type AuditCatalogQuery, type AuditCatalogSnapshot } from '@/lib/rider-audit-catalog';
import { capturePrivateTask } from '@/lib/private-task';
import { downloadCSV } from '@/lib/csv-export';

export function useRiderAuditCatalog() {
  const [data, setData] = useState<AuditCatalogSnapshot | null>(null), [pending, setPending] = useState<AuditCatalogQuery | null>(initialAuditCatalogQuery);
  const [error, setError] = useState<string | null>(null), [exportError, setExportError] = useState<string | null>(null), [search, setSearchState] = useState('');
  const alive = useRef(false), sequence = useRef(0), busy = useRef(false), failed = useRef(false);
  const latest = useRef<AuditCatalogSnapshot | null>(null), attempt = useRef(initialAuditCatalogQuery), restartAttempt = useRef(false), searchRef = useRef('');
  const load = useCallback(async (query: AuditCatalogQuery, restart = false) => {
    if (!alive.current) return;
    const ticket = ++sequence.current, previous = latest.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    busy.current = true; failed.current = false; attempt.current = query; restartAttempt.current = restart; setPending(query); setError(null); setExportError(null);
    try {
      task = capturePrivateTask();
      const next = await readAuditCatalogPage(query);
      task.assertCurrent(); if (!current()) return;
      if (!restart && previous && previous.query.status === query.status && previous.query.online === query.online && Math.abs(previous.query.offset - query.offset) === AUDIT_PAGE_SIZE) {
        const riders = new Set(previous.rows.map(row => row.rider_id)), users = new Set(previous.rows.map(row => row.user_id));
        if (next.rows.some(row => riders.has(row.rider_id) || users.has(row.user_id))) throw new Error('Las páginas cambiaron');
      }
      latest.current = next; setData(next);
    } catch { if (current()) { failed.current = true; setError('No se pudo comprobar la consulta de auditoría. Se conserva la última página confirmada. Reintenta o vuelve al inicio si cambiaron las páginas.'); } }
    finally { if (current()) { busy.current = false; setPending(null); } }
  }, []);
  useEffect(() => { const requests = sequence; alive.current = true; void load(initialAuditCatalogQuery); return () => { alive.current = false; requests.current++; }; }, [load]);
  const navigate = (direction: -1 | 1) => {
    const snapshot = latest.current;
    if (busy.current || !snapshot || direction === 1 && !snapshot.hasNext || direction === -1 && snapshot.query.offset === 0) return;
    return load({ ...snapshot.query, offset: snapshot.query.offset + direction * AUDIT_PAGE_SIZE });
  };
  const setFilter = (field: 'status' | 'online', value: string) => {
    if (field === 'status' ? value !== 'ALL' && !RIDER_AUDIT_STATUSES.includes(value as never) : !['ALL', 'true', 'false'].includes(value)) return;
    const query = busy.current ? attempt.current : latest.current?.query ?? initialAuditCatalogQuery;
    return load({ ...query, [field]: value, offset: 0 }, true);
  };
  const setSearch = (value: string) => { searchRef.current = value; setSearchState(value); setExportError(null); };
  const exportPage = () => {
    const snapshot = latest.current;
    if (!snapshot || !alive.current || busy.current || failed.current) return;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask(); const rows = searchAuditCatalog(snapshot.rows, searchRef.current);
      if (!rows.length) return;
      const csv = auditCatalogCsv(rows, { ...snapshot.query, search: searchRef.current }); task.assertCurrent();
      if (!downloadCSV(csv, `auditoria_riders_pagina_${snapshot.query.offset / AUDIT_PAGE_SIZE + 1}_${rows.length}_filas`)) throw new Error('No se generó CSV');
      setExportError(null);
    } catch { if (alive.current && (!task || task.isCurrent())) setExportError('No se pudo generar el CSV de la página. Los datos se conservan.'); }
  };
  return { data, error, exportError, search, setSearch, setFilter, exportPage, navigate,
    selected: pending ?? data?.query ?? initialAuditCatalogQuery, isLoading: pending !== null,
    visibleRows: searchAuditCatalog(data?.rows ?? [], search), refresh: () => load(latest.current?.query ?? initialAuditCatalogQuery),
    retry: () => load(attempt.current, restartAttempt.current), first: () => load({ ...(latest.current?.query ?? initialAuditCatalogQuery), offset: 0 }, true) };
}
