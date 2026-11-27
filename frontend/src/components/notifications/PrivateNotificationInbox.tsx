'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, Trash2, Loader2, RefreshCw, Inbox, ShieldCheck } from 'lucide-react';
import { capturePrivateTask } from '@/lib/private-task';
import { toast } from '@/lib/feedback';
import { notificationInboxChanged } from '@/lib/notification-inbox-events';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { NotificationProviderDiagnosticsPanel } from './NotificationProviderDiagnosticsPanel';
import { TerminalDispatchReviewPanel } from './TerminalDispatchReviewPanel';
import { isTerminalExternal } from '@/services/terminal-notifications.service';
import {
  notificationInbox,
  INBOX_CHANNELS,
  INBOX_STATUSES,
  InboxRow,
  InboxPage,
} from '@/services/notification-inbox.service';

type Failure = 'load' | 'uncertain' | 'confirmed';
export function PrivateNotificationInbox() {
  const [data, setData] = useState<InboxPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [stale, setStale] = useState(false);
  const [channel, setChannel] = useState('');
  const [status, setStatus] = useState('');
  const [selected, setSelected] = useState<InboxRow | null>(null);
  const pending = useRef(false);
  const alive = useRef(true);
  const outcome = useRef<Failure | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(async (page: number, confirmed = false, notice = false) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      let result = await notificationInbox.page(page);
      task.assertCurrent();
      const last = Math.max(1, result.pages);
      if (page > last) {
        result = await notificationInbox.page(last);
        task.assertCurrent();
      }
      if (result.page > Math.max(1, result.pages))
        throw new Error('La página cambió durante la consulta');
      if (alive.current) {
        outcome.current = null;
        setData(result);
        setFailure(null);
        setStale(false);
        if (notice) {
          toast.success('Bandeja actualizada');
          notificationInboxChanged(task.generation);
        }
      }
    } catch {
      if (alive.current && (!task || task.isCurrent())) {
        setFailure(confirmed ? 'confirmed' : (outcome.current ?? 'load'));
        setStale(true);
      }
    } finally {
      pending.current = false;
      if (alive.current && (!task || task.isCurrent())) setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load(1);
  }, [load]);
  async function act(row: InboxRow, action: 'read' | 'delete') {
    if (pending.current || stale || isTerminalExternal(row)) return;
    pending.current = true;
    setBusy(true);
    setSelected(null);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    let confirmed = false;
    try {
      task = capturePrivateTask();
      await notificationInbox.act(row, action);
      task.assertCurrent();
      if (!alive.current) return;
      confirmed = true;
      outcome.current = 'confirmed';
      setStale(true);
      toast.success(
        action === 'read' ? 'Notificación marcada como leída' : 'Notificación eliminada',
      );
      setData((previous) =>
        previous
          ? {
              ...previous,
              items:
                action === 'delete'
                  ? previous.items.filter((item) => item.id !== row.id)
                  : previous.items.map((item) =>
                      item.id === row.id ? { ...item, status: 'LEIDO' } : item,
                    ),
            }
          : previous,
      );
    } catch {
      if (alive.current && (!task || task.isCurrent())) {
        outcome.current = 'uncertain';
        setFailure('uncertain');
        setStale(true);
      }
    } finally {
      pending.current = false;
      if (alive.current && (!task || task.isCurrent())) setBusy(false);
    }
    if (confirmed && alive.current && task?.isCurrent()) await load(data?.page ?? 1, true);
  }
  const rows =
    data?.items.filter(
      (row) => (!channel || row.channel === channel) && (!status || row.status === status),
    ) ?? [];
  const disabled = busy || stale;
  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
      <header className="overflow-hidden rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-sky-50 to-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="rounded-2xl bg-indigo-600 p-3 text-white shadow-sm">
              <Bell aria-hidden="true" className="h-6 w-6" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wider text-indigo-600">
                Centro de comunicación
              </p>
              <h1 className="text-2xl font-semibold text-slate-900">Notificaciones</h1>
            </div>
          </div>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void load(data?.page ?? 1, false, true)}
          >
            <RefreshCw
              aria-hidden="true"
              className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`}
            />
            Actualizar bandeja
          </Button>
        </div>
        <p className="mt-4 text-sm text-slate-600">
          Tus avisos y comprobantes, con seguimiento de cada acción.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            ['Total consultado', data?.total],
            ['No leídas en la bandeja interna', data?.unread_count],
            ['Página consultada', data?.page],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-xl border border-white bg-white/80 p-3">
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-1 text-xl font-semibold text-indigo-900">{value ?? '—'}</p>
            </div>
          ))}
        </div>
      </header>
      <NotificationProviderDiagnosticsPanel />
      <TerminalDispatchReviewPanel />
      <section
        aria-label="Bandeja personal"
        className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
      >
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4">
          <h2 className="mr-auto flex items-center gap-2 font-semibold text-slate-800">
            <Inbox aria-hidden="true" className="h-5 w-5 text-indigo-600" />
            Bandeja personal
          </h2>
          <Link
            href="/notifications/preferences"
            className="text-sm font-medium text-indigo-700 hover:underline"
          >
            Preferencias
          </Link>
        </div>
        <div className="space-y-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-slate-600">
              Canal
              <select
                aria-label="Filtrar por canal"
                value={channel}
                onChange={(event) => setChannel(event.target.value)}
                className="mt-1 block w-full min-w-0 rounded-lg border border-slate-200 bg-white p-2.5 text-sm"
              >
                <option value="">Todos los canales</option>
                {INBOX_CHANNELS.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-600">
              Estado
              <select
                aria-label="Filtrar por estado"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="mt-1 block w-full min-w-0 rounded-lg border border-slate-200 bg-white p-2.5 text-sm"
              >
                <option value="">Todos los estados</option>
                {INBOX_STATUSES.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-xs text-slate-500">
            Los filtros se aplican a la página consultada. El contador de no leídas corresponde solo
            a avisos internos.
          </p>
          {stale && (
            <p
              role="status"
              className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
            >
              La bandeja necesita una consulta actualizada. Las acciones están pausadas hasta
              recuperar su estado.
            </p>
          )}
          {busy && (
            <p role="status" className="flex items-center gap-2 text-sm text-indigo-700">
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
              Consultando o procesando la acción…
            </p>
          )}
          {!busy && data && !rows.length && (
            <p className="rounded-xl bg-slate-50 p-6 text-center text-sm text-slate-500">
              {data.total === 0
                ? 'Tu bandeja está vacía.'
                : 'No hay avisos que coincidan en esta página.'}
            </p>
          )}
          {rows.map((row) => (
            <article
              key={row.id}
              aria-label={row.title || 'Notificación'}
              className={`min-w-0 rounded-xl border p-4 ${row.status === 'LEIDO' ? 'border-slate-200 bg-slate-50' : 'border-indigo-100 bg-white'}`}
            >
              <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h3 className="break-words font-medium text-slate-900">
                    {row.title || row.template_code || 'Notificación'}
                  </h3>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant="secondary">{row.channel}</Badge>
                    <Badge variant={row.status === 'FALLIDO' ? 'destructive' : 'outline'}>
                      {row.status}
                    </Badge>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap break-words text-sm text-slate-600">
                    {row.body}
                  </p>
                  {row.created_at && (
                    <p className="mt-2 text-xs text-slate-500">
                      {new Intl.DateTimeFormat('es-VE', {
                        timeZone: 'America/Caracas',
                        dateStyle: 'short',
                        timeStyle: 'short',
                      }).format(new Date(row.created_at))}{' '}
                      (Caracas)
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap items-start gap-2 sm:shrink-0 sm:flex-col">
                  {isTerminalExternal(row) ? (
                    <span className="flex items-center gap-1 text-xs text-slate-500">
                      <ShieldCheck aria-hidden="true" className="h-4 w-4" />
                      Seguimiento externo
                    </span>
                  ) : (
                    <>
                      {row.status !== 'LEIDO' && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={disabled}
                          aria-label={`Marcar leído: ${row.title || 'Notificación'}`}
                          onClick={() => void act(row, 'read')}
                        >
                          <CheckCheck aria-hidden="true" className="mr-1 h-4 w-4" />
                          Marcar leído
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={disabled}
                        aria-label={`Eliminar: ${row.title || 'Notificación'}`}
                        onClick={() => setSelected(row)}
                      >
                        <Trash2 aria-hidden="true" className="mr-1 h-4 w-4 text-rose-600" />
                        Eliminar
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </article>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 text-sm text-slate-600">
            <p>
              {data
                ? `Página ${data.page} de ${Math.max(1, data.pages)} · ${data.total} avisos en la última consulta`
                : 'Consulta pendiente'}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!data || disabled || data.page <= 1}
                onClick={() => void load((data?.page ?? 1) - 1)}
              >
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!data || disabled || data.page >= data.pages}
                onClick={() => void load((data?.page ?? 1) + 1)}
              >
                Siguiente
              </Button>
            </div>
          </div>
        </div>
      </section>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Eliminar notificación</DialogTitle>
            <DialogDescription>
              Se eliminará este aviso de tu bandeja personal. Esta acción no cambia la orden ni sus
              movimientos.
            </DialogDescription>
          </DialogHeader>
          <p className="break-words rounded-xl bg-slate-50 p-3 text-sm text-slate-700">
            {selected?.title || 'Notificación seleccionada'}
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setSelected(null)}>
              Volver
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => {
                if (selected) void act(selected, 'delete');
              }}
            >
              Confirmar eliminación
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!failure}
        onOpenChange={(open) => {
          if (!open) setFailure(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {failure === 'uncertain'
                ? 'No se pudo confirmar la acción'
                : failure === 'confirmed'
                  ? 'Acción confirmada; consulta pendiente'
                  : 'No se pudo cargar la bandeja'}
            </DialogTitle>
            <DialogDescription>
              {failure === 'uncertain'
                ? 'La acción podría haberse aplicado. Consulta el estado antes de decidir si necesitas otra acción.'
                : failure === 'confirmed'
                  ? 'La acción fue confirmada, pero no se pudo actualizar el listado.'
                  : data
                    ? 'Se conserva la última página consultada; sus datos pueden haber cambiado.'
                    : 'La consulta falló. Esto no significa que tu bandeja esté vacía.'}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-slate-600">
            La recuperación consulta la bandeja y no repite acciones de lectura o eliminación.
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setFailure(null)}>
              Volver
            </Button>
            <Button disabled={busy} onClick={() => void load(data?.page ?? 1, false, true)}>
              Consultar de nuevo
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
