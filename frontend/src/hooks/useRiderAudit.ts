'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { capturePrivateTask } from '@/lib/private-task';
import { AUDIT_PAGE_SIZE, initialAuditOffsets, type AuditOffsets } from '@/lib/rider-audit-contract';
import { readRiderAudit, type RiderAuditSnapshot } from '@/services/rider-audit.service';

export function useRiderAudit(riderId: string) {
  const [data, setData] = useState<RiderAuditSnapshot | null>(null), [isLoading, setLoading] = useState(true), [error, setError] = useState<string | null>(null);
  const alive = useRef(false), sequence = useRef(0), busy = useRef(false), latest = useRef<RiderAuditSnapshot | null>(null), attempt = useRef(initialAuditOffsets);
  const load = useCallback(async (offsets: AuditOffsets, restart = false) => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const assertActive = () => { if (!alive.current || sequence.current !== ticket) throw new Error('Lectura retirada'); };
    const current = () => alive.current && sequence.current === ticket && (!task || task.isCurrent());
    busy.current = true; attempt.current = offsets; setLoading(true); setError(null);
    try {
      task = capturePrivateTask();
      const next = await readRiderAudit(riderId, offsets, assertActive);
      task.assertCurrent(); assertActive();
      const previous = latest.current;
      if (previous && !restart) {
        for (const key of ['orders', 'deliveries', 'transactions'] as const) {
          if (Math.abs(previous.offsets[key] - offsets[key]) !== AUDIT_PAGE_SIZE) continue;
          const ids = new Set(previous[key].rows.map(row => row.id));
          if (next[key].rows.some(row => ids.has(row.id))) throw new Error('Las páginas cambiaron');
        }
      }
      latest.current = next; setData(next);
    } catch { if (current()) setError('No se pudo comprobar el conjunto de auditoría. Se conserva la última consulta confirmada. Reintenta o vuelve al inicio si cambiaron las páginas.'); }
    finally { if (current()) { busy.current = false; setLoading(false); } }
  }, [riderId]);
  useEffect(() => {
    const requests = sequence;
    alive.current = true; latest.current = null; setData(null); void load(initialAuditOffsets);
    return () => { alive.current = false; requests.current++; };
  }, [load]);
  const navigate = (key: keyof AuditOffsets, direction: -1 | 1) => {
    const snapshot = latest.current;
    if (busy.current || !snapshot || direction === 1 && !snapshot[key].hasNext || direction === -1 && snapshot.offsets[key] === 0) return;
    return load({ ...snapshot.offsets, [key]: snapshot.offsets[key] + direction * AUDIT_PAGE_SIZE });
  };
  return { data, isLoading, error, navigate,
    refresh: () => load(latest.current?.offsets ?? initialAuditOffsets),
    retry: () => load(attempt.current), first: () => load(initialAuditOffsets, true) };
}
