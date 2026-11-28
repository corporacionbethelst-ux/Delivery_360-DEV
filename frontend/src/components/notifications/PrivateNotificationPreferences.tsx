'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { BellRing, RefreshCw, Save, ShieldCheck, Loader2, Undo2 } from 'lucide-react';
import { capturePrivateTask } from '@/lib/private-task';
import { toast } from '@/lib/feedback';
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
import {
  notificationPreferences,
  editablePreferenceChannels,
  preferenceKey,
  preferenceValue,
  preferenceEvents,
  EVENT_LABELS,
  CHANNEL_LABELS,
  EXTERNAL_CHANNELS,
  Preference,
  PreferenceSnapshot,
} from '@/services/notification-preferences.service';

type Modal =
  | 'load'
  | 'uncertain'
  | 'confirmed'
  | 'review'
  | 'discard_reload'
  | 'discard_draft'
  | null;
type Sent = { rows: Preference[]; outcome: 'uncertain' | 'confirmed' };
export function PrivateNotificationPreferences({
  scopeGeneration,
  role,
}: {
  scopeGeneration: number;
  role: string;
}) {
  const [data, setData] = useState<PreferenceSnapshot | null>(null);
  const [draft, setDraft] = useState<Preference[]>([]);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [modal, setModal] = useState<Modal>(null);
  const alive = useRef(true),
    pending = useRef(false),
    sent = useRef<Sent | null>(null);
  const allowed = editablePreferenceChannels(role);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(
    async (notice = false) => {
      if (pending.current) return;
      pending.current = true;
      setBusy(true);
      let task: ReturnType<typeof capturePrivateTask> | undefined;
      try {
        task = capturePrivateTask();
        if (task.generation !== scopeGeneration) return;
        const result = await notificationPreferences.snapshot();
        task.assertCurrent();
        if (!alive.current) return;
        setData(result);
        setLocked(false);
        const previous = sent.current;
        sent.current = null;
        if (previous) {
          const differences = previous.rows.filter(
            (row) => preferenceValue(result, row.event_code, row.channel) !== row.enabled,
          );
          setDraft(differences);
          if (differences.length) setModal('review');
          else {
            setModal(null);
            toast.success(
              previous.outcome === 'confirmed'
                ? 'Preferencias guardadas y verificadas'
                : 'Estado actual verificado',
            );
          }
        } else {
          setDraft([]);
          setModal(null);
          if (notice) toast.success('Preferencias consultadas');
        }
      } catch {
        if (alive.current && (!task || task.isCurrent())) {
          setLocked(true);
          setModal(sent.current?.outcome ?? 'load');
        }
      } finally {
        pending.current = false;
        if (alive.current && (!task || task.isCurrent())) setBusy(false);
      }
    },
    [scopeGeneration],
  );
  useEffect(() => {
    void load();
  }, [load]);
  function toggle(event_code: string, channel: Preference['channel'], enabled: boolean) {
    if (!data || busy || locked || !allowed.includes(channel)) return;
    const row = { event_code, channel, enabled },
      key = preferenceKey(row);
    setDraft((previous) => [
      ...previous.filter((item) => preferenceKey(item) !== key),
      ...(preferenceValue(data, event_code, channel) === enabled ? [] : [row]),
    ]);
  }
  async function save() {
    if (pending.current || locked || !data || !draft.length) return;
    pending.current = true;
    setBusy(true);
    let task: ReturnType<typeof capturePrivateTask> | undefined,
      confirmed = false;
    try {
      task = capturePrivateTask();
      if (task.generation !== scopeGeneration) return;
      const rows = draft.map((row) => ({ ...row }));
      sent.current = { rows, outcome: 'uncertain' };
      setLocked(true);
      await notificationPreferences.save(rows, role);
      task.assertCurrent();
      if (!alive.current) return;
      sent.current.outcome = 'confirmed';
      confirmed = true;
    } catch {
      if (alive.current && (!task || task.isCurrent())) {
        setLocked(true);
        setModal('uncertain');
      }
    } finally {
      pending.current = false;
      if (alive.current && (!task || task.isCurrent())) setBusy(false);
    }
    if (confirmed && alive.current && task?.isCurrent()) await load();
  }
  function refresh() {
    if (draft.length && !sent.current) setModal('discard_reload');
    else void load(true);
  }
  const isDiscard = modal === 'discard_reload' || modal === 'discard_draft';
  const title = isDiscard
    ? 'Revisar cambios sin guardar'
    : modal === 'review'
      ? 'Revisa las preferencias actuales'
      : modal === 'uncertain'
        ? 'No se pudo confirmar el guardado'
        : modal === 'confirmed'
          ? 'Guardado confirmado; consulta pendiente'
          : 'No se pudieron consultar las preferencias';
  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
      <header className="rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50 via-indigo-50 to-sky-50 p-5 shadow-sm sm:p-6">
        <div className="flex items-start gap-3">
          <span className="rounded-2xl bg-violet-600 p-3 text-white shadow-sm">
            <BellRing aria-hidden="true" className="h-6 w-6" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wider text-violet-600">
              Centro de comunicación
            </p>
            <h1 className="break-words text-2xl font-semibold text-slate-900">
              Preferencias de notificación
            </h1>
          </div>
        </div>
        <p className="mt-4 text-sm text-slate-600">
          Elige qué avisos externos permites para tu cuenta. Permitir un canal no garantiza su
          envío: también dependen de la configuración y las reglas del evento.
        </p>
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-white/80 p-3 text-xs text-indigo-900">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 shrink-0" />
          Los comprobantes internos se conservan independientemente de estas opciones. No se
          reenvían avisos anteriores.
        </p>
        <Link
          href="/notifications"
          className="mt-4 inline-block text-sm font-medium text-indigo-700 hover:underline"
        >
          Volver a la bandeja
        </Link>
      </header>
      <div
        aria-label="Acciones de preferencias"
        className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      >
        <div className="text-sm text-slate-600">
          {busy ? (
            <span className="flex items-center gap-2">
              <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
              Consultando o guardando…
            </span>
          ) : !data ? (
            'Consulta pendiente'
          ) : (
            `${draft.length} ${draft.length === 1 ? 'cambio sin guardar' : 'cambios sin guardar'}`
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={refresh}>
            <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />
            Consultar estado
          </Button>
          <Button
            variant="ghost"
            disabled={busy || locked || !draft.length}
            onClick={() => setModal('discard_draft')}
          >
            <Undo2 aria-hidden="true" className="mr-2 h-4 w-4" />
            Descartar borrador
          </Button>
          <Button disabled={busy || locked || !data || !draft.length} onClick={() => void save()}>
            <Save aria-hidden="true" className="mr-2 h-4 w-4" />
            Guardar cambios
          </Button>
        </div>
      </div>
      {locked && (
        <p
          role="status"
          className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          Las opciones están pausadas hasta consultar su estado. Se conserva la última consulta y tu
          borrador.
        </p>
      )}
      {data && (
        <section aria-label="Preferencias por evento" className="space-y-4">
          {preferenceEvents(data).map((event) => {
            const template = data.templates.find((row) => row.code === event);
            return (
              <article
                key={event}
                aria-label={EVENT_LABELS.get(event) ?? event}
                className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="break-words font-semibold text-slate-800">
                      {EVENT_LABELS.get(event) ?? event}
                    </h2>
                    <p className="mt-1 break-all text-xs text-slate-500">{event}</p>
                  </div>
                  <Badge variant="outline">
                    {!template
                      ? 'Sin plantilla consultada'
                      : template.is_active
                        ? 'Plantilla consultada'
                        : 'Plantilla pausada'}
                  </Badge>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  {EXTERNAL_CHANNELS.map((channel) => {
                    const saved = data.preferences.find(
                      (row) => row.event_code === event && row.channel === channel,
                    );
                    const change = draft.find(
                      (row) => row.event_code === event && row.channel === channel,
                    );
                    return (
                      <label
                        key={channel}
                        className={`flex min-w-0 items-start gap-3 rounded-xl border p-3 ${change ? 'border-violet-300 bg-violet-50' : 'border-slate-200 bg-slate-50'}`}
                      >
                        <input
                          type="checkbox"
                          aria-label={`${EVENT_LABELS.get(event) ?? event}: ${CHANNEL_LABELS[channel]}`}
                          className="mt-1 h-4 w-4 shrink-0 accent-violet-600"
                          disabled={busy || locked || !allowed.includes(channel)}
                          checked={change?.enabled ?? saved?.enabled ?? true}
                          onChange={(e) => toggle(event, channel, e.target.checked)}
                        />
                        <span className="min-w-0 text-sm font-medium text-slate-700">
                          {CHANNEL_LABELS[channel]}
                          <span className="mt-1 block text-xs font-normal text-slate-500">
                            {!allowed.includes(channel)
                              ? 'No editable para tu rol'
                              : change
                                ? `Cambio pendiente · actual: ${preferenceValue(data, event, channel) ? 'permitido' : 'bloqueado'}`
                                : saved
                                  ? saved.enabled
                                    ? 'Permiso guardado'
                                    : 'Bloqueo guardado'
                                  : 'Permitido por defecto'}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </article>
            );
          })}
        </section>
      )}
      <Dialog
        open={!!modal}
        onOpenChange={(open) => {
          if (!open) setModal(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {isDiscard
                ? 'Tu borrador aún no se ha enviado. Puedes conservarlo o descartarlo de forma explícita.'
                : modal === 'review'
                  ? 'La consulta no coincide con todos los cambios enviados. Se conserva un borrador de las diferencias para que lo revises.'
                  : modal === 'uncertain'
                    ? 'Los cambios podrían haberse aplicado. Consulta sus valores actuales antes de decidir otra acción.'
                    : modal === 'confirmed'
                      ? 'El servidor confirmó el guardado, pero aún no se pudieron consultar los valores actuales.'
                      : 'La consulta no se completó. Esto no significa que no tengas preferencias guardadas.'}
            </DialogDescription>
          </DialogHeader>
          {modal === 'review' && (
            <ul className="space-y-2 text-sm text-slate-600">
              {draft.map((row) => (
                <li key={preferenceKey(row)} className="break-words rounded-lg bg-slate-50 p-3">
                  {EVENT_LABELS.get(row.event_code) ?? row.event_code} ·{' '}
                  {CHANNEL_LABELS[row.channel]}: borrador {row.enabled ? 'permitido' : 'bloqueado'};
                  actual{' '}
                  {data && preferenceValue(data, row.event_code, row.channel)
                    ? 'permitido'
                    : 'bloqueado'}
                  .
                </li>
              ))}
            </ul>
          )}
          {!isDiscard && modal !== 'review' && (
            <p className="text-sm text-slate-600">
              Consultar el estado no vuelve a enviar los cambios.
            </p>
          )}
          <DialogFooter className="gap-2">
            {isDiscard ? (
              <>
                <Button variant="outline" onClick={() => setModal(null)}>
                  Conservar borrador
                </Button>
                <Button
                  onClick={() => {
                    if (modal === 'discard_reload') void load(true);
                    else {
                      setDraft([]);
                      setModal(null);
                    }
                  }}
                >
                  Descartar{modal === 'discard_reload' ? ' y consultar' : ' borrador'}
                </Button>
              </>
            ) : modal === 'review' ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => {
                    setDraft([]);
                    setModal(null);
                  }}
                >
                  Usar valores actuales
                </Button>
                <Button onClick={() => setModal(null)}>Revisar borrador</Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => setModal(null)}>
                  Volver
                </Button>
                <Button disabled={busy} onClick={() => void load(true)}>
                  Consultar de nuevo
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
