"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
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
  const inputStyle =
    "rounded border border-slate-300 bg-white px-3 py-2 text-sm w-full";
  const buttonStyle = "rounded border px-3 py-2 text-sm disabled:opacity-50";
  return (
    <main className="space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Entregas registradas</h1>
          <p className="text-slate-600">
            Consulta paginada de entregas reales. Las asignaciones sin entrega
            se consultan en órdenes.
          </p>
        </div>
        <button
          className={buttonStyle}
          disabled={catalog.isLoading}
          onClick={() => void catalog.refresh()}
        >
          Actualizar consulta
        </button>
      </header>
      <form
        onSubmit={submit}
        className="grid gap-3 rounded-lg border bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
        aria-label="Filtros de entregas"
      >
        <p className="sm:col-span-2 lg:col-span-4 text-sm text-slate-600">
          Los cambios se aplican al pulsar Aplicar filtros. La consulta
          confirmada identifica los datos visibles.
        </p>
        <label>
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
        <label>
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
        <label>
          ID repartidor (opcional)
          <input
            className={inputStyle}
            disabled={draft.assignment === "unassigned"}
            value={draft.rider}
            onChange={(e) => setDraft({ ...draft, rider: e.target.value })}
          />
        </label>
        <label>
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
        <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
          <button className={buttonStyle} type="submit">
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
            Restablecer filtros
          </button>
        </div>
      </form>
      {formError && (
        <p role="alert" className="rounded border border-red-300 p-3">
          {formError}
        </p>
      )}
      {catalog.error && (
        <div
          role="alert"
          className="space-y-2 rounded border border-amber-400 p-3"
        >
          <p>{catalog.error}</p>
          <button
            className={buttonStyle}
            disabled={catalog.isLoading}
            onClick={() => void catalog.retry()}
          >
            Reintentar consulta
          </button>
        </div>
      )}
      {catalog.isLoading && <p role="status">Cargando consulta de entregas…</p>}
      {snapshot && confirmed && (
        <>
          <section
            aria-label="Consulta de entregas confirmada"
            className="rounded border bg-white p-4"
          >
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
          </section>
          <label className="block">
            Buscar solo en esta página
            <input
              className={inputStyle}
              value={catalog.search}
              onChange={(e) => catalog.setSearch(e.target.value)}
              placeholder="Referencia, entrega, orden, cliente o repartidor"
            />
          </label>
          {snapshot.rows.length === 0 ? (
            <p>No hay entregas en esta página de la consulta.</p>
          ) : catalog.rows.length === 0 ? (
            <p>
              Sin coincidencias en esta página. La búsqueda no consulta otras
              páginas.
            </p>
          ) : (
            <div className="overflow-x-auto rounded border bg-white">
              <table className="w-full min-w-[900px] text-left text-sm">
                <caption className="sr-only">
                  Entregas de la página confirmada
                </caption>
                <thead>
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
                      <th key={label} className="p-3">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {catalog.rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-t"
                      aria-label={`Entrega ${row.id}`}
                    >
                      <td className="p-3">
                        <p>{row.reference || "Referencia no informada"}</p>
                        <p className="max-w-xs break-all text-xs">
                          ID entrega: {row.id}
                        </p>
                      </td>
                      <td className="p-3">
                        <p>{row.customer || "Cliente no informado"}</p>
                        <p className="max-w-xs break-all text-xs">
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
                          <p className="max-w-xs break-all text-xs">
                            {row.riderId}
                          </p>
                        )}
                      </td>
                      <td className="p-3">
                        {row.status
                          ? (statusNames[row.status] ?? row.status)
                          : "Estado no informado"}
                      </td>
                      <td className="p-3">{deliveryDuration(row)}</td>
                      <td className="p-3">
                        {row.sla === null
                          ? "SLA no informado"
                          : row.sla
                            ? "Cumple SLA"
                            : "Fuera de SLA"}
                      </td>
                      <td className="p-3">
                        <Link
                          className="text-blue-700 underline"
                          href={`/manager/operations/orders/${encodeURIComponent(row.order)}`}
                          aria-label={`Ver orden de entrega ${row.id}`}
                        >
                          Ver orden
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
            className="flex flex-wrap gap-3"
          >
            <button
              className={buttonStyle}
              disabled={catalog.isLoading || confirmed.offset === 0}
              onClick={() => catalog.navigate(-1)}
            >
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
            </button>
            <button
              className={buttonStyle}
              disabled={catalog.isLoading || confirmed.offset === 0}
              onClick={() => void catalog.first()}
            >
              Volver al inicio
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
