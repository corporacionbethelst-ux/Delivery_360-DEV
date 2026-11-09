"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  ArrowLeft,
  LocateFixed,
  MapPin,
  Navigation,
  RefreshCw,
  Search,
  Users,
  Wifi,
} from "lucide-react";
import {
  OperationsHeader,
  OperationEmpty,
  OperationMetric,
  OperationNotice,
  OperationPill,
  SectionHeading,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import { riderService } from "@/services/rider.service";
import type { Rider } from "@/types/user";
import { riderDate, riderName, riderVehicle } from "@/lib/rider-display";
import {
  RIDER_MAP_POLL_MS,
  riderMapAvailability,
  riderMapMatches,
  riderMapPosition,
  riderMapStatuses,
  type RiderMapFocus,
  type RiderMapPoint,
} from "@/lib/rider-map";

const MapCanvas = dynamic(() => import("./RiderMapCanvas"), {
  ssr: false,
  loading: () => (
    <p role="status" className="p-5">
      Preparando el mapa…
    </p>
  ),
});
export default function MapPageContent() {
  const [snapshot, setSnapshot] = useState<{ rows: Rider[]; at: Date } | null>(
    null,
  );
  const [loading, setLoading] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [automatic, setAutomatic] = useState(true),
    [tabHidden, setTabHidden] = useState(false);
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("ALL"),
    [availability, setAvailability] = useState("ALL"),
    [location, setLocation] = useState("ALL");
  const [focus, setFocus] = useState<RiderMapFocus | null>(null),
    [fitSequence, setFitSequence] = useState(0);
  const alive = useRef(false),
    sequence = useRef(0),
    flight = useRef<number | null>(null),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null),
    automaticRef = useRef(true);
  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);
  const load = useCallback(
    async function refresh() {
      if (!alive.current || flight.current !== null) return;
      clearTimer();
      const ticket = ++sequence.current;
      flight.current = ticket;
      setLoading(true);
      setError(null);
      const current = () => alive.current && sequence.current === ticket;
      try {
        const rows = await riderService.getAll();
        if (current()) setSnapshot({ rows, at: new Date() });
      } catch (error) {
        if (current())
          setError(
            error instanceof Error && error.name !== "AxiosError"
              ? error.message
              : "No se pudo consultar la ubicación de los repartidores.",
          );
      } finally {
        if (flight.current === ticket) flight.current = null;
        if (current()) {
          setLoading(false);
          if (automaticRef.current && !document.hidden)
            timer.current = setTimeout(() => void refresh(), RIDER_MAP_POLL_MS);
        }
      }
    },
    [clearTimer],
  );
  useEffect(() => {
    const requests = sequence,
      pending = flight;
    alive.current = true;
    pending.current = null;
    setTabHidden(document.hidden);
    void load();
    const visibility = () => {
      setTabHidden(document.hidden);
      clearTimer();
      if (!document.hidden && automaticRef.current) void load();
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false;
      requests.current++;
      pending.current = null;
      clearTimer();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [clearTimer, load]);
  const toggleAutomatic = (enabled: boolean) => {
    automaticRef.current = enabled;
    setAutomatic(enabled);
    clearTimer();
    if (enabled && !document.hidden && flight.current === null) void load();
  };
  const rows = snapshot?.rows;
  const filtered = useMemo(
    () =>
      (rows ?? []).filter((row) =>
        riderMapMatches(row, search, status, availability, location),
      ),
    [rows, search, status, availability, location],
  );
  const points: RiderMapPoint[] = useMemo(
    () =>
      filtered.flatMap((rider) => {
        const position = riderMapPosition(rider);
        return position ? [{ rider, position }] : [];
      }),
    [filtered],
  );
  const resetView = () => {
    setFocus(null);
    setFitSequence((value) => value + 1);
  };
  const center = (position: [number, number]) =>
    setFocus((previous) => ({
      position,
      sequence: (previous?.sequence ?? 0) + 1,
    }));
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={Navigation}
        eyebrow="Flota · Ubicaciones"
        title="Mapa de Repartidores"
        description="Últimas ubicaciones registradas. La consulta automática se renueva cada 20 segundos; no representa seguimiento continuo."
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
              className={operationStyles.primaryButton}
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`}
              />
              Actualizar ubicaciones
            </button>
          </>
        }
      />
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Filtros del mapa"
      >
        <SectionHeading
          icon={Search}
          title="Explorar la consulta cargada"
          description="Los filtros actúan localmente sobre el listado y sus marcadores."
        />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-2 text-sm font-medium">
            Buscar por nombre, contacto, placa o ID
            <input
              className={operationStyles.field}
              placeholder="Buscar repartidor…"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                resetView();
              }}
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Estado registrado
            <select
              className={operationStyles.field}
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                resetView();
              }}
            >
              <option value="ALL">Todos los estados</option>
              {Object.entries(riderMapStatuses).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
              <option value="UNKNOWN">Estado no informado</option>
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Conexión informada
            <select
              className={operationStyles.field}
              value={availability}
              onChange={(event) => {
                setAvailability(event.target.value);
                resetView();
              }}
            >
              <option value="ALL">Todas las conexiones</option>
              <option value="ONLINE">En línea</option>
              <option value="OFFLINE">Desconectado</option>
              <option value="UNKNOWN">No informada</option>
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Ubicación registrada
            <select
              className={operationStyles.field}
              value={location}
              onChange={(event) => {
                setLocation(event.target.value);
                resetView();
              }}
            >
              <option value="ALL">Todas las ubicaciones</option>
              <option value="VALID">Con coordenadas válidas</option>
              <option value="MISSING">Sin coordenadas válidas</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={automatic}
              onChange={(event) => toggleAutomatic(event.target.checked)}
            />
            Actualización automática (20 s)
          </label>
          <span className="text-sm text-slate-600">
            {automatic
              ? tabHidden
                ? "Consulta automática pausada: pestaña oculta."
                : "Consulta automática habilitada."
              : "Consulta automática pausada por el usuario."}
          </span>
        </div>
        <p className="text-xs text-slate-600">
          Consulta confirmada:{" "}
          {snapshot ? riderDate(snapshot.at) : "Sin consulta confirmada"}.
          America/Caracas.
        </p>
      </section>
      {loading && (
        <OperationNotice role="status">
          Consultando ubicaciones…
        </OperationNotice>
      )}
      {error && (
        <OperationNotice role="alert" tone="warning">
          <p>{error}</p>
          <p>Se conserva la última consulta confirmada, si existe.</p>
          <button
            className={operationStyles.button}
            disabled={loading}
            onClick={() => void load()}
          >
            Reintentar ubicaciones
          </button>
        </OperationNotice>
      )}
      {snapshot && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <OperationMetric
              icon={Users}
              label="Repartidores cargados"
              value={snapshot.rows.length}
            />
            <OperationMetric
              icon={Wifi}
              label="En línea entre los cargados"
              value={
                snapshot.rows.filter((row) => row.is_online === true).length
              }
              tone="emerald"
            />
            <OperationMetric
              icon={MapPin}
              label="Con ubicación en el filtro actual"
              value={points.length}
              tone="violet"
            />
          </div>
          <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
            <section
              className={`${operationStyles.panel} min-w-0 space-y-4 p-4`}
              aria-label="Listado del mapa"
              aria-busy={loading}
            >
              <SectionHeading
                icon={Users}
                title="Repartidores del filtro"
                description={`${filtered.length} coincidencias de ${snapshot.rows.length} repartidores cargados.`}
              />
              <div
                className="max-h-[42rem] space-y-3 overflow-y-auto overscroll-contain pr-1"
                tabIndex={0}
                role="region"
                aria-label="Tarjetas de repartidores"
              >
                {!filtered.length ? (
                  <OperationEmpty>
                    {snapshot.rows.length
                      ? "No hay coincidencias. Ajusta los filtros."
                      : "La consulta no devolvió repartidores."}
                  </OperationEmpty>
                ) : (
                  filtered.map((rider) => {
                    const position = riderMapPosition(rider),
                      vehicle = riderVehicle(rider);
                    const tone: OperationTone =
                      rider.status === "ACTIVO"
                        ? "emerald"
                        : rider.status === "PENDIENTE"
                          ? "amber"
                          : rider.status === "SUSPENDIDO"
                            ? "rose"
                            : "slate";
                    return (
                      <article
                        key={rider.id}
                        aria-label={`Repartidor ${rider.id}`}
                        className="min-w-0 space-y-3 rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50/50 via-white to-cyan-50/30 p-4"
                      >
                        <h3 className="break-words font-bold">
                          {riderName(rider)}
                        </h3>
                        <p className="break-all font-mono text-xs text-slate-500">
                          ID: {rider.id}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <OperationPill tone={tone}>
                            {riderMapStatuses[
                              rider.status as keyof typeof riderMapStatuses
                            ] ||
                              rider.status ||
                              "Estado no informado"}
                          </OperationPill>
                          <OperationPill
                            tone={
                              rider.is_online === true ? "emerald" : "slate"
                            }
                          >
                            {riderMapAvailability(rider)}
                          </OperationPill>
                        </div>
                        <p className="break-all text-sm text-violet-800">
                          {vehicle.type} · {vehicle.plate}
                        </p>
                        <p className="text-xs text-slate-600">
                          Reportada: {riderDate(rider.last_location_at)}
                        </p>
                        <p className="break-all font-mono text-xs text-slate-600">
                          {position
                            ? position
                                .map((value) => value.toFixed(6))
                                .join(", ")
                            : "Ubicación no informada o inválida"}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <button
                            className={operationStyles.button}
                            disabled={!position}
                            onClick={() => {
                              if (position) center(position);
                            }}
                            aria-label={`Centrar en mapa a ${riderName(rider)}`}
                          >
                            <LocateFixed
                              aria-hidden="true"
                              className="h-4 w-4"
                            />
                            Centrar
                          </button>
                          <Link
                            className={operationStyles.link}
                            href={`/manager/fleet/riders/${encodeURIComponent(rider.id)}`}
                            aria-label={`Ver perfil de ${rider.id}`}
                          >
                            Ver perfil
                          </Link>
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </section>
            <section
              className={`${operationStyles.panel} isolate min-w-0 overflow-hidden`}
              aria-label="Mapa de ubicaciones registradas"
            >
              <div className="space-y-3 border-b border-violet-100 bg-violet-50/40 p-4">
                <SectionHeading
                  icon={MapPin}
                  title="Ubicaciones del filtro"
                  tone="violet"
                  description="Los puntos indican la última coordenada registrada, aunque el repartidor esté desconectado."
                />
                <button
                  className={operationStyles.button}
                  disabled={!points.length}
                  onClick={() => {
                    setFocus(null);
                    setFitSequence((value) => value + 1);
                  }}
                >
                  Ajustar a los puntos visibles
                </button>
                {!points.length && (
                  <p className="text-sm text-slate-600">
                    Sin coordenadas válidas en el filtro. Se muestra una vista
                    mundial de referencia.
                  </p>
                )}
              </div>
              <MapCanvas
                points={points}
                focus={focus}
                fitSequence={fitSequence}
              />
            </section>
          </div>
        </>
      )}
    </main>
  );
}
