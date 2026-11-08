"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Filter,
  ListFilter,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  Search,
  Truck,
} from "lucide-react";
import {
  OperationEmpty,
  OperationMetric,
  OperationNotice,
  OperationPill,
  OperationsHeader,
  SectionHeading,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import { useDeliveryCatalog } from "@/hooks/useDeliveryCatalog";
import {
  DELIVERY_STATES,
  deliveryDuration,
  firstDeliveryQuery,
  prepareDeliveryQuery,
  type DeliveryQuery,
} from "@/lib/delivery-catalog";

export default function ManagerDeliveriesPage() {
  return (
    <ManagerPageBoundary scope="delivery-catalog">
      <DeliveryCatalog />
    </ManagerPageBoundary>
  );
}
const statusNames: Record<string, string> = {
  ALL: "Todos los estados",
  PENDIENTE: "Pendiente",
  INICIADA: "Iniciada",
  EN_PICKUP: "En recogida",
  EN_ROUTE: "En ruta",
  EN_DESTINO: "En destino",
  COMPLETADA: "Completada",
  FALLIDA: "Fallida",
  CANCELADA: "Cancelada",
};
const assignmentNames = {
  ALL: "Todas",
  assigned: "Con repartidor",
  unassigned: "Sin asignar",
};
const statusTones: Record<string, OperationTone> = {
  PENDIENTE: "amber",
  INICIADA: "blue",
  EN_PICKUP: "violet",
  EN_ROUTE: "blue",
  EN_DESTINO: "violet",
  COMPLETADA: "emerald",
  FALLIDA: "rose",
  CANCELADA: "slate",
};
function DeliveryCatalog() {
  const catalog = useDeliveryCatalog();
  const [draft, setDraft] = useState<DeliveryQuery>(firstDeliveryQuery),
    [formError, setFormError] = useState<string | null>(null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    try {
      const query = prepareDeliveryQuery({ ...draft, offset: 0 });
      setFormError(null);
      void catalog.load(query);
    } catch {
      setFormError(
        "Comprueba los filtros: el ID debe ser UUID y no se combina con Sin asignar.",
      );
    }
  };
  const snapshot = catalog.data,
    confirmed = snapshot?.query;
  const inputStyle = operationStyles.field;
  const buttonStyle = operationStyles.button;
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        title="Entregas registradas"
        icon={Truck}
        description={
          <p>
            Consulta paginada de entregas reales. Las asignaciones sin entrega
            se consultan en órdenes.
          </p>
        }
        actions={
          <button
            className={buttonStyle}
            disabled={catalog.isLoading}
            onClick={() => void catalog.refresh()}
          >
            <RefreshCw
              aria-hidden="true"
              className={`h-4 w-4 ${catalog.isLoading ? "animate-spin motion-reduce:animate-none" : ""}`}
            />
            Actualizar consulta
          </button>
        }
      />
      <form
        onSubmit={submit}
        className={`${operationStyles.panel} grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4`}
        aria-label="Filtros de entregas"
      >
        <div className="sm:col-span-2 lg:col-span-4">
          <SectionHeading
            icon={ListFilter}
            title="Filtros de búsqueda"
            description="Los cambios se aplican al pulsar Aplicar filtros. La consulta confirmada identifica los datos visibles."
          />
        </div>
        <label className="space-y-2 text-sm font-medium text-slate-700">
          Estado en el servidor
          <select
            className={inputStyle}
            value={draft.status}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
          >
            <option value="ALL">Todos los estados</option>
            {DELIVERY_STATES.map((status) => (
              <option key={status} value={status}>
                {statusNames[status]}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-2 text-sm font-medium text-slate-700">
          Asignación en el servidor
          <select
            className={inputStyle}
            value={draft.assignment}
            onChange={(e) =>
              setDraft({
                ...draft,
                assignment: e.target.value as DeliveryQuery["assignment"],
                rider: e.target.value === "unassigned" ? "" : draft.rider,
              })
            }
          >
            <option value="ALL">Todas</option>
            <option value="assigned">Con repartidor</option>
            <option value="unassigned">Sin asignar</option>
          </select>
        </label>
        <label className="space-y-2 text-sm font-medium text-slate-700">
          ID repartidor (opcional)
          <input
            className={inputStyle}
            disabled={draft.assignment === "unassigned"}
            value={draft.rider}
            onChange={(e) => setDraft({ ...draft, rider: e.target.value })}
          />
        </label>
        <label className="space-y-2 text-sm font-medium text-slate-700">
          Filas por página
          <select
            className={inputStyle}
            value={draft.limit}
            onChange={(e) =>
              setDraft({ ...draft, limit: Number(e.target.value) })
            }
          >
            {[20, 50, 100].map((size) => (
              <option key={size}>{size}</option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 sm:col-span-2 lg:col-span-4">
          <button className={operationStyles.primaryButton} type="submit">
            <Filter aria-hidden="true" className="h-4 w-4" />
            Aplicar filtros
          </button>
          <button
            className={buttonStyle}
            type="button"
            onClick={() => {
              setDraft(firstDeliveryQuery);
              setFormError(null);
              void catalog.load(firstDeliveryQuery);
            }}
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            Restablecer filtros
          </button>
        </div>
      </form>
      {formError && (
        <OperationNotice role="alert" tone="error">
          {formError}
        </OperationNotice>
      )}
      {catalog.error && (
        <OperationNotice role="alert" tone="warning">
          <p>{catalog.error}</p>
          <button
            className={buttonStyle}
            disabled={catalog.isLoading}
            onClick={() => void catalog.retry()}
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            Reintentar consulta
          </button>
        </OperationNotice>
      )}
      {catalog.isLoading && (
        <OperationNotice role="status">
          Cargando consulta de entregas…
        </OperationNotice>
      )}
      {snapshot && confirmed && (
        <>
          <section
            aria-label="Consulta de entregas confirmada"
            aria-busy={catalog.isLoading}
            className="space-y-4"
          >
            <OperationNotice>
              <p className="font-semibold">
                Consulta confirmada: estado {statusNames[confirmed.status]};
                asignación {assignmentNames[confirmed.assignment]}; repartidor{" "}
                {confirmed.rider || "Todos"}.
              </p>
              <p>
                Total de la consulta: {snapshot.total}. Página{" "}
                {confirmed.offset / confirmed.limit + 1}: {snapshot.rows.length}{" "}
                registros; {catalog.rows.length} coincidencias locales.
              </p>
            </OperationNotice>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <OperationMetric
                label="Entregas de la consulta"
                value={snapshot.total}
                icon={PackageCheck}
              />
              <OperationMetric
                label="Registros en esta página"
                value={snapshot.rows.length}
                icon={Truck}
                tone="violet"
              />
              <OperationMetric
                label="Coincidencias en esta página"
                value={catalog.rows.length}
                icon={Search}
                tone="emerald"
              />
            </div>
          </section>
          <label className="block space-y-2 text-sm font-medium text-slate-700">
            <span className="flex items-center gap-2">
              <Search aria-hidden="true" className="h-4 w-4 text-blue-600" />
              Buscar solo en esta página
            </span>
            <input
              className={inputStyle}
              value={catalog.search}
              onChange={(e) => catalog.setSearch(e.target.value)}
              placeholder="Referencia, entrega, orden, cliente o repartidor"
            />
          </label>
          {snapshot.rows.length === 0 ? (
            <OperationEmpty>
              No hay entregas en esta página de la consulta.
            </OperationEmpty>
          ) : catalog.rows.length === 0 ? (
            <OperationEmpty>
              Sin coincidencias en esta página. La búsqueda no consulta otras
              páginas.
            </OperationEmpty>
          ) : (
            <div
              className={`${operationStyles.panel} overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600`}
              tabIndex={0}
              role="region"
              aria-label="Tabla de entregas, desplazamiento horizontal"
            >
              <table className="w-full min-w-[900px] text-left text-sm">
                <caption className="sr-only">
                  Entregas de la página confirmada
                </caption>
                <thead className={operationStyles.tableHead}>
                  <tr>
                    {[
                      "Referencia y entrega",
                      "Orden y cliente",
                      "Repartidor",
                      "Estado",
                      "Duración",
                      "SLA",
                      "Detalle",
                    ].map((label) => (
                      <th scope="col" key={label} className="p-3">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {catalog.rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-t border-slate-100 transition-colors hover:bg-blue-50/50"
                      aria-label={`Entrega ${row.id}`}
                    >
                      <td className="p-3">
                        <p className="font-semibold text-slate-900">
                          {row.reference || "Referencia no informada"}
                        </p>
                        <p className="mt-1 max-w-xs break-all font-mono text-xs text-slate-500">
                          ID entrega: {row.id}
                        </p>
                      </td>
                      <td className="p-3">
                        <p className="font-medium">
                          {row.customer || "Cliente no informado"}
                        </p>
                        <p className="mt-1 max-w-xs break-all font-mono text-xs text-slate-500">
                          ID orden: {row.order}
                        </p>
                      </td>
                      <td className="p-3">
                        <p>
                          {row.riderId
                            ? row.riderName || "Nombre no informado"
                            : "Sin asignar"}
                        </p>
                        {row.riderId && (
                          <p className="mt-1 max-w-xs break-all font-mono text-xs text-slate-500">
                            {row.riderId}
                          </p>
                        )}
                      </td>
                      <td className="p-3">
                        <OperationPill
                          tone={statusTones[row.status ?? ""] ?? "slate"}
                        >
                          {row.status
                            ? (statusNames[row.status] ?? row.status)
                            : "Estado no informado"}
                        </OperationPill>
                      </td>
                      <td className="p-3">{deliveryDuration(row)}</td>
                      <td className="p-3">
                        <OperationPill
                          tone={
                            row.sla === null
                              ? "slate"
                              : row.sla
                                ? "emerald"
                                : "rose"
                          }
                        >
                          {row.sla === null
                            ? "SLA no informado"
                            : row.sla
                              ? "Cumple SLA"
                              : "Fuera de SLA"}
                        </OperationPill>
                      </td>
                      <td className="p-3">
                        <Link
                          className={`${operationStyles.link} whitespace-nowrap`}
                          href={`/manager/operations/orders/${encodeURIComponent(row.order)}`}
                          aria-label={`Ver orden de entrega ${row.id}`}
                        >
                          Ver orden
                          <ArrowRight aria-hidden="true" className="h-4 w-4" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <nav
            aria-label="Páginas de entregas"
            className={`${operationStyles.panel} flex flex-wrap gap-3 p-4`}
          >
            <button
              className={buttonStyle}
              disabled={catalog.isLoading || confirmed.offset === 0}
              onClick={() => catalog.navigate(-1)}
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Anterior
            </button>
            <button
              className={buttonStyle}
              disabled={
                catalog.isLoading ||
                confirmed.offset + confirmed.limit >= snapshot.total
              }
              onClick={() => catalog.navigate(1)}
            >
              Siguiente
              <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </button>
            <button
              className={buttonStyle}
              disabled={catalog.isLoading || confirmed.offset === 0}
              onClick={() => void catalog.first()}
            >
              <RotateCcw aria-hidden="true" className="h-4 w-4" />
              Volver al inicio
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
