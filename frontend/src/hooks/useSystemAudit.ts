"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  auditService,
  type AuditFilters,
  type AuditLog,
  type AuditLogResponse,
  type AuditSummary,
} from "@/services/audit.service";
import { AUDIT_EXPORT_LIMIT, AUDIT_PAGE_SIZE } from "@/lib/system-audit";

type Query = Readonly<AuditFilters>;
type Snapshot = { page: AuditLogResponse; filters: Query; at: Date };
const equal = (a: Query, b: Query) => JSON.stringify(a) === JSON.stringify(b);
export function useSystemAudit() {
  const [query, setQuery] = useState<Query>({
      limit: AUDIT_PAGE_SIZE,
      offset: 0,
    }),
    queryRef = useRef(query);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [loading, setLoading] = useState(true),
    [readError, setReadError] = useState<string | null>(null);
  const [summary, setSummary] = useState<{
      data: AuditSummary;
      at: Date;
    } | null>(null),
    [summaryLoading, setSummaryLoading] = useState(true),
    [summaryError, setSummaryError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuditLog | null>(null),
    selectedRef = useRef<AuditLog | null>(null);
  const [detail, setDetail] = useState<AuditLog | null>(null),
    [detailLoading, setDetailLoading] = useState(false),
    [detailError, setDetailError] = useState<string | null>(null);
  const [exportScope, setExportScope] = useState<Snapshot | null>(null),
    exportRef = useRef<Snapshot | null>(null);
  const [exporting, setExporting] = useState(false),
    writing = useRef(false),
    [exportError, setExportError] = useState<string | null>(null),
    [downloaded, setDownloaded] = useState(false);
  const alive = useRef(false),
    sequence = useRef(0),
    summarySequence = useRef(0),
    detailSequence = useRef(0),
    urls = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const load = useCallback(async (target: Query) => {
    const ticket = ++sequence.current;
    setLoading(true);
    setReadError(null);
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      equal(target, queryRef.current);
    try {
      const page = await auditService.getLogs(target);
      if (current())
        setSnapshot({ page, filters: { ...target }, at: new Date() });
    } catch {
      if (current())
        setReadError(
          "No se pudo confirmar la consulta de auditoría. Se conservan los últimos datos cargados, si existen.",
        );
    } finally {
      if (current()) setLoading(false);
    }
  }, []);
  const loadSummary = useCallback(async () => {
    const ticket = ++summarySequence.current;
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const data = await auditService.getSummary(7);
      if (alive.current && ticket === summarySequence.current)
        setSummary({ data, at: new Date() });
    } catch {
      if (alive.current && ticket === summarySequence.current)
        setSummaryError(
          "No se pudo actualizar el resumen global. La consulta de eventos tiene su propio resultado.",
        );
    } finally {
      if (alive.current && ticket === summarySequence.current)
        setSummaryLoading(false);
    }
  }, []);
  useEffect(() => {
    const reads = sequence,
      summaries = summarySequence,
      details = detailSequence,
      downloads = urls.current;
    alive.current = true;
    void loadSummary();
    return () => {
      alive.current = false;
      reads.current++;
      summaries.current++;
      details.current++;
      downloads.forEach((timer, url) => {
        clearTimeout(timer);
        URL.revokeObjectURL(url);
      });
      downloads.clear();
    };
  }, [loadSummary]);
  useEffect(() => {
    void load(query);
  }, [load, query]);
  const closeDetail = () => {
    detailSequence.current++;
    selectedRef.current = null;
    setSelected(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
  };
  const closeExport = () => {
    if (writing.current) return;
    exportRef.current = null;
    setExportScope(null);
    setExportError(null);
  };
  const choose = (filters: Query) => {
    if (writing.current) return;
    const next = { ...filters };
    closeDetail();
    closeExport();
    sequence.current++;
    queryRef.current = next;
    setQuery(next);
    setDownloaded(false);
  };
  const refresh = () => {
    if (!writing.current) {
      void load(queryRef.current);
      void loadSummary();
    }
  };
  const matching = !!snapshot && equal(snapshot.filters, query),
    ready = !!snapshot && matching && !loading && !readError;
  const loadDetail = async (row: AuditLog) => {
    const ticket = ++detailSequence.current;
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const data = await auditService.getById(row.id);
      if (
        alive.current &&
        ticket === detailSequence.current &&
        selectedRef.current?.id === row.id
      )
        setDetail(data);
    } catch {
      if (alive.current && ticket === detailSequence.current)
        setDetailError(
          "No se pudo confirmar el detalle de este evento. Reintenta su consulta.",
        );
    } finally {
      if (alive.current && ticket === detailSequence.current)
        setDetailLoading(false);
    }
  };
  const openDetail = (row: AuditLog) => {
    if (!ready || writing.current) return;
    const captured = { ...row };
    selectedRef.current = captured;
    setSelected(captured);
    void loadDetail(captured);
  };
  const openExport = () => {
    if (!ready || !snapshot || writing.current) return;
    const captured = { ...snapshot, filters: { ...snapshot.filters } };
    exportRef.current = captured;
    setExportScope(captured);
    setExportError(null);
    setDownloaded(false);
  };
  const exportCsv = async () => {
    const captured = exportRef.current;
    if (!captured || writing.current || !alive.current) return;
    writing.current = true;
    setExporting(true);
    setExportError(null);
    let url: string | undefined, link: HTMLAnchorElement | undefined;
    try {
      const csv = await auditService.exportCsv({
        ...captured.filters,
        limit: AUDIT_EXPORT_LIMIT,
      });
      if (!alive.current || exportRef.current !== captured) return;
      url = URL.createObjectURL(
        new Blob([csv], { type: "text/csv;charset=utf-8;" }),
      );
      link = document.createElement("a");
      link.href = url;
      link.download = `audit_logs_${new Date().toLocaleDateString("sv-SE", { timeZone: "America/Caracas" })}.csv`;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      exportRef.current = null;
      setExportScope(null);
      setDownloaded(true);
    } catch {
      if (alive.current)
        setExportError(
          "No se pudo descargar el CSV. Conservamos los filtros de esta exportación para que puedas reintentar.",
        );
    } finally {
      link?.remove();
      if (url) {
        const allocated = url;
        urls.current.set(
          allocated,
          setTimeout(() => {
            URL.revokeObjectURL(allocated);
            urls.current.delete(allocated);
          }, 1000),
        );
      }
      writing.current = false;
      if (alive.current) setExporting(false);
    }
  };
  return {
    query,
    snapshot,
    loading,
    readError,
    matching,
    ready,
    choose,
    refresh,
    retry: () => {
      if (!writing.current) void load(queryRef.current);
    },
    summary,
    summaryLoading,
    summaryError,
    retrySummary: () => {
      if (!writing.current) void loadSummary();
    },
    selected,
    detail,
    detailLoading,
    detailError,
    openDetail,
    closeDetail,
    retryDetail: () => {
      if (selectedRef.current) void loadDetail(selectedRef.current);
    },
    exportScope,
    exporting,
    exportError,
    downloaded,
    openExport,
    closeExport,
    exportCsv,
  };
}
