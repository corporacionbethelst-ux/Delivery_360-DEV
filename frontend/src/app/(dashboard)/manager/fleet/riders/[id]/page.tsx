"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  Award,
  Bike,
  FileText,
  MapPin,
  RefreshCw,
  UserRound,
  Wallet,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationNotice,
  OperationPill,
  SectionHeading,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthStore } from "@/stores/authStore";
import { riderService } from "@/services/rider.service";
import type { Rider } from "@/types/user";
import {
  canManageRiders,
  riderCoordinates,
  riderDate,
  riderName,
  riderNumber,
  riderReadRoles,
  riderVehicle,
} from "@/lib/rider-display";

const statuses: Record<string, { label: string; tone: OperationTone }> = {
  ACTIVO: { label: "Activo", tone: "emerald" },
  OCUPADO: { label: "Ocupado", tone: "blue" },
  PENDIENTE: { label: "Pendiente", tone: "amber" },
  SUSPENDIDO: { label: "Suspendido", tone: "rose" },
  INACTIVO: { label: "Inactivo", tone: "slate" },
};
type StatusAction = {
  id: string;
  name: string;
  status: "ACTIVO" | "SUSPENDIDO";
};
export default function ManagerRiderDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  return (
    <ManagerPageBoundary scope={`rider-profile:${id}`} roles={riderReadRoles}>
      <Profile id={id} />
    </ManagerPageBoundary>
  );
}
function Profile({ id }: { id: string }) {
  const { user } = useAuthStore();
  const canManage = canManageRiders(user?.role);
  const [rider, setRider] = useState<Rider | null>(null);
  const [loading, setLoading] = useState(false),
    [pending, setPending] = useState(false);
  const [readError, setReadError] = useState<string | null>(null),
    [actionError, setActionError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<StatusAction | null>(null);
  const alive = useRef(false),
    sequence = useRef(0),
    writing = useRef(false);
  const load = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    setReadError(null);
    try {
      if (!id) throw new Error("ID de repartidor no válido.");
      const data = await riderService.getById(id);
      if (!data || data.id !== id)
        throw new Error(
          "La respuesta no corresponde al repartidor solicitado.",
        );
      if (alive.current && ticket === sequence.current) setRider(data);
    } catch (error) {
      if (alive.current && ticket === sequence.current)
        setReadError(
          error instanceof Error
            ? error.message
            : "No se pudo cargar el perfil.",
        );
    } finally {
      if (alive.current && ticket === sequence.current) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    const requests = sequence;
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      requests.current++;
    };
  }, [load]);
  const changeStatus = async () => {
    const snapshot = confirmation;
    if (
      !snapshot ||
      !canManage ||
      writing.current ||
      loading ||
      readError ||
      !alive.current
    )
      return;
    writing.current = true;
    setPending(true);
    setActionError(null);
    setSuccess(null);
    try {
      // The endpoint returns an acknowledgement, not a complete profile.
      await riderService.updateStatus(snapshot.id, snapshot.status);
      if (!alive.current) return;
      setConfirmation(null);
      setSuccess(
        "Estado actualizado. La ficha se consulta nuevamente para confirmar los datos.",
      );
      await load();
    } catch (error) {
      if (!alive.current) return;
      setActionError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar el estado.",
      );
      // A failed activation may restrict a rider whose documents are not ready.
      if (
        typeof error === "object" &&
        error !== null &&
        "status" in error &&
        error.status === 409
      ) {
        setConfirmation(null);
        await load();
      }
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const state = statuses[rider?.status ?? ""],
    vehicle = rider ? riderVehicle(rider) : null,
    coordinates = rider ? riderCoordinates(rider) : null;
  const canSuspend = rider?.status === "ACTIVO" || rider?.status === "OCUPADO";
  const canActivate = ["PENDIENTE", "SUSPENDIDO", "INACTIVO"].includes(
    rider?.status ?? "",
  );
  const disabled = loading || pending || !!readError;
  const metrics = rider as
    | (Rider & { total_deliveries?: number; rating?: number })
    | null;
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={UserRound}
        eyebrow="Flota · Perfil"
        title="Perfil del Repartidor"
        description={
          <span className="break-all">
            ID repartidor: {id || "No informado"}
          </span>
        }
        actions={
          <>
            <Link
              className={operationStyles.button}
              href="/manager/fleet/riders"
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver al listado
            </Link>
            <button
              className={operationStyles.button}
              onClick={() => void load()}
              disabled={loading || pending}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar perfil
            </button>
            {rider && (
              <Link
                className={operationStyles.primaryButton}
                href={`/manager/fleet/riders/${encodeURIComponent(rider.id)}/documents`}
              >
                <FileText aria-hidden="true" className="h-4 w-4" />
                Gestionar Documentos
              </Link>
            )}
          </>
        }
      />
      {loading && (
        <OperationNotice role="status">
          Consultando el perfil del repartidor…
        </OperationNotice>
      )}
      {readError && (
        <OperationNotice tone="warning" role="alert">
          <p>{readError}</p>
          <p>
            Los datos anteriores, si existen, corresponden a la última consulta
            confirmada.
          </p>
          <button
            className={operationStyles.button}
            disabled={loading || pending}
            onClick={() => void load()}
          >
            Reintentar perfil
          </button>
        </OperationNotice>
      )}
      {actionError && (
        <OperationNotice tone="error" role="alert">
          {actionError}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice tone="success" role="status">
          {success}
        </OperationNotice>
      )}
      {rider && (
        <>
          <section
            className={`${operationStyles.panel} overflow-hidden`}
            aria-label="Identidad del repartidor"
            aria-busy={loading}
          >
            <div className="flex flex-col gap-4 border-b border-blue-100 bg-gradient-to-br from-blue-50 via-white to-cyan-50 p-5 sm:flex-row sm:justify-between">
              <div className="min-w-0 space-y-3">
                <h2 className="break-words text-2xl font-bold">
                  {riderName(rider)}
                </h2>
                <p className="break-all text-sm text-slate-600">
                  {rider.email || "Email no informado"}
                </p>
                <p className="break-all text-sm text-slate-600">
                  {rider.phone || "Teléfono no informado"}
                </p>
                <div className="flex flex-wrap gap-2">
                  <OperationPill tone={state?.tone}>
                    {state?.label || rider.status || "Estado no informado"}
                  </OperationPill>
                  <OperationPill
                    tone={rider.is_online === true ? "emerald" : "slate"}
                  >
                    {rider.is_online === true
                      ? "En línea"
                      : rider.is_online === false
                        ? "Desconectado"
                        : "Disponibilidad no informada"}
                  </OperationPill>
                </div>
              </div>
              <div className="min-w-0 space-y-2 text-sm text-slate-600">
                <p className="break-all font-mono">ID: {rider.id}</p>
                <p>Registro: {riderDate(rider.created_at)}</p>
                <p className="text-xs">Fechas en America/Caracas</p>
              </div>
            </div>
            <div className="space-y-4 p-5">
              {rider.status === "PENDIENTE" && (
                <OperationNotice tone="warning">
                  Revisa la documentación antes de solicitar la activación. El
                  servidor comprueba los requisitos.
                </OperationNotice>
              )}
              {canManage && (canSuspend || canActivate) && (
                <button
                  className={operationStyles.button}
                  disabled={disabled}
                  onClick={() => {
                    setActionError(null);
                    setConfirmation({
                      id: rider.id,
                      name: riderName(rider),
                      status: canSuspend ? "SUSPENDIDO" : "ACTIVO",
                    });
                  }}
                >
                  {canSuspend
                    ? "Suspender"
                    : rider.status === "PENDIENTE"
                      ? "Aprobar Repartidor"
                      : "Activar"}
                </button>
              )}
            </div>
          </section>
          <div className="grid gap-5 lg:grid-cols-3">
            <section
              className={`${operationStyles.panel} space-y-4 border-violet-200 bg-violet-50/30 p-5`}
              aria-label="Vehículo asignado"
            >
              <SectionHeading
                icon={Bike}
                title="Vehículo y zona"
                tone="violet"
              />
              <p className="font-semibold">{vehicle?.type}</p>
              <p className="break-all font-mono text-sm">{vehicle?.plate}</p>
              <p className="text-sm">{vehicle?.ownership}</p>
              <p className="break-words text-sm">
                Zona: {rider.operating_zone || "No informada"}
              </p>
            </section>
            <section
              className={`${operationStyles.panel} space-y-4 p-5`}
              aria-label="Rendimiento informado"
            >
              <SectionHeading icon={Activity} title="Rendimiento" />
              <p>Entregas: {riderNumber(metrics?.total_deliveries)}</p>
              <p>Calificación: {riderNumber(metrics?.rating)}</p>
            </section>
            <section
              className={`${operationStyles.panel} space-y-4 border-amber-200 bg-amber-50/30 p-5`}
              aria-label="Nivel informado"
            >
              <SectionHeading
                icon={Award}
                title="Nivel del repartidor"
                tone="amber"
              />
              <OperationPill tone="amber">
                {rider.tier || "Nivel no informado"}
              </OperationPill>
              <p className="text-sm text-slate-600">
                Las bonificaciones dependen de las reglas vigentes; esta ficha
                no informa una tasa.
              </p>
            </section>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <section
              className={`${operationStyles.panel} space-y-4 p-5`}
              aria-label="Resumen financiero informado"
            >
              <SectionHeading
                icon={Wallet}
                title="Resumen financiero"
                tone="emerald"
                description="Valores informados en esta ficha."
              />
              <dl className="space-y-3">
                <div className="flex flex-wrap justify-between gap-2 rounded-xl bg-emerald-50 p-4">
                  <dt>Saldo informado</dt>
                  <dd className="font-bold tabular-nums">
                    {riderNumber(rider.wallet_balance)}
                  </dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2 rounded-xl bg-blue-50 p-4">
                  <dt>Pendiente informado</dt>
                  <dd className="font-bold tabular-nums">
                    {riderNumber(rider.pending_balance)}
                  </dd>
                </div>
              </dl>
              <p className="text-sm text-slate-600">
                La ficha no informa moneda ni disponibilidad de retiro.
              </p>
            </section>
            <section
              className={`${operationStyles.panel} space-y-4 p-5`}
              aria-label="Última ubicación reportada"
            >
              <SectionHeading
                icon={MapPin}
                title="Última ubicación reportada"
                description="Coordenadas de la última consulta; no representan seguimiento en vivo."
              />
              {coordinates ? (
                <p className="break-all rounded-xl border border-blue-100 bg-blue-50 p-5 font-mono">
                  {coordinates}
                </p>
              ) : (
                <OperationNotice>
                  Coordenadas no informadas o fuera de rango.
                </OperationNotice>
              )}
              <p className="text-sm text-slate-600">
                Reportada: {riderDate(rider.last_location_at)}
              </p>
              <p className="text-xs text-slate-500">America/Caracas</p>
            </section>
          </div>
        </>
      )}
      <Dialog
        open={!!confirmation}
        onOpenChange={(open) => {
          if (!open && !writing.current) setConfirmation(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-blue-200">
          <DialogHeader>
            <DialogTitle>
              {confirmation?.status === "SUSPENDIDO"
                ? "Suspender repartidor"
                : "Activar repartidor"}
            </DialogTitle>
            <DialogDescription>
              Confirma el cambio para {confirmation?.name}. ID:{" "}
              <span className="break-all">{confirmation?.id}</span>.{" "}
              {confirmation?.status === "SUSPENDIDO"
                ? "Se suspenderá su estado operativo."
                : "El servidor verificará su documentación. La activación no lo conecta automáticamente."}
            </DialogDescription>
          </DialogHeader>
          {actionError && (
            <p role="alert" className="text-sm text-rose-700">
              {actionError}
            </p>
          )}
          <DialogFooter>
            <button
              className={operationStyles.button}
              disabled={pending}
              onClick={() => setConfirmation(null)}
            >
              Cancelar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={disabled}
              onClick={() => void changeStatus()}
            >
              {pending ? "Guardando…" : "Confirmar estado"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
