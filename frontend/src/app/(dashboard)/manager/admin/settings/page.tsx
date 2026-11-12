"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BadgeDollarSign,
  Headphones,
  RefreshCw,
  Save,
  Settings,
  Shield,
  Wallet,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationMetric,
  OperationNotice,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { BonusSimulator } from "@/components/admin/BonusSimulator";
import { useAuthStore } from "@/stores/authStore";
import {
  settingsService,
  type PlatformSettings,
  type PlatformSettingsUpdate,
} from "@/services/settings.service";
import {
  SETTING_LABELS,
  SETTING_NUMBERS,
  sameSetting,
  settingsChanges,
  settingsDraft,
  settingsTime,
  settingsValue,
  type SettingsDraft,
  type SettingsKey,
} from "@/lib/platform-settings";

type Snapshot = { data: PlatformSettings; at: Date; version: number };
type Confirmation = { base: PlatformSettings; patch: PlatformSettingsUpdate };
export default function SettingsPage() {
  return (
    <ManagerPageBoundary scope="platform-settings">
      <SettingsForm />
    </ManagerPageBoundary>
  );
}
function SettingsForm() {
  const { user } = useAuthStore(),
    administrator = user?.role === "SUPERADMIN";
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [draft, setDraft] = useState<SettingsDraft | null>(null),
    [loading, setLoading] = useState(true),
    [saving, setSaving] = useState(false),
    [readError, setReadError] = useState<string | null>(null),
    [error, setError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null),
    [requiresReload, setRequiresReload] = useState(false),
    [confirmation, setConfirmation] = useState<Confirmation | null>(null),
    [reloadDialog, setReloadDialog] = useState(false);
  const alive = useRef(false),
    sequence = useRef(0),
    version = useRef(0),
    writing = useRef(false),
    confirmed = useRef<Confirmation | null>(null);
  const load = useCallback(async () => {
    if (writing.current) return;
    const ticket = ++sequence.current;
    confirmed.current = null;
    setConfirmation(null);
    setReloadDialog(false);
    setLoading(true);
    setReadError(null);
    setSuccess(null);
    setError(null);
    try {
      const data = await settingsService.getSettings();
      if (!alive.current || ticket !== sequence.current) return;
      setSnapshot({ data, at: new Date(), version: ++version.current });
      setDraft(settingsDraft(data));
      setRequiresReload(false);
    } catch {
      if (alive.current && ticket === sequence.current)
        setReadError(
          "No se pudo confirmar la configuración. Se conserva la última consulta cargada, si existe.",
        );
    } finally {
      if (alive.current && ticket === sequence.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const requests = sequence;
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      requests.current++;
    };
  }, [load]);
  const dirty =
    !!snapshot && !!draft && !sameSetting(draft, settingsDraft(snapshot.data));
  const editable =
    administrator &&
    !!snapshot &&
    !!draft &&
    !loading &&
    !saving &&
    !readError &&
    !requiresReload &&
    !confirmation;
  const update = <K extends keyof SettingsDraft>(
    key: K,
    value: SettingsDraft[K],
  ) => {
    if (!editable) return;
    setDraft((previous) => previous && { ...previous, [key]: value });
    setError(null);
    setSuccess(null);
  };
  const review = (event: React.FormEvent) => {
    event.preventDefault();
    if (!editable || !snapshot || !draft || writing.current) return;
    setError(null);
    setSuccess(null);
    try {
      const patch = settingsChanges(snapshot.data, draft);
      if (!Object.keys(patch).length) {
        setDraft(settingsDraft(snapshot.data));
        setSuccess(
          "Los valores introducidos coinciden con la configuración cargada.",
        );
        return;
      }
      const captured = { base: snapshot.data, patch };
      confirmed.current = captured;
      setConfirmation(captured);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Revisa los datos de configuración.",
      );
    }
  };
  const closeConfirmation = () => {
    if (!writing.current) {
      confirmed.current = null;
      setConfirmation(null);
    }
  };
  const save = async () => {
    const captured = confirmed.current;
    if (
      !captured ||
      !administrator ||
      requiresReload ||
      writing.current ||
      !alive.current
    )
      return;
    writing.current = true;
    setSaving(true);
    setError(null);
    try {
      const fresh = await settingsService.getSettings();
      if (!alive.current || confirmed.current !== captured) return;
      const keys = Object.keys(captured.patch) as SettingsKey[];
      if (keys.some((key) => !sameSetting(fresh[key], captured.base[key]))) {
        setRequiresReload(true);
        setError(
          "Alguno de los campos que vas a guardar cambió desde la lectura. Recarga y revisa la configuración antes de continuar.",
        );
        return;
      }
      const updated = await settingsService.updateSettings(captured.patch);
      if (!alive.current || confirmed.current !== captured) return;
      if (keys.some((key) => !sameSetting(updated[key], captured.patch[key]))) {
        setRequiresReload(true);
        setError(
          "La respuesta no confirmó los valores enviados. Recarga y revisa la configuración antes de repetir.",
        );
        return;
      }
      confirmed.current = null;
      setConfirmation(null);
      setSnapshot({
        data: updated,
        at: new Date(),
        version: ++version.current,
      });
      setDraft(settingsDraft(updated));
      setSuccess("Configuración guardada y confirmada correctamente.");
    } catch {
      if (alive.current) {
        setRequiresReload(true);
        setError(
          "No se pudo confirmar el guardado. Recarga y revisa el estado de la configuración antes de repetir la operación.",
        );
      }
    } finally {
      writing.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const reload = () => {
    if (writing.current) return;
    if (dirty) setReloadDialog(true);
    else void load();
  };
  const field = (key: (typeof SETTING_NUMBERS)[number]) => (
    <label key={key} className="space-y-2 text-sm font-medium">
      {SETTING_LABELS[key]}
      <input
        className={operationStyles.field}
        inputMode="decimal"
        value={draft![key]}
        onChange={(event) => update(key, event.target.value)}
        placeholder="Sin configurar"
      />
      <span className="block text-xs font-normal text-slate-600">
        Guardado: {settingsValue(snapshot!.data[key])}
      </span>
    </label>
  );
  return (
    <main className={`${operationStyles.page} max-w-5xl`}>
      <OperationsHeader
        icon={Settings}
        eyebrow="Administración · Plataforma"
        title="Configuración de la Plataforma"
        description="Revisa los parámetros guardados y prepara cambios de tarifas, bonos y operación."
        actions={
          <button
            className={operationStyles.button}
            disabled={loading || saving || !!confirmation}
            onClick={reload}
          >
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
            Recargar configuración
          </button>
        }
      />
      {!administrator && (
        <OperationNotice>
          Tu acceso permite consultar la configuración y simular bonos. El
          guardado está reservado a superadministración.
        </OperationNotice>
      )}
      {loading && (
        <OperationNotice role="status">
          Consultando configuración…
        </OperationNotice>
      )}
      {readError && (
        <OperationNotice role="alert" tone="warning">
          <p>{readError}</p>
          <button
            className={operationStyles.button}
            disabled={loading || saving}
            onClick={reload}
          >
            Reintentar configuración
          </button>
        </OperationNotice>
      )}
      {error && !confirmation && (
        <OperationNotice role="alert" tone="error">
          {error}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice role="status" tone="success">
          {success}
        </OperationNotice>
      )}
      {snapshot && draft && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <OperationMetric
              icon={Shield}
              label="Mantenimiento guardado"
              value={snapshot.data.maintenance_mode ? "Activo" : "Inactivo"}
              tone={snapshot.data.maintenance_mode ? "amber" : "emerald"}
            />
            <OperationMetric
              icon={Headphones}
              label="Zonas guardadas"
              value={snapshot.data.active_zones.length}
              tone="violet"
            />
            <OperationMetric
              icon={Wallet}
              label="Importes sin configurar"
              value={
                SETTING_NUMBERS.filter((key) => snapshot.data[key] === null)
                  .length
              }
            />
          </div>
          <p className="text-xs text-slate-600">
            Consulta confirmada: {settingsTime(snapshot.at)}. Actualización
            informada: {settingsTime(snapshot.data.updated_at)} ·
            America/Caracas.
          </p>
          <form onSubmit={review} className="space-y-5" noValidate>
            <fieldset disabled={!editable} className="min-w-0 space-y-5">
              <section
                className={`${operationStyles.panel} space-y-5 border-blue-100 p-5`}
              >
                <SectionHeading
                  icon={Wallet}
                  title="Tarifas y comisión"
                  description="Cero es un valor válido. Los importes ausentes permanecen sin configurar; no se completan automáticamente."
                />
                <div className="grid gap-4 md:grid-cols-3">
                  {SETTING_NUMBERS.slice(0, 3).map(field)}
                </div>
              </section>
              <section
                className={`${operationStyles.panel} space-y-5 border-violet-200 p-5`}
              >
                <SectionHeading
                  icon={BadgeDollarSign}
                  title="Bonos del repartidor"
                  tone="violet"
                  description="Importes guardados para entregas e intentos fallidos. Se conserva la precisión introducida."
                />
                <div className="grid gap-4 md:grid-cols-2">
                  {SETTING_NUMBERS.slice(3).map(field)}
                </div>
              </section>
              <section
                className={`${operationStyles.panel} space-y-5 border-blue-100 p-5`}
              >
                <SectionHeading icon={Headphones} title="Operación y soporte" />
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2 text-sm font-medium">
                    Zonas activas
                    <textarea
                      className={operationStyles.field}
                      rows={4}
                      value={draft.active_zones}
                      onChange={(event) =>
                        update("active_zones", event.target.value)
                      }
                    />
                    <span className="block text-xs font-normal text-slate-600">
                      Una zona por línea. Las comas dentro del nombre se
                      conservan.
                    </span>
                  </label>
                  <label className="space-y-2 text-sm font-medium">
                    Email de soporte
                    <input
                      className={operationStyles.field}
                      type="email"
                      value={draft.support_email}
                      onChange={(event) =>
                        update("support_email", event.target.value)
                      }
                      placeholder="Sin configurar"
                    />
                    <span className="block text-xs font-normal text-slate-600">
                      Guardado: {settingsValue(snapshot.data.support_email)}
                    </span>
                  </label>
                </div>
              </section>
              <section
                className={`${operationStyles.panel} space-y-4 border-amber-200 p-5`}
              >
                <SectionHeading
                  icon={Shield}
                  title="Estado del sistema"
                  tone="amber"
                />
                <div className="flex items-center justify-between gap-4">
                  <label
                    htmlFor="platform-maintenance"
                    className="text-sm font-medium"
                  >
                    Modo mantenimiento
                  </label>
                  <Switch
                    id="platform-maintenance"
                    checked={draft.maintenance_mode}
                    onCheckedChange={(value) =>
                      update("maintenance_mode", value)
                    }
                  />
                </div>
              </section>
            </fieldset>
            <div
              className={`${operationStyles.panel} flex flex-wrap items-center justify-between gap-3 p-4`}
            >
              <p className="text-sm text-slate-600">
                {dirty ? "Hay cambios sin guardar." : "Sin cambios pendientes."}
              </p>
              {administrator && (
                <button
                  type="submit"
                  className={operationStyles.primaryButton}
                  disabled={!editable || !dirty}
                >
                  <Save aria-hidden="true" className="h-4 w-4" />
                  Revisar cambios
                </button>
              )}
            </div>
          </form>
          <BonusSimulator
            key={snapshot.version}
            currentBase={snapshot.data.rider_delivery_bonus}
            disabled={loading || saving || !!readError || requiresReload}
          />
        </>
      )}
      <Dialog
        open={!!confirmation}
        onOpenChange={(open) => {
          if (!open) closeConfirmation();
        }}
      >
        <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto rounded-2xl border-amber-200">
          <DialogHeader>
            <DialogTitle>Confirmar cambios de configuración</DialogTitle>
            <DialogDescription>
              Se actualizarán únicamente los campos listados. Revisa los valores
              guardados y los propuestos antes de confirmar.
            </DialogDescription>
          </DialogHeader>
          <dl className="space-y-3">
            {confirmation &&
              (Object.keys(confirmation.patch) as SettingsKey[]).map((key) => (
                <div
                  key={key}
                  className="space-y-2 rounded-xl border border-slate-200 p-3"
                >
                  <dt className="font-semibold">{SETTING_LABELS[key]}</dt>
                  <dd className="break-words text-sm text-slate-600">
                    Guardado: {settingsValue(confirmation.base[key])}
                  </dd>
                  <dd className="break-words text-sm font-medium text-blue-800">
                    Propuesto: {settingsValue(confirmation.patch[key])}
                  </dd>
                </div>
              ))}
          </dl>
          {error && (
            <OperationNotice role="alert" tone="warning">
              {error}
            </OperationNotice>
          )}
          <DialogFooter>
            {requiresReload ? (
              <button
                className={operationStyles.primaryButton}
                onClick={() => void load()}
              >
                Recargar y revisar
              </button>
            ) : (
              <button
                className={operationStyles.primaryButton}
                disabled={saving}
                onClick={() => void save()}
              >
                {saving ? "Guardando…" : "Confirmar guardado"}
              </button>
            )}
            <button
              className={operationStyles.button}
              disabled={saving}
              onClick={closeConfirmation}
            >
              Cancelar
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={reloadDialog} onOpenChange={setReloadDialog}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl">
          <DialogHeader>
            <DialogTitle>Recargar configuración</DialogTitle>
            <DialogDescription>
              La nueva consulta reemplazará los cambios sin guardar del
              formulario.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              className={operationStyles.primaryButton}
              onClick={() => void load()}
            >
              Descartar borrador y recargar
            </button>
            <button
              className={operationStyles.button}
              onClick={() => setReloadDialog(false)}
            >
              Conservar borrador
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
