"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Archive,
  ArrowLeft,
  Bell,
  BookOpen,
  CheckCheck,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { alertService, type Alert } from "@/services/alert.service";
import { alertDate } from "@/lib/alert-date";

export const ALERT_PAGE_SIZE = 50;
const roles = ["SUPERADMIN", "GERENTE", "OPERADOR"];
type Query = { status: "ALL" | "READ" | "UNREAD"; offset: number };
type Confirmation =
  | { kind: "all" }
  | { kind: "dismiss"; id: string; title: string };
const statusLabels = {
  ALL: "Todas las alertas",
  UNREAD: "No leídas",
  READ: "Leídas",
};
const severityLabels: Record<string, { label: string; tone: OperationTone }> = {
  LOW: { label: "Baja", tone: "blue" },
  MEDIUM: { label: "Media", tone: "amber" },
  HIGH: { label: "Alta", tone: "rose" },
  CRITICAL: { label: "Crítica", tone: "rose" },
};
const typeLabels: Record<string, string> = {
  DELAY: "Retraso",
  FAILURE: "Fallo",
  VEHICLE: "Vehículo",
  SYSTEM: "Sistema",
  PAYMENT: "Pago",
  RIDER: "Repartidor",
  SLA_WARNING: "Aviso SLA",
};
const date = (value: unknown) =>
  alertDate(value)?.toLocaleString("es-VE", { timeZone: "America/Caracas" }) ??
  "Fecha no disponible";
const normalize = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
const sameQuery = (a: Query, b: Query) =>
  a.status === b.status && a.offset === b.offset;

export default function PersonalAlertCenter({
  mode,
}: {
  mode: "manager" | "operator";
}) {
  return (
    <ManagerPageBoundary roles={roles} scope={`personal-alert-center:${mode}`}>
      <Center mode={mode} />
    </ManagerPageBoundary>
  );
}
function Center({ mode }: { mode: "manager" | "operator" }) {
  const [query, setQuery] = useState<Query>({ status: "ALL", offset: 0 });
  const queryRef = useRef(query);
  const [snapshot, setSnapshot] = useState<{
    query: Query;
    rows: Alert[];
    more: boolean;
    at: Date;
  } | null>(null);
  const [loading, setLoading] = useState(false),
    [pending, setPending] = useState(false),
    [needsRefresh, setNeedsRefresh] = useState(false);
  const [readError, setReadError] = useState<string | null>(null),
    [actionError, setActionError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null);
  const [search, setSearch] = useState(""),
    [severity, setSeverity] = useState("ALL"),
    [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const alive = useRef(false),
    sequence = useRef(0),
    reading = useRef<number | null>(null),
    writing = useRef(false);
  const load = useCallback(async (target: Query) => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    reading.current = ticket;
    setLoading(true);
    setReadError(null);
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      sameQuery(target, queryRef.current);
    try {
      const rows = await alertService.getAll({
        status: target.status,
        limit: ALERT_PAGE_SIZE + 1,
        offset: target.offset,
      });
      if (current()) {
        setSnapshot({
          query: { ...target },
          rows: rows.slice(0, ALERT_PAGE_SIZE),
          more: rows.length > ALERT_PAGE_SIZE,
          at: new Date(),
        });
        setNeedsRefresh(false);
        setActionError(null);
      }
    } catch {
      if (current())
        setReadError(
          "La consulta no se pudo confirmar. Se conservan los últimos datos cargados, si existen.",
        );
    } finally {
      if (reading.current === ticket) reading.current = null;
      if (current()) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const requests = sequence,
      reads = reading;
    alive.current = true;
    return () => {
      alive.current = false;
      requests.current++;
      reads.current = null;
    };
  }, []);
  useEffect(() => {
    void load(query);
  }, [load, query]);
  const chooseQuery = (target: Query) => {
    if (writing.current) return;
    queryRef.current = target;
    sequence.current++;
    setQuery(target);
  };
  const matching = !!snapshot && sameQuery(snapshot.query, query);
  const disabled =
    pending || loading || !matching || !!readError || needsRefresh;
  const activeRows = useMemo(
    () => snapshot?.rows.filter((row) => !row.isDismissed) ?? [],
    [snapshot],
  );
  const filtered = useMemo(
    () =>
      activeRows.filter((row) => {
        const matchesSeverity =
          severity === "ALL" ||
          (severity === "UNKNOWN"
            ? !Object.hasOwn(severityLabels, row.severity)
            : row.severity === severity);
        return (
          matchesSeverity &&
          normalize(
            [row.title, row.description, row.id, row.orderId, row.riderId]
              .filter(Boolean)
              .join(" "),
          ).includes(normalize(search))
        );
      }),
    [activeRows, search, severity],
  );
  const perform = async (kind: "read" | "dismiss" | "all", id?: string) => {
    if (
      disabled ||
      writing.current ||
      reading.current !== null ||
      !alive.current
    )
      return;
    writing.current = true;
    setPending(true);
    setActionError(null);
    setSuccess(null);
    setNeedsRefresh(true);
    try {
      let message: string;
      if (kind === "all") {
        const result = await alertService.markAllAsRead();
        message = `${result.count} alertas personales marcadas como leídas por el servidor.`;
      } else if (kind === "read") {
        await alertService.markAsRead(id!);
        message = "Alerta marcada como leída en tu bandeja.";
      } else {
        await alertService.dismiss(id!);
        message = "Alerta descartada de tu bandeja.";
      }
      if (!alive.current) return;
      setConfirmation(null);
      setSuccess(message);
      if (queryRef.current.offset !== 0) chooseAfterWrite();
      else await load(queryRef.current);
    } catch {
      if (alive.current) {
        setConfirmation(null);
        setActionError(
          "No se pudo confirmar el resultado de la acción. Actualiza la bandeja y revisa su estado antes de repetir.",
        );
      }
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const chooseAfterWrite = () => {
    const target = { ...queryRef.current, offset: 0 };
    queryRef.current = target;
    sequence.current++;
    setQuery(target);
  };
  const dashboard = mode === "manager" ? "/manager" : "/operator";
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={Bell}
        eyebrow="Operaciones · Bandeja personal"
        title="Centro de Alertas"
        description="Tus notificaciones operacionales. Leer o descartar una alerta no resuelve la incidencia operativa ni confirma el cumplimiento de un SLA."
        actions={
          <>
            <Link className={operationStyles.button} href={dashboard}>
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver al panel
            </Link>
            <button
              className={operationStyles.button}
              disabled={loading || pending}
              onClick={() => void load(queryRef.current)}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={disabled}
              onClick={() => setConfirmation({ kind: "all" })}
            >
              <CheckCheck aria-hidden="true" className="h-4 w-4" />
              Leer todas mis alertas
            </button>
          </>
        }
      />
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Consulta y filtros de alertas"
      >
        <SectionHeading
          icon={Search}
          title="Explorar tu bandeja"
          description="El estado consulta el servidor; la búsqueda y severidad filtran solo la página cargada."
        />
        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label="Estado de lectura"
        >
          {Object.entries(statusLabels).map(([value, label]) => (
            <button
              key={value}
              className={
                query.status === value
                  ? operationStyles.primaryButton
                  : operationStyles.button
              }
              aria-pressed={query.status === value}
              disabled={pending}
              onClick={() =>
                chooseQuery({ status: value as Query["status"], offset: 0 })
              }
            >
              {label}
            </button>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm font-medium">
            Buscar en esta página
            <input
              className={operationStyles.field}
              placeholder="Título, descripción o ID relacionado"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Severidad en esta página
            <select
              className={operationStyles.field}
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option value="ALL">Todas las severidades</option>
              {Object.entries(severityLabels).map(([value, item]) => (
                <option key={value} value={value}>
                  {item.label}
                </option>
              ))}
              <option value="UNKNOWN">Severidad no reconocida</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-slate-600">
          Se muestran hasta 50 registros por página. El servidor no informa un
          total global. Fechas en America/Caracas.
        </p>
      </section>
      {loading && (
        <OperationNotice role="status">
          Consultando tus alertas…
        </OperationNotice>
      )}
      {readError && (
        <OperationNotice role="alert" tone="warning">
          <p>{readError}</p>
          <button
            className={operationStyles.button}
            disabled={loading || pending}
            onClick={() => void load(queryRef.current)}
          >
            Reintentar consulta
          </button>
        </OperationNotice>
      )}
      {actionError && (
        <OperationNotice role="alert" tone="error">
          {actionError}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice role="status" tone="success">
          {success}
        </OperationNotice>
      )}
      {snapshot && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <OperationMetric
              icon={Bell}
              label="Registros de la página confirmada"
              value={snapshot.rows.length}
            />
            <OperationMetric
              icon={BookOpen}
              label="No leídas visibles en esta página"
              value={activeRows.filter((row) => !row.isRead).length}
              tone="amber"
            />
            <OperationMetric
              icon={ShieldAlert}
              label="Coincidencias locales"
              value={filtered.length}
              tone="violet"
            />
          </div>
          <section
            className="space-y-4"
            aria-label="Alertas de la consulta confirmada"
            aria-busy={loading}
          >
            <p className="text-sm text-slate-600">
              Consulta confirmada: {statusLabels[snapshot.query.status]}, página{" "}
              {snapshot.query.offset / ALERT_PAGE_SIZE + 1}. {date(snapshot.at)}{" "}
              · America/Caracas.
            </p>
            {!matching && (
              <OperationNotice>
                Las tarjetas corresponden a la consulta confirmada indicada
                arriba. La selección solicitada todavía no está confirmada.
              </OperationNotice>
            )}
            {!filtered.length ? (
              <OperationEmpty>
                {activeRows.length
                  ? "No hay coincidencias en esta página. Ajusta los filtros locales."
                  : "La página consultada no contiene alertas visibles."}
              </OperationEmpty>
            ) : (
              filtered.map((row) => {
                const meta = Object.hasOwn(severityLabels, row.severity)
                  ? severityLabels[row.severity]
                  : undefined;
                return (
                  <article
                    key={row.id}
                    aria-label={`Alerta ${row.id}`}
                    className={`${operationStyles.panel} overflow-hidden border-l-4 ${row.severity === "CRITICAL" ? "border-l-rose-600" : row.severity === "HIGH" ? "border-l-orange-500" : row.severity === "MEDIUM" ? "border-l-amber-500" : row.severity === "LOW" ? "border-l-blue-500" : "border-l-slate-300"}`}
                  >
                    <div className="flex flex-col gap-4 p-5 md:flex-row md:justify-between">
                      <div className="min-w-0 flex-1 space-y-3">
                        <div className="flex flex-wrap gap-2">
                          <OperationPill tone={meta?.tone}>
                            {meta?.label ||
                              row.severity ||
                              "Severidad no informada"}
                          </OperationPill>
                          <OperationPill tone={row.isRead ? "slate" : "amber"}>
                            {row.isRead ? "Leída" : "No leída"}
                          </OperationPill>
                          <OperationPill tone="violet">
                            {Object.hasOwn(typeLabels, row.type)
                              ? typeLabels[row.type]
                              : row.type || "Tipo no informado"}
                          </OperationPill>
                        </div>
                        <h2 className="break-words text-lg font-bold">
                          {row.title || "Título no informado"}
                        </h2>
                        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-600">
                          {row.description || "Descripción no informada"}
                        </p>
                        <p className="break-all font-mono text-xs text-slate-500">
                          ID alerta: {row.id}
                        </p>
                        <p className="text-xs text-slate-600">
                          Creada: {date(row.createdAt)}
                        </p>
                        <div className="flex flex-wrap gap-3">
                          {row.orderId && (
                            <Link
                              className={`${operationStyles.link} break-all text-sm`}
                              href={
                                mode === "manager"
                                  ? `/manager/operations/orders/${encodeURIComponent(row.orderId)}`
                                  : `/operator/orders/${encodeURIComponent(row.orderId)}`
                              }
                            >
                              Orden: {row.orderId}
                            </Link>
                          )}
                          {row.riderId && (
                            <Link
                              className={`${operationStyles.link} break-all text-sm`}
                              href={`/manager/fleet/riders/${encodeURIComponent(row.riderId)}`}
                            >
                              Repartidor: {row.riderId}
                            </Link>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-start gap-2 md:max-w-60 md:justify-end">
                        {!row.isRead && (
                          <button
                            className={operationStyles.button}
                            disabled={disabled}
                            onClick={() => void perform("read", row.id)}
                          >
                            Marcar como leída
                          </button>
                        )}
                        <button
                          className={operationStyles.button}
                          disabled={disabled}
                          onClick={() =>
                            setConfirmation({
                              kind: "dismiss",
                              id: row.id,
                              title: row.title,
                            })
                          }
                        >
                          <Archive aria-hidden="true" className="h-4 w-4" />
                          Descartar alerta
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })
            )}
          </section>
          <nav
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"
            aria-label="Paginación de alertas"
          >
            <button
              className={operationStyles.button}
              disabled={
                loading ||
                pending ||
                !matching ||
                snapshot.query.offset === 0 ||
                !!readError
              }
              onClick={() =>
                chooseQuery({
                  ...snapshot.query,
                  offset: Math.max(0, snapshot.query.offset - ALERT_PAGE_SIZE),
                })
              }
            >
              Página anterior
            </button>
            <span className="text-sm text-slate-600">
              Página {snapshot.query.offset / ALERT_PAGE_SIZE + 1} de la
              consulta confirmada
            </span>
            <button
              className={operationStyles.button}
              disabled={
                loading || pending || !matching || !snapshot.more || !!readError
              }
              onClick={() =>
                chooseQuery({
                  ...snapshot.query,
                  offset: snapshot.query.offset + ALERT_PAGE_SIZE,
                })
              }
            >
              Página siguiente
            </button>
          </nav>
        </>
      )}
      <Dialog
        open={!!confirmation}
        onOpenChange={(open) => {
          if (!open && !writing.current) setConfirmation(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-amber-200">
          <DialogHeader>
            <DialogTitle>
              {confirmation?.kind === "all"
                ? "Leer todas mis alertas"
                : "Descartar alerta personal"}
            </DialogTitle>
            <DialogDescription>
              {confirmation?.kind === "all" ? (
                "Afecta a todas tus alertas operacionales no leídas, incluidas otras páginas y las que no coincidan con los filtros locales. Esta acción no resuelve las incidencias operativas."
              ) : (
                <>
                  Se retirará de tu bandeja la alerta «
                  {confirmation?.kind === "dismiss" ? confirmation.title : ""}».
                  ID:{" "}
                  <span className="break-all">
                    {confirmation?.kind === "dismiss" ? confirmation.id : ""}
                  </span>
                  . No resuelve la incidencia operativa.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
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
              onClick={() => {
                if (confirmation?.kind === "all") void perform("all");
                else if (confirmation?.kind === "dismiss")
                  void perform("dismiss", confirmation.id);
              }}
            >
              {pending ? "Guardando…" : "Confirmar"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
