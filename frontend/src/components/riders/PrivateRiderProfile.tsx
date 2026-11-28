'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { UserRound, Bike, FileCheck2, RefreshCw, Save, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { capturePrivateTask } from '@/lib/private-task';
import { toast } from '@/lib/feedback';
import {
  riderSelf,
  SelfProfile,
  ProfileDraft,
  ProfileField,
  VEHICLE_OPTIONS,
  profileDraft,
  changedProfileFields,
  changesVehicle,
} from '@/services/rider-self.service';

type Modal =
  | 'load'
  | 'uncertain'
  | 'confirmed'
  | 'conflict'
  | 'review'
  | 'discard'
  | 'confirm_vehicle'
  | 'vehicle_saved'
  | null;
type Attempt = {
  keys: ProfileField[];
  values: ProfileDraft;
  outcome: 'uncertain' | 'confirmed' | 'conflict';
};
const LABELS: Record<ProfileField, string> = {
  first_name: 'Nombre',
  last_name: 'Apellido',
  phone: 'Teléfono / WhatsApp',
  vehicle_type: 'Tipo de vehículo',
  vehicle_plate: 'Placa',
};
export function PrivateRiderProfile({
  owner,
  scopeGeneration,
}: {
  owner: string;
  scopeGeneration: number;
}) {
  const [data, setData] = useState<SelfProfile | null>(null);
  const [draft, setDraft] = useState<ProfileDraft>({
    first_name: '',
    last_name: '',
    phone: '',
    vehicle_type: '',
    vehicle_plate: '',
  });
  const [busy, setBusy] = useState(false),
    [locked, setLocked] = useState(false),
    [modal, setModal] = useState<Modal>(null);
  const alive = useRef(true),
    pending = useRef(false),
    sent = useRef<Attempt | null>(null),
    profileId = useRef<string>();
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
        const result = await riderSelf.get(owner, profileId.current);
        task.assertCurrent();
        if (!alive.current) return;
        profileId.current = result.id;
        setData(result);
        setLocked(false);
        const attempt = sent.current;
        sent.current = null;
        const next = profileDraft(result);
        if (attempt) {
          const differences = attempt.keys.filter((key) => result[key] !== attempt.values[key]);
          for (const key of differences) next[key] = attempt.values[key];
          setDraft(next);
          if (differences.length) setModal('review');
          else {
            setModal(changesVehicle(attempt.keys) ? 'vehicle_saved' : null);
            toast.success(
              attempt.outcome === 'confirmed'
                ? 'Perfil guardado y verificado'
                : 'Estado actual verificado',
            );
          }
        } else {
          setDraft(next);
          setModal(null);
          if (notice) toast.success('Perfil consultado');
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
    [owner, scopeGeneration],
  );
  useEffect(() => {
    void load();
  }, [load]);
  const changed = data ? changedProfileFields(data, draft) : [];
  const invalidVehicleChange =
    changesVehicle(changed) &&
    (data?.vehicle_ownership_type !== 'PROPIO' ||
      !Object.prototype.hasOwnProperty.call(VEHICLE_OPTIONS, draft.vehicle_type));
  async function save() {
    if (pending.current || locked || !data || !changed.length || invalidVehicleChange) return;
    pending.current = true;
    setBusy(true);
    setModal(null);
    let task: ReturnType<typeof capturePrivateTask> | undefined,
      confirmed = false;
    try {
      task = capturePrivateTask();
      if (task.generation !== scopeGeneration) return;
      sent.current = { keys: [...changed], values: { ...draft }, outcome: 'uncertain' };
      setLocked(true);
      await riderSelf.save(data, draft, owner);
      task.assertCurrent();
      if (!alive.current) return;
      sent.current.outcome = 'confirmed';
      confirmed = true;
    } catch (error) {
      if (alive.current && (!task || task.isCurrent())) {
        const conflict =
          typeof error === 'object' && error !== null && 'status' in error && error.status === 409;
        if (sent.current && conflict) sent.current.outcome = 'conflict';
        setLocked(true);
        setModal(conflict ? 'conflict' : 'uncertain');
      }
    } finally {
      pending.current = false;
      if (alive.current && (!task || task.isCurrent())) setBusy(false);
    }
    if (confirmed && alive.current && task?.isCurrent()) await load();
  }
  const title =
    modal === 'discard'
      ? 'Revisar cambios sin guardar'
      : modal === 'confirm_vehicle'
        ? 'Confirmar cambio de vehículo'
        : modal === 'vehicle_saved'
          ? 'Revisa la documentación del vehículo'
          : modal === 'review'
            ? 'Revisa el perfil actual'
            : modal === 'conflict'
              ? 'El perfil cambió'
              : modal === 'uncertain'
                ? 'No se pudo confirmar el guardado'
                : modal === 'confirmed'
                  ? 'Guardado confirmado; consulta pendiente'
                  : 'No se pudo consultar el perfil';
  const description =
    modal === 'discard'
      ? 'Puedes conservar tu borrador o descartarlo al consultar de nuevo. La consulta no guarda cambios.'
      : modal === 'confirm_vehicle'
        ? 'Cambiar el tipo o la placa requiere revisar los documentos y deshabilita tu disponibilidad. Confirma únicamente si el nuevo vehículo es correcto.'
        : modal === 'vehicle_saved'
          ? 'Los valores actuales del vehículo fueron verificados. Revisa tus documentos y tu disponibilidad antes de volver a operar.'
          : modal === 'review'
            ? 'Los datos actuales difieren de tu solicitud. Se conserva un borrador de las diferencias; revisa los valores antes de volver a guardar.'
            : modal === 'conflict'
              ? 'El servidor rechazó esta revisión. Consulta el perfil y revisa las diferencias; no se reintentará el guardado automáticamente.'
              : modal === 'uncertain'
                ? 'Los cambios podrían haberse aplicado. Consultar el estado no vuelve a enviar el guardado.'
                : modal === 'confirmed'
                  ? 'El servidor confirmó los cambios, pero aún falta consultar el perfil actual. No se volverán a enviar.'
                  : 'No se usarán datos guardados del navegador para sustituir el perfil. Consulta de nuevo para continuar.';
  function field(key: Exclude<ProfileField, 'vehicle_type'>, required = false) {
    return (
      <div className="min-w-0 space-y-2">
        <Label htmlFor={key}>{LABELS[key]}</Label>
        <Input
          id={key}
          required={required}
          maxLength={key === 'first_name' || key === 'last_name' ? 100 : 20}
          value={draft[key]}
          onChange={(e) =>
            setDraft((previous) => ({
              ...previous,
              [key]: key === 'vehicle_plate' ? e.target.value.toUpperCase() : e.target.value,
            }))
          }
          disabled={
            busy ||
            locked ||
            !data ||
            (key === 'vehicle_plate' && data.vehicle_ownership_type === 'EMPRESA')
          }
          placeholder={key === 'phone' ? '+58 412 1234567' : undefined}
        />
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-6">
      <header className="rounded-2xl border border-sky-100 bg-gradient-to-br from-sky-50 via-indigo-50 to-violet-50 p-5 shadow-sm sm:p-6">
        <div className="flex items-start gap-3">
          <span className="rounded-2xl bg-indigo-600 p-3 text-white">
            <UserRound aria-hidden="true" className="h-6 w-6" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-indigo-600">
              Mi cuenta · Repartidor
            </p>
            <h1 className="text-2xl font-semibold text-slate-900">Mi perfil</h1>
          </div>
        </div>
        <p className="mt-4 text-sm text-slate-600">
          Mantén tus datos de contacto y tu vehículo actualizados para operar con información
          verificada.
        </p>
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-white/80 p-3 text-xs text-indigo-900">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 shrink-0" />
          Tus cambios se confirman con una consulta al servidor. Si el perfil cambió, podrás revisar
          las diferencias.
        </p>
      </header>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (busy || locked || !data || !changed.length || invalidVehicleChange) return;
          if (changesVehicle(changed)) setModal('confirm_vehicle');
          else void save();
        }}
        className="space-y-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p role="status" className="text-sm text-slate-600">
            {busy
              ? 'Consultando o guardando…'
              : !data
                ? 'Consulta pendiente'
                : locked
                  ? 'Edición pausada hasta consultar el estado'
                  : invalidVehicleChange
                    ? 'Revisa el tipo de vehículo o adopta la asignación actual antes de guardar'
                    : `${changed.length} ${changed.length === 1 ? 'cambio sin guardar' : 'cambios sin guardar'}`}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() =>
                changed.length && !sent.current ? setModal('discard') : void load(true)
              }
            >
              <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />
              Recargar perfil
            </Button>
            <Button
              type="submit"
              disabled={
                busy ||
                locked ||
                !data ||
                !changed.length ||
                invalidVehicleChange ||
                !draft.first_name.trim() ||
                !draft.last_name.trim()
              }
            >
              <Save aria-hidden="true" className="mr-2 h-4 w-4" />
              Guardar cambios
            </Button>
          </div>
        </div>
        <section
          aria-label="Datos personales"
          className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h2 className="flex items-center gap-2 font-semibold text-slate-800">
            <UserRound aria-hidden="true" className="h-5 w-5 text-indigo-600" />
            Datos personales
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {field('first_name', true)}
            {field('last_name', true)}
          </div>
          <div>
            <p className="text-sm font-medium text-slate-700">Correo electrónico · no editable</p>
            <p className="mt-2 break-all rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
              {data?.email ?? 'Pendiente de consulta'}
            </p>
          </div>
          {field('phone')}
        </section>
        <section
          aria-label="Vehículo"
          className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h2 className="flex items-center gap-2 font-semibold text-slate-800">
            <Bike aria-hidden="true" className="h-5 w-5 text-sky-600" />
            Vehículo{' '}
            {data ? `· ${data.vehicle_ownership_type === 'EMPRESA' ? 'de empresa' : 'propio'}` : ''}
          </h2>
          <p className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-900">
            {data?.vehicle_ownership_type === 'EMPRESA'
              ? 'El vehículo de empresa se muestra según la asignación vigente. Solicita a gerencia los cambios de flota; puedes actualizar tus datos personales aquí.'
              : 'Cambiar el tipo o la placa requiere revisión documental y deshabilita la disponibilidad. Los datos personales se guardan por separado de los campos de vehículo que no cambies.'}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="vehicle_type">Tipo de vehículo</Label>
              <select
                id="vehicle_type"
                value={draft.vehicle_type}
                disabled={busy || locked || !data || data.vehicle_ownership_type === 'EMPRESA'}
                onChange={(e) =>
                  setDraft((previous) => ({ ...previous, vehicle_type: e.target.value }))
                }
                className="h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
              >
                <option value="" disabled>
                  Sin tipo registrado
                </option>
                {draft.vehicle_type &&
                  !Object.prototype.hasOwnProperty.call(VEHICLE_OPTIONS, draft.vehicle_type) && (
                    <option value={draft.vehicle_type}>{draft.vehicle_type} · histórico</option>
                  )}
                {Object.entries(VEHICLE_OPTIONS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {field('vehicle_plate')}
          </div>
        </section>
      </form>
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-indigo-100 bg-indigo-50/70 p-5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-semibold text-indigo-900">
            <FileCheck2 aria-hidden="true" className="h-5 w-5 shrink-0" />
            Documentación
          </h2>
          <p className="mt-2 text-sm text-slate-600">
            Consulta la revisión de identidad, licencia y vehículo.
          </p>
        </div>
        <Link
          href="/rider/profile/documents"
          className="rounded-lg border border-indigo-200 bg-white px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
        >
          Gestionar documentos
        </Link>
      </section>
      <Dialog
        open={!!modal}
        onOpenChange={(open) => {
          if (!open) setModal(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {modal === 'review' && data && (
            <ul className="space-y-2 text-sm text-slate-600">
              {changed.map((key) => (
                <li key={key} className="break-all rounded-lg bg-slate-50 p-3">
                  {LABELS[key]} · actual: {data[key] || 'Sin dato'} · borrador:{' '}
                  {draft[key] || 'Sin dato'}
                </li>
              ))}
            </ul>
          )}
          <DialogFooter className="gap-2">
            {modal === 'confirm_vehicle' ? (
              <>
                <Button variant="outline" onClick={() => setModal(null)}>
                  Revisar borrador
                </Button>
                <Button disabled={busy} onClick={() => void save()}>
                  Confirmar cambio
                </Button>
              </>
            ) : modal === 'discard' ? (
              <>
                <Button variant="outline" onClick={() => setModal(null)}>
                  Conservar borrador
                </Button>
                <Button disabled={busy} onClick={() => void load(true)}>
                  Descartar y consultar
                </Button>
              </>
            ) : modal === 'review' ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (data) setDraft(profileDraft(data));
                    setModal(null);
                  }}
                >
                  Usar valores actuales
                </Button>
                <Button onClick={() => setModal(null)}>Revisar borrador</Button>
              </>
            ) : modal === 'vehicle_saved' ? (
              <>
                <Button variant="outline" onClick={() => setModal(null)}>
                  Cerrar
                </Button>
                <Link
                  href="/rider/profile/documents"
                  className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
                >
                  Ver documentos
                </Link>
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
