"use client";
import { useState } from "react";
import {
  Download,
  History,
  RefreshCw,
  Search,
  ShieldCheck,
  Terminal,
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
import type { AuditLog } from "@/services/audit.service";
import {
  AUDIT_ACTIONS,
  AUDIT_EXPORT_LIMIT,
  AUDIT_PAGE_SIZE,
  AUDIT_RESULTS,
  auditDraftFilters,
  auditEventTime,
  auditScope,
  auditTime,
  emptyAuditDraft,
  type AuditDraft,
} from "@/lib/system-audit";
import { useSystemAudit } from "@/hooks/useSystemAudit";

function Result({ row }: { row: AuditLog }) {
  const tone: OperationTone =
    row.status === "SUCCESS"
      ? "emerald"
      : row.status === "WARNING"
        ? "amber"
        : row.status === "FAILURE"
          ? "rose"
          : "slate";
  return (
    <OperationPill tone={tone}>
      {Object.hasOwn(AUDIT_RESULTS, row.status)
        ? AUDIT_RESULTS[row.status as keyof typeof AUDIT_RESULTS]
        : row.status}
    </OperationPill>
  );
}
function Actor({ row }: { row: AuditLog }) {
  const identified = !!row.user_id || !!row.user_email;
  return (
    <>
      <p className="break-all font-semibold">
        {row.user_email || (row.user_id ? `Usuario ${row.user_id}` : "SYSTEM")}
      </p>
      <p className="text-xs text-slate-600">
        {row.user_role || (identified ? "Rol no informado" : "SYSTEM")}
      </p>
    </>
  );
}
export default function AdminAuditPage() {
  return (
    <ManagerPageBoundary scope="system-audit">
      <AuditPage />
    </ManagerPageBoundary>
  );
}
function AuditPage() {
  const state = useSystemAudit(),
    [draft, setDraft] = useState<AuditDraft>({ ...emptyAuditDraft }),
    [applied, setApplied] = useState<AuditDraft>({ ...emptyAuditDraft }),
    [filterError, setFilterError] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied),
    snapshot = state.snapshot,
    page = snapshot?.page,
    summary = state.summary?.data;
  const change = (key: keyof AuditDraft, value: string) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setFilterError(null);
  };
  const apply = (event: React.FormEvent) => {
    event.preventDefault();
    if (state.exporting) return;
    try {
      const filters = auditDraftFilters(draft);
      setApplied({ ...draft });
      setFilterError(null);
      state.choose(filters);
    } catch (error) {
      setFilterError(
        error instanceof Error
          ? error.message
          : "Revisa los filtros de auditoría.",
      );
    }
  };
  const clear = () => {
    if (state.exporting) return;
    setDraft({ ...emptyAuditDraft });
    setApplied({ ...emptyAuditDraft });
    setFilterError(null);
    state.choose({ limit: AUDIT_PAGE_SIZE, offset: 0 });
  };
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        audit
        icon={History}
        eyebrow="Administración · Trazabilidad"
        title="Auditoría del Sistema"
        description="Revisa acciones, actores y recursos con el resultado registrado en cada evento."
        actions={
          <>
            <button
              className={operationStyles.button}
              disabled={
                state.loading || state.summaryLoading || state.exporting
              }
              onClick={state.refresh}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar auditoría
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={!state.ready || dirty || state.exporting}
              onClick={state.openExport}
            >
              <Download aria-hidden="true" className="h-4 w-4" />
              Exportar CSV
            </button>
          </>
        }
      />
      <section aria-label="Resumen global de auditoría" className="space-y-3">
        <SectionHeading
          icon={ShieldCheck}
          title="Actividad global · últimos 7 días"
          tone="violet"
          description="Este resumen es independiente de los filtros de eventos. El éxito informado puede incluir advertencias."
        />
        {state.summaryLoading && (
          <OperationNotice role="status">
            Consultando resumen global…
          </OperationNotice>
        )}
        {state.summaryError && (
          <OperationNotice tone="warning" role="alert">
            <p>{state.summaryError}</p>
            <button
              className={operationStyles.button}
              disabled={state.summaryLoading || state.exporting}
              onClick={state.retrySummary}
            >
              Reintentar resumen
            </button>
          </OperationNotice>
        )}
        {summary && (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <OperationMetric
                icon={History}
                label="Eventos del período global"
                value={summary.total}
                tone="violet"
              />
              <OperationMetric
                icon={Terminal}
                label="Tipos de acción en el período"
                value={Object.keys(summary.by_action).length}
              />
              <OperationMetric
                icon={ShieldCheck}
                label="Eventos con éxito informado"
                value={summary.by_success.true ?? summary.by_success.True ?? 0}
                tone="emerald"
              />
            </div>
            <p className="text-xs text-slate-600">
              Período desde {auditTime(summary.period_start)}. Resumen
              confirmado: {auditTime(state.summary?.at)} · America/Caracas.
            </p>
          </>
        )}
      </section>
      <form
        onSubmit={apply}
        className={`${operationStyles.panel} space-y-5 p-5`}
        aria-label="Filtros de auditoría"
        noValidate
      >
        <SectionHeading
          icon={Search}
          title="Explorar los eventos"
          description="Aplica los filtros para consultar el servidor. Las fechas abarcan días completos de America/Caracas."
        />
        <fieldset
          disabled={state.exporting}
          className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4"
        >
          <label className="space-y-2 text-sm font-medium md:col-span-2">
            Buscar en la auditoría
            <input
              className={operationStyles.field}
              value={draft.search}
              onChange={(e) => change("search", e.target.value)}
              placeholder="Descripción, usuario, recurso, IP o ruta"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Acción registrada
            <select
              className={operationStyles.field}
              value={draft.action}
              onChange={(e) => change("action", e.target.value)}
            >
              <option value="ALL">Todas las acciones</option>
              {AUDIT_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {action}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Resultado del evento
            <select
              className={operationStyles.field}
              value={draft.status}
              onChange={(e) => change("status", e.target.value)}
            >
              <option value="ALL">Todos los resultados</option>
              {Object.entries(AUDIT_RESULTS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Tipo de recurso
            <input
              className={operationStyles.field}
              value={draft.resource_type}
              onChange={(e) => change("resource_type", e.target.value)}
              placeholder="Order, User, Rider…"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            ID de recurso
            <input
              className={operationStyles.field}
              value={draft.resource_id}
              onChange={(e) => change("resource_id", e.target.value)}
            />
          </label>
          <label className="space-y-2 text-sm font-medium md:col-span-2">
            ID de usuario (UUID)
            <input
              className={operationStyles.field}
              value={draft.user_id}
              onChange={(e) => change("user_id", e.target.value)}
              placeholder="Identificador completo del actor"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Desde (Caracas)
            <input
              type="date"
              className={operationStyles.field}
              value={draft.date_from}
              onChange={(e) => change("date_from", e.target.value)}
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Hasta (Caracas)
            <input
              type="date"
              className={operationStyles.field}
              value={draft.date_to}
              onChange={(e) => change("date_to", e.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-end gap-3 md:col-span-2">
            <button className={operationStyles.primaryButton} type="submit">
              Aplicar filtros
            </button>
            <button
              type="button"
              className={operationStyles.button}
              onClick={clear}
            >
              Limpiar filtros
            </button>
          </div>
        </fieldset>
        {dirty && (
          <p className="text-sm text-amber-900">
            Hay cambios sin aplicar. La tabla conserva su consulta confirmada;
            aplica los filtros antes de exportar.
          </p>
        )}
        {filterError && (
          <OperationNotice tone="error" role="alert">
            {filterError}
          </OperationNotice>
        )}
      </form>
      {state.loading && (
        <OperationNotice role="status">Consultando eventos…</OperationNotice>
      )}
      {state.readError && (
        <OperationNotice tone="warning" role="alert">
          <p>{state.readError}</p>
          <button
            className={operationStyles.button}
            disabled={state.loading || state.exporting}
            onClick={state.retry}
          >
            Reintentar eventos
          </button>
        </OperationNotice>
      )}
      {state.downloaded && (
        <OperationNotice tone="success" role="status">
          Se inició la descarga del CSV con los filtros confirmados, desde el
          primer resultado y hasta {AUDIT_EXPORT_LIMIT} eventos. Los registros
          pueden haber cambiado desde la consulta de la tabla.
        </OperationNotice>
      )}
      {snapshot && page && (
        <section
          className="space-y-4"
          aria-label="Eventos de la consulta confirmada"
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <OperationMetric
              icon={History}
              label="Eventos en la consulta confirmada"
              value={page.total}
              tone="violet"
            />
            <OperationMetric
              icon={Terminal}
              label="Eventos en esta página"
              value={page.items.length}
            />
            <OperationMetric
              icon={Search}
              label="Página confirmada"
              value={Math.floor(page.offset / page.limit) + 1}
              tone="amber"
            />
          </div>
          <p className="break-words text-sm text-slate-600">
            Consulta confirmada: {auditScope(snapshot.filters)}. Lectura:{" "}
            {auditTime(snapshot.at)} · America/Caracas.
          </p>
          {!state.matching && (
            <OperationNotice>
              Se conserva la consulta confirmada indicada arriba hasta confirmar
              la nueva selección.
            </OperationNotice>
          )}
          {!page.items.length ? (
            <OperationEmpty>
              {page.total && page.offset
                ? "Esta página ya no contiene eventos. Vuelve a una página anterior o actualiza la consulta."
                : "No se encontraron eventos en la consulta confirmada."}
            </OperationEmpty>
          ) : (
            <div
              role="region"
              aria-label="Tabla de auditoría"
              tabIndex={0}
              className={`${operationStyles.panel} overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-600`}
            >
              <table className="w-full min-w-[1050px] text-left text-sm">
                <thead className={operationStyles.tableHead}>
                  <tr>
                    {[
                      "Resultado",
                      "Acción",
                      "Actor",
                      "Fecha · Caracas",
                      "Recurso",
                      "Origen",
                      "Detalle",
                    ].map((name) => (
                      <th key={name} scope="col" className="p-4">
                        {name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {page.items.map((row) => (
                    <tr
                      key={row.id}
                      className="align-top hover:bg-violet-50/30"
                    >
                      <td className="space-y-1 p-4">
                        <Result row={row} />
                        {row.status_code != null && (
                          <p className="text-xs text-slate-500">
                            HTTP {row.status_code}
                          </p>
                        )}
                      </td>
                      <td className="max-w-[200px] space-y-1 p-4">
                        <p className="break-words font-bold">{row.action}</p>
                        <p className="break-all font-mono text-xs text-slate-500">
                          ID: {row.id}
                        </p>
                      </td>
                      <td className="max-w-[240px] space-y-1 p-4">
                        <Actor row={row} />
                      </td>
                      <td className="p-4 text-xs text-slate-600">
                        {auditEventTime(row)}
                      </td>
                      <td className="max-w-[200px] p-4">
                        <p className="font-semibold">
                          {row.resource_type || "Tipo no informado"}
                        </p>
                        <p className="break-all font-mono text-xs text-slate-600">
                          {row.resource_id || "ID no informado"}
                        </p>
                      </td>
                      <td className="max-w-[170px] space-y-1 break-all p-4 text-xs text-slate-600">
                        <p>{row.ip_address || "IP no informada"}</p>
                        <p>{row.request_method || "Método no informado"}</p>
                      </td>
                      <td className="max-w-xs space-y-3 p-4">
                        <p className="line-clamp-2 break-words text-slate-600">
                          {row.details ||
                            row.description ||
                            row.error_message ||
                            "Sin descripción informada"}
                        </p>
                        <button
                          className={operationStyles.link}
                          disabled={!state.ready || state.exporting}
                          onClick={() => state.openDetail(row)}
                          aria-label={`Ver detalle del evento ${row.id}`}
                        >
                          Ver detalle
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <nav
            className={`${operationStyles.panel} flex flex-wrap items-center justify-between gap-3 p-4`}
            aria-label="Paginación de auditoría"
          >
            <button
              className={operationStyles.button}
              disabled={!state.ready || state.exporting || page.offset === 0}
              onClick={() =>
                state.choose({
                  ...snapshot.filters,
                  offset: Math.max(0, page.offset - AUDIT_PAGE_SIZE),
                })
              }
            >
              Página anterior
            </button>
            <span className="text-sm text-slate-600">
              Página {Math.floor(page.offset / page.limit) + 1} · {page.total}{" "}
              eventos en la consulta
            </span>
            <button
              className={operationStyles.button}
              disabled={
                !state.ready ||
                state.exporting ||
                page.offset + page.limit >= page.total
              }
              onClick={() =>
                state.choose({
                  ...snapshot.filters,
                  offset: page.offset + AUDIT_PAGE_SIZE,
                })
              }
            >
              Página siguiente
            </button>
          </nav>
        </section>
      )}
      <Dialog
        open={!!state.selected}
        onOpenChange={(open) => {
          if (!open) state.closeDetail();
        }}
      >
        <DialogContent className="max-h-[90dvh] max-w-3xl overflow-y-auto rounded-2xl border-violet-200">
          <DialogHeader>
            <DialogTitle>Detalle del evento</DialogTitle>
            <DialogDescription className="break-all">
              ID: {state.selected?.id}. Consulta del registro original de
              auditoría.
            </DialogDescription>
          </DialogHeader>
          {state.detailLoading && (
            <OperationNotice role="status">
              Consultando detalle…
            </OperationNotice>
          )}
          {state.detailError && (
            <OperationNotice tone="warning" role="alert">
              <p>{state.detailError}</p>
              <button
                className={operationStyles.button}
                onClick={state.retryDetail}
              >
                Reintentar detalle
              </button>
            </OperationNotice>
          )}
          {state.detail && <EventDetail row={state.detail} />}
          <DialogFooter>
            <button
              className={operationStyles.button}
              onClick={state.closeDetail}
            >
              Cerrar detalle
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!state.exportScope}
        onOpenChange={(open) => {
          if (!open) state.closeExport();
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-amber-200">
          <DialogHeader>
            <DialogTitle>Exportar auditoría</DialogTitle>
            <DialogDescription>
              Se consultarán hasta {AUDIT_EXPORT_LIMIT} eventos desde el primer
              resultado de los filtros confirmados, incluyendo otras páginas. El
              archivo refleja los datos disponibles al exportar.
            </DialogDescription>
          </DialogHeader>
          <p className="break-words rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">
            {state.exportScope && auditScope(state.exportScope.filters)}
          </p>
          {state.exportScope &&
            state.exportScope.page.total > AUDIT_EXPORT_LIMIT && (
              <OperationNotice tone="warning">
                La consulta confirmada supera el límite. Acota los filtros para
                dividir la exportación.
              </OperationNotice>
            )}
          {state.exportError && (
            <OperationNotice tone="error" role="alert">
              {state.exportError}
            </OperationNotice>
          )}
          <DialogFooter>
            <button
              className={operationStyles.button}
              disabled={state.exporting}
              onClick={state.closeExport}
            >
              Cancelar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={state.exporting}
              onClick={() => void state.exportCsv()}
            >
              {state.exporting ? "Preparando CSV…" : "Descargar CSV"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
function EventDetail({ row }: { row: AuditLog }) {
  return (
    <div className="space-y-4">
      <section className="space-y-3 rounded-xl border border-blue-100 bg-blue-50/30 p-4">
        <SectionHeading icon={History} title="Evento y actor" />
        <Result row={row} />
        <p className="break-words font-bold">
          {row.action} · {auditEventTime(row)} · America/Caracas
        </p>
        <Actor row={row} />
        <p className="break-all text-sm">
          ID de usuario: {row.user_id || "No informado"}
        </p>
        <p className="whitespace-pre-wrap break-words text-sm">
          {row.description || row.details || "Sin descripción informada"}
        </p>
      </section>
      <section className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/30 p-4">
        <SectionHeading
          icon={Terminal}
          title="Recurso y solicitud"
          tone="violet"
        />
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {Object.entries({
            Recurso: row.resource_type,
            "ID de recurso": row.resource_id,
            IP: row.ip_address,
            Método: row.request_method,
            Ruta: row.request_path,
            "Código HTTP": row.status_code,
            "Agente de usuario": row.user_agent,
            "Resumen de cambios": row.changes_summary,
            Error: row.error_message,
          }).map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="font-semibold">{key}</dt>
              <dd className="whitespace-pre-wrap break-all text-slate-600">
                {value ?? "No informado"}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      {row.contains_personal_data && (
        <OperationNotice tone="warning">
          El evento está marcado como contenido con datos personales.
        </OperationNotice>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(
          [
            ["Valores anteriores", row.old_values],
            ["Valores nuevos", row.new_values],
          ] as const
        ).map(([title, values]) => (
          <section
            key={title}
            className="min-w-0 space-y-2 rounded-xl border border-amber-200 bg-amber-50/30 p-4"
          >
            <h3 className="font-semibold">{title}</h3>
            {values == null ? (
              <p className="text-sm text-slate-600">No informados</p>
            ) : (
              <pre
                className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs"
                tabIndex={0}
                aria-label={title}
              >
                {JSON.stringify(values, null, 2)}
              </pre>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
