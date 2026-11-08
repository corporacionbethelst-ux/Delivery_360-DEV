"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { RiderAuditAccess } from "@/components/audit/RiderAuditAccess";
import { useRiderAuditCatalog } from "@/hooks/useRiderAuditCatalog";
import {
  AUDIT_PAGE_SIZE,
  RIDER_AUDIT_STATUSES,
} from "@/lib/rider-audit-contract";
import {
  auditCatalogMetrics,
  auditOnlineLabel,
} from "@/lib/rider-audit-catalog";
import { transactionDateLabel } from "@/lib/transaction-contract";
import { payoutAmountLabel } from "@/lib/payout-contract";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ArrowLeft,
  ArrowRight,
  ClipboardCheck,
  Download,
  ListFilter,
  ListOrdered,
  Package,
  Radio,
  RefreshCw,
  RotateCcw,
  Search,
  UserRound,
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

const riderStatusTones: Record<string, OperationTone> = {
  ACTIVO: "blue",
  INACTIVO: "slate",
  OCUPADO: "violet",
  PENDIENTE: "amber",
  SUSPENDIDO: "amber",
};

export default function RiderAuditPage() {
  return (
    <RiderAuditAccess>
      <Catalog />
    </RiderAuditAccess>
  );
}
function Catalog() {
  const page = useRiderAuditCatalog(),
    data = page.data,
    metrics = auditCatalogMetrics(page.visibleRows);
  return (
    <div className={operationStyles.page}>
      <OperationsHeader
        audit
        icon={ClipboardCheck}
        title="Auditoría por repartidor"
        description="Resumen operativo y contable en páginas de hasta 50 repartidores."
        actions={
          <>
            <Button
              className={operationStyles.button}
              variant="outline"
              onClick={() => {
                void page.refresh();
              }}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-4 w-4 ${page.isLoading ? "animate-spin motion-reduce:animate-none" : ""}`}
              />
              Actualizar consulta
            </Button>
            <Button
              className={operationStyles.primaryButton}
              disabled={
                page.isLoading ||
                !data ||
                !!page.error ||
                !page.visibleRows.length
              }
              onClick={page.exportPage}
            >
              <Download aria-hidden="true" className="h-4 w-4" />
              Exportar página CSV
            </Button>
          </>
        }
      />
      <Card className={operationStyles.panel}>
        <CardHeader className="pb-4">
          <SectionHeading
            icon={ListFilter}
            title="Buscar y filtrar repartidores"
            tone="violet"
            description="Combina los filtros de la consulta y busca entre las filas de la página cargada."
          />
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="min-w-0">
            <label
              htmlFor="audit-search"
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Buscar solo en esta página
            </label>
            <input
              id="audit-search"
              className={operationStyles.field}
              placeholder="ID, nombre, email, teléfono, placa o zona"
              value={page.search}
              onChange={(e) => page.setSearch(e.target.value)}
            />
          </div>
          <div className="min-w-0">
            <label
              htmlFor="audit-status"
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Estado en el servidor
            </label>
            <select
              id="audit-status"
              className={operationStyles.field}
              value={page.selected.status}
              onChange={(e) => {
                void page.setFilter("status", e.target.value);
              }}
            >
              <option value="ALL">Todos los estados</option>
              {RIDER_AUDIT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <label
              htmlFor="audit-online"
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Disponibilidad en el servidor
            </label>
            <select
              id="audit-online"
              className={operationStyles.field}
              value={page.selected.online}
              onChange={(e) => {
                void page.setFilter("online", e.target.value);
              }}
            >
              <option value="ALL">Todos</option>
              <option value="true">Online</option>
              <option value="false">Offline</option>
            </select>
          </div>
        </CardContent>
      </Card>
      {page.isLoading && (
        <OperationNotice role="status">Consultando auditoría…</OperationNotice>
      )}
      {page.error && (
        <OperationNotice role="alert" tone="warning">
          <p>{page.error}</p>
          <Button
            className={operationStyles.button}
            variant="outline"
            disabled={page.isLoading}
            onClick={() => {
              void page.retry();
            }}
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            Reintentar consulta
          </Button>
        </OperationNotice>
      )}
      {page.exportError && (
        <OperationNotice role="alert" tone="error">
          {page.exportError}
        </OperationNotice>
      )}
      {data && (
        <section
          aria-label="Página de auditoría confirmada"
          aria-busy={page.isLoading}
          className="space-y-5"
        >
          <OperationNotice>
            <p className="font-semibold">
              Consulta confirmada: estado {data.query.status}; disponibilidad{" "}
              {auditOnlineLabel(data.query.online)}.
            </p>
            <p>
              Las métricas y el CSV solo abarcan las coincidencias de esta
              página. No se informa un total global de repartidores ni se suman
              importes de moneda desconocida.
            </p>
          </OperationNotice>
          <section
            aria-label="Métricas de las coincidencias de esta página"
            className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3"
          >
            <OperationMetric
              label="Filas cargadas en esta página"
              value={data.rows.length}
              icon={ListOrdered}
              tone="violet"
            />
            <OperationMetric
              label="Coincidencias en esta página"
              value={page.visibleRows.length}
              icon={Search}
            />
            <OperationMetric
              label="Online informado en las coincidencias"
              value={`${metrics.online} · ${metrics.unknownOnline} sin información`}
              icon={Radio}
              tone="emerald"
            />
            <OperationMetric
              label="Órdenes activas de las coincidencias"
              value={metrics.activeOrders ?? "Cantidad no calculable"}
              icon={Package}
              tone="amber"
            />
          </section>
          {!data.rows.length ? (
            <OperationEmpty>
              No hay repartidores en esta página de la consulta.
            </OperationEmpty>
          ) : !page.visibleRows.length ? (
            <OperationEmpty>
              Sin coincidencias en esta página. Puedes navegar o cambiar la
              búsqueda.
            </OperationEmpty>
          ) : (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {page.visibleRows.map((item) => (
                <Card
                  key={item.rider_id}
                  role="article"
                  aria-label={`Auditoría de ${item.rider_id}`}
                  className={`${operationStyles.panel} min-w-0 overflow-hidden transition-shadow hover:shadow-md`}
                >
                  <CardHeader className="border-b border-slate-100 bg-gradient-to-br from-violet-50/80 via-white to-blue-50/60">
                    <span className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl border border-violet-200 bg-white text-violet-700">
                      <UserRound aria-hidden="true" className="h-5 w-5" />
                    </span>
                    <CardTitle className="break-words text-lg leading-snug text-slate-900">
                      {item.full_name ?? "Nombre no informado"}
                    </CardTitle>
                    <p className="text-sm break-all">
                      {item.email ?? "Email no informado"}
                    </p>
                    <p className="text-sm font-mono break-all">
                      ID rider: {item.rider_id}
                    </p>
                    <p className="text-xs text-gray-600 font-mono break-all">
                      ID usuario: {item.user_id}
                    </p>
                  </CardHeader>
                  <CardContent className="space-y-4 pt-5">
                    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <Field
                        label="Estado registrado"
                        value={
                          <OperationPill
                            tone={
                              riderStatusTones[item.status ?? ""] ?? "slate"
                            }
                          >
                            {item.status ?? "No informado"}
                          </OperationPill>
                        }
                      />
                      <Field
                        label="Disponibilidad informada"
                        value={
                          <OperationPill
                            tone={
                              item.is_online === null
                                ? "slate"
                                : item.is_online
                                  ? "emerald"
                                  : "slate"
                            }
                          >
                            {item.is_online === null
                              ? "No informada"
                              : item.is_online
                                ? "Online"
                                : "Offline"}
                          </OperationPill>
                        }
                      />
                      <Field
                        label="Órdenes asignadas (acumulado)"
                        value={item.orders_assigned}
                      />
                      <Field
                        label="Órdenes activas (agregado)"
                        value={item.orders_active}
                      />
                      <Field
                        label="Entregas reales (acumulado)"
                        value={item.deliveries_total}
                      />
                      <Field
                        label="Entregas completadas (acumulado)"
                        value={item.deliveries_completed}
                      />
                      <Field
                        label="Entregas fallidas (acumulado)"
                        value={item.deliveries_failed}
                      />
                      <Field
                        label="SLA informado"
                        value={
                          item.deliveries_total
                            ? `${item.sla_compliance_rate}% · ${item.sla_compliant}/${item.deliveries_total} entregas`
                            : "Sin entregas en el denominador"
                        }
                      />
                      <Field
                        label="Créditos PROCESADO (acumulado)"
                        value={payoutAmountLabel(
                          item.total_earned,
                          item.currency ?? undefined,
                        )}
                      />
                      <Field
                        label="Retiros PENDIENTE (agregado)"
                        value={payoutAmountLabel(
                          item.pending_payouts,
                          item.currency ?? undefined,
                        )}
                      />
                      <Field
                        label="Tipo de vehículo"
                        value={item.vehicle_type ?? "No informado"}
                      />
                      <Field
                        label="Placa"
                        value={item.vehicle_plate ?? "No informada"}
                      />
                      <Field
                        label="Zona"
                        value={item.operating_zone ?? "No informada"}
                      />
                      <Field
                        label="Teléfono"
                        value={item.phone ?? "No informado"}
                      />
                      <Field
                        label="Última ubicación informada"
                        value={
                          item.last_lat !== null && item.last_lng !== null
                            ? `${item.last_lat}, ${item.last_lng}`
                            : "No informada"
                        }
                      />
                      <Field
                        label="Fecha de ubicación informada"
                        value={transactionDateLabel(item.last_location_at)}
                      />
                    </dl>
                    <Link
                      className={`${operationStyles.link} w-full justify-center border border-blue-100 bg-blue-50 px-4 py-3 no-underline hover:bg-blue-100`}
                      aria-label={`Ver auditoría de ${item.rider_id}`}
                      href={`/manager/operations/rider-audit/${encodeURIComponent(item.rider_id)}`}
                    >
                      Ver detalle de auditoría
                      <ArrowRight aria-hidden="true" className="h-4 w-4" />
                    </Link>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
          <p className="text-xs text-gray-600">
            Cada tarjeta muestra agregados del servidor, con criterios distintos
            para créditos procesados y retiros pendientes. No son una
            confirmación bancaria ni un saldo disponible para retirar.
          </p>
        </section>
      )}
      <nav
        aria-label="Páginas del catálogo de auditoría"
        className={`${operationStyles.panel} flex flex-wrap items-center gap-3 p-4`}
      >
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={page.isLoading}
          onClick={() => {
            void page.first();
          }}
        >
          <RotateCcw aria-hidden="true" className="h-4 w-4" />
          Volver al inicio
        </Button>
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={page.isLoading || !data || data.query.offset === 0}
          onClick={() => {
            void page.navigate(-1);
          }}
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          Anterior
        </Button>
        <span aria-live="polite">
          Página {(data?.query.offset ?? 0) / AUDIT_PAGE_SIZE + 1}
        </span>
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={page.isLoading || !data?.hasNext}
          onClick={() => {
            void page.navigate(1);
          }}
        >
          Siguiente
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Button>
      </nav>
      <p className="text-xs text-gray-600">
        La búsqueda y la exportación son de la página cargada. Los cambios de
        disponibilidad o nombre pueden mover filas entre páginas; si falla la
        navegación, vuelve al inicio.
      </p>
    </div>
  );
}
function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-3">
      <dt className="text-xs leading-relaxed text-slate-600">{label}</dt>
      <dd className="mt-1 break-words text-sm font-semibold text-slate-900">
        {value}
      </dd>
    </div>
  );
}
