"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Bike,
  FileText,
  Mail,
  Phone,
  RefreshCw,
  Search,
  UserPlus,
  UserRound,
  Users,
} from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationEmpty,
  OperationNotice,
  OperationPill,
  OperationsHeader,
  SectionHeading,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import { riderService } from "@/services/rider.service";
import type { Rider } from "@/types/user";

const readRoles = ["SUPERADMIN", "GERENTE", "OPERADOR"];
const states: Record<string, { label: string; tone: OperationTone }> = {
  ACTIVO: { label: "Activo", tone: "emerald" },
  PENDIENTE: { label: "Pendiente", tone: "amber" },
  SUSPENDIDO: { label: "Suspendido", tone: "rose" },
  INACTIVO: { label: "Inactivo", tone: "slate" },
  OCUPADO: { label: "Ocupado", tone: "blue" },
};
const normalize = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
export default function ManagerRidersPage() {
  return (
    <ManagerPageBoundary scope="rider-catalog" roles={readRoles}>
      <Catalog />
    </ManagerPageBoundary>
  );
}
function Catalog() {
  const { user } = useAuthStore();
  const canCreate = !!user && ["GERENTE", "SUPERADMIN"].includes(user.role);
  const [riders, setRiders] = useState<Rider[] | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("ALL");
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    setError(null);
    try {
      const data = await riderService.getAll();
      if (ticket === sequence.current) setRiders(data);
    } catch {
      if (ticket === sequence.current)
        setError(
          "No se pudieron cargar los repartidores. Se conserva la última consulta confirmada.",
        );
    } finally {
      if (ticket === sequence.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const requests = sequence;
    void load();
    return () => {
      requests.current++;
    };
  }, [load]);
  const visible = useMemo(() => {
    const term = normalize(search);
    return (riders ?? []).filter(
      (row) =>
        (status === "ALL" || row.status === status) &&
        normalize(
          [
            row.id,
            row.first_name,
            row.last_name,
            row.full_name,
            row.email,
            row.phone,
            row.vehicle_ownership_type === "EMPRESA"
              ? row.assigned_vehicle?.plate
              : row.vehicle_plate,
          ]
            .filter(Boolean)
            .join(" "),
        ).includes(term),
    );
  }, [riders, search, status]);
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={Users}
        eyebrow="Flota · Repartidores"
        title="Gestión de Repartidores"
        description="Administra perfiles, documentos y estados operativos."
        actions={
          <>
            <button
              className={operationStyles.button}
              disabled={loading}
              onClick={() => void load()}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`}
              />
              Actualizar
            </button>
            {canCreate && (
              <Link
                className={operationStyles.primaryButton}
                href="/manager/fleet/riders/new"
              >
                <UserPlus aria-hidden="true" className="h-4 w-4" />
                Nuevo Repartidor
              </Link>
            )}
          </>
        }
      />
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Filtros de repartidores"
      >
        <SectionHeading
          icon={Search}
          title="Buscar en los repartidores cargados"
          description="La búsqueda y el estado filtran solo los registros de la última consulta confirmada."
        />
        <div className="grid gap-4 md:grid-cols-3">
          <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
            Buscar por nombre, contacto, placa o ID
            <input
              className={operationStyles.field}
              placeholder="Nombre, email, teléfono, placa o ID"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="space-y-2 text-sm font-medium text-slate-700">
            Estado registrado
            <select
              className={operationStyles.field}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="ALL">Todos los estados</option>
              {Object.entries(states).map(([key, state]) => (
                <option key={key} value={key}>
                  {state.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
      {loading && (
        <OperationNotice role="status">
          Consultando repartidores…
        </OperationNotice>
      )}
      {error && (
        <OperationNotice role="alert" tone="warning">
          <p>{error}</p>
          <button
            className={operationStyles.button}
            disabled={loading}
            onClick={() => void load()}
          >
            Reintentar consulta
          </button>
        </OperationNotice>
      )}
      {riders !== null && (
        <section
          aria-label="Repartidores de la consulta confirmada"
          aria-busy={loading}
          className="space-y-4"
        >
          <p className="text-sm text-slate-600">
            {visible.length} coincidencias de {riders.length} repartidores
            cargados.
          </p>
          {!visible.length ? (
            <OperationEmpty>
              {riders.length
                ? "No hay coincidencias en los registros cargados. Ajusta la búsqueda o el estado."
                : "La consulta no devolvió repartidores."}
            </OperationEmpty>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((rider) => {
                const name =
                  [rider.first_name, rider.last_name]
                    .filter(Boolean)
                    .join(" ")
                    .trim() ||
                  rider.full_name?.trim() ||
                  "Nombre no informado";
                const state = states[rider.status ?? ""] ?? {
                  label: rider.status || "Estado no informado",
                  tone: "slate" as const,
                };
                const assigned =
                  rider.vehicle_ownership_type === "EMPRESA"
                    ? rider.assigned_vehicle
                    : null;
                const actualVehicle =
                  assigned?.id === rider.assigned_vehicle_id ? assigned : null;
                const type =
                  rider.vehicle_ownership_type === "EMPRESA"
                    ? actualVehicle?.type || "Vehículo de empresa"
                    : rider.vehicle_type || "Tipo no informado";
                const plate =
                  rider.vehicle_ownership_type === "EMPRESA"
                    ? actualVehicle?.plate
                    : rider.vehicle_plate;
                return (
                  <article
                    key={rider.id}
                    aria-label={`Repartidor ${rider.id}`}
                    className={`${operationStyles.panel} flex min-w-0 flex-col overflow-hidden transition-shadow hover:shadow-md`}
                  >
                    <div className="flex items-start gap-3 border-b border-blue-100 bg-gradient-to-br from-blue-50 via-white to-cyan-50 p-5">
                      <span className="rounded-xl border border-blue-200 bg-white p-3 text-blue-700">
                        <UserRound aria-hidden="true" className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <h2 className="break-words font-bold text-slate-900">
                          {name}
                        </h2>
                        <p className="mt-1 break-all font-mono text-xs text-slate-600">
                          ID repartidor: {rider.id}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-1 flex-col gap-4 p-5">
                      <div className="flex flex-wrap gap-2">
                        <OperationPill tone={state.tone}>
                          {state.label}
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
                      <p className="flex min-w-0 items-start gap-2 text-sm text-slate-600">
                        <Mail
                          aria-hidden="true"
                          className="mt-0.5 h-4 w-4 shrink-0"
                        />
                        <span className="break-all">
                          {rider.email || "Email no informado"}
                        </span>
                      </p>
                      <p className="flex items-center gap-2 text-sm text-slate-600">
                        <Phone
                          aria-hidden="true"
                          className="h-4 w-4 shrink-0"
                        />
                        {rider.phone || "Teléfono no informado"}
                      </p>
                      <div className="rounded-xl border border-violet-100 bg-violet-50/50 p-3">
                        <p className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                          <Bike
                            aria-hidden="true"
                            className="h-4 w-4 shrink-0 text-violet-700"
                          />
                          {type}
                        </p>
                        <p className="mt-1 break-all font-mono text-xs text-slate-600">
                          {plate || "Placa no informada"}
                        </p>
                        <p className="mt-2 text-xs text-slate-600">
                          {rider.vehicle_ownership_type === "EMPRESA"
                            ? "Empresa"
                            : rider.vehicle_ownership_type === "PROPIO"
                              ? "Propio"
                              : "Propiedad no informada"}
                        </p>
                      </div>
                      <div className="mt-auto flex flex-wrap gap-3 border-t border-slate-100 pt-4">
                        <Link
                          className={operationStyles.link}
                          href={`/manager/fleet/riders/${encodeURIComponent(rider.id)}/documents`}
                          aria-label={`Ver documentos de ${rider.id}`}
                        >
                          <FileText aria-hidden="true" className="h-4 w-4" />
                          Documentos
                        </Link>
                        <Link
                          className={operationStyles.link}
                          href={`/manager/fleet/riders/${encodeURIComponent(rider.id)}`}
                          aria-label={`Ver perfil de ${rider.id}`}
                        >
                          Ver perfil
                        </Link>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
