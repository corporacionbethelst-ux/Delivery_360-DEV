'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { financialService, type FinancialOrdersReport, type FinancialReconciliation } from '@/services/financial.service';
import { capturePrivateTask } from '@/lib/private-task';
import { ordersReportCsv, prepareReportQuery, REPORT_EXPORT_LIMIT, REPORT_PREVIEW_LIMIT, type ReportRange } from '@/lib/financial-report-contract';
import { downloadCSV } from '@/lib/csv-export';

type Mode = 'preview' | 'export';
interface Snapshot { range: ReportRange; orders: FinancialOrdersReport; reconciliation: FinancialReconciliation }
interface Failure { message: string; exportBlocked?: boolean; retry?: { range: ReportRange; mode: Mode } }
const same = (a: ReportRange, b: ReportRange) => (a.date_from ?? '') === (b.date_from ?? '') && (a.date_to ?? '') === (b.date_to ?? '');

export function useFinancialReports() {
  const [draft, setDraftState] = useState({ start: '', end: '' });
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [pending, setPending] = useState<Mode | null>('preview');
  const [error, setError] = useState<Failure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const alive = useRef(false), sequence = useRef(0), draftVersion = useRef(0), exportBusy = useRef(false);
  const latest = useRef<Snapshot | null>(null), draftRef = useRef(draft);
  const draftRange = () => ({ date_from: draftRef.current.start || undefined, date_to: draftRef.current.end || undefined });

  const load = useCallback(async (input: ReportRange, mode: Mode) => {
    if (!alive.current || mode === 'export' && exportBusy.current) return;
    const rawDraft = { date_from: draftRef.current.start || undefined, date_to: draftRef.current.end || undefined };
    if (mode === 'export' && (!latest.current || !same(input, latest.current.range) || !same(input, rawDraft))) {
      setError({ message: 'Aplica los filtros antes de exportar ese rango.' }); return;
    }
    const ticket = ++sequence.current, version = draftVersion.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    let range: ReportRange = input, phase: 'query' | 'read' | 'limit' | 'download' = 'query';
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    exportBusy.current = mode === 'export';
    setPending(mode); setError(null); setNotice(null);
    try {
      range = prepareReportQuery(input, false);
      phase = 'read'; task = capturePrivateTask();
      const [orders, reconciliation] = await Promise.all([
        financialService.getOrdersReport({ ...range, limit: mode === 'export' ? REPORT_EXPORT_LIMIT : REPORT_PREVIEW_LIMIT, offset: 0 }),
        financialService.getReconciliation(range),
      ]);
      task.assertCurrent();
      if (!current() || mode === 'export' && version !== draftVersion.current) return;
      if (mode === 'export' && orders.total_orders > REPORT_EXPORT_LIMIT) {
        phase = 'limit';
        throw new Error(`El rango contiene ${orders.total_orders} órdenes. El máximo por CSV es ${REPORT_EXPORT_LIMIT}; reduce el rango para descargarlo completo.`);
      }
      if (mode === 'export' && orders.rows.length !== orders.total_orders) throw new Error('Exportación incompleta');
      const next = { range: { ...range }, orders, reconciliation };
      latest.current = next; setSnapshot(next);
      if (mode === 'export') {
        if (!orders.rows.length) { setNotice('No hay órdenes en el rango confirmado para exportar.'); return; }
        phase = 'download';
        const data = ordersReportCsv(orders);
        task.assertCurrent();
        if (!current() || version !== draftVersion.current) return;
        if (!downloadCSV(data, `reporte_ordenes_${range.date_from ?? 'sin_inicio'}_${range.date_to ?? 'sin_fin'}_${orders.rows.length}_filas`)) throw new Error('No se generó el archivo');
        if (current()) setNotice(`CSV generado con ${orders.rows.length} ${orders.rows.length === 1 ? 'orden' : 'órdenes'} del rango confirmado. Revisa la descarga del navegador.`);
      }
    } catch (failure) {
      if (current()) setError({
        message: phase === 'query' ? 'Revisa las fechas: el inicio no puede ser posterior al fin.'
          : phase === 'limit' && failure instanceof Error ? failure.message
          : phase === 'download' ? 'No se pudo generar la descarga CSV. Los datos consultados se conservan.'
          : 'No se pudo comprobar el reporte y su conciliación. Se conservan los últimos datos confirmados.',
        exportBlocked: phase === 'limit',
        retry: phase === 'read' || phase === 'download' ? { range: { ...range }, mode } : undefined,
      });
    } finally {
      if (current()) { exportBusy.current = false; setPending(null); }
    }
  }, []);

  useEffect(() => {
    alive.current = true; void load({}, 'preview');
    return () => { alive.current = false; sequence.current++; exportBusy.current = false; };
  }, [load]);

  const setDraft = (field: 'start' | 'end', value: string) => {
    if (draftRef.current[field] === value) return;
    draftRef.current = { ...draftRef.current, [field]: value }; draftVersion.current++;
    setDraftState(draftRef.current); setNotice(null); setError(null);
    if (exportBusy.current) {
      sequence.current++; exportBusy.current = false; setPending(null);
      setError({ message: 'La exportación se canceló porque cambiaron las fechas. Aplica el rango y vuelve a exportar.' });
    }
  };
  const dirty = !!snapshot && !same(snapshot.range, { date_from: draft.start || undefined, date_to: draft.end || undefined });
  const canExport = !!snapshot && !dirty && !pending && !error?.exportBlocked && snapshot.orders.total_orders > 0 && snapshot.orders.total_orders <= REPORT_EXPORT_LIMIT;
  const apply = () => load(draftRange(), 'preview');
  const exportCsv = () => latest.current ? load(latest.current.range, 'export') : undefined;
  const retry = () => error?.retry ? load(error.retry.range, error.retry.mode) : undefined;
  const retryDisabled = !!pending || error?.retry?.mode === 'export' && !same(error.retry.range, draftRange());
  return { draft, setDraft, snapshot, dirty, pending, error, notice, canExport, apply, exportCsv, retry, retryDisabled };
}
