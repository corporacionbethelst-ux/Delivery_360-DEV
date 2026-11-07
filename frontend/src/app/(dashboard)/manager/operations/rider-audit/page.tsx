'use client';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { RiderAuditAccess } from '@/components/audit/RiderAuditAccess';
import { useRiderAuditCatalog } from '@/hooks/useRiderAuditCatalog';
import { AUDIT_PAGE_SIZE, RIDER_AUDIT_STATUSES } from '@/lib/rider-audit-contract';
import { auditCatalogMetrics, auditOnlineLabel } from '@/lib/rider-audit-catalog';
import { transactionDateLabel } from '@/lib/transaction-contract';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function RiderAuditPage() { return <RiderAuditAccess><Catalog /></RiderAuditAccess>; }
function Catalog() {
  const page = useRiderAuditCatalog(), data = page.data, metrics = auditCatalogMetrics(page.visibleRows);
  return <div className="p-4 md:p-6 bg-gray-50 min-h-screen"><div className="max-w-7xl mx-auto space-y-5">
    <div className="flex flex-wrap justify-between items-start gap-3">
      <div className="min-w-0"><h1 className="text-2xl font-bold">Auditoría por repartidor</h1><p className="text-gray-600">Resumen operativo y contable en páginas de hasta 50 repartidores.</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { void page.refresh(); }}>Actualizar consulta</Button><Button disabled={page.isLoading || !data || !!page.error || !page.visibleRows.length} onClick={page.exportPage}>Exportar página CSV</Button></div>
    </div>
    <Card><CardContent className="pt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="min-w-0"><label htmlFor="audit-search" className="block text-sm mb-1">Buscar solo en esta página</label><input id="audit-search" className="w-full min-w-0 rounded border p-2" placeholder="ID, nombre, email, teléfono, placa o zona" value={page.search} onChange={e => page.setSearch(e.target.value)} /></div>
      <div className="min-w-0"><label htmlFor="audit-status" className="block text-sm mb-1">Estado en el servidor</label><select id="audit-status" className="w-full min-w-0 rounded border p-2" value={page.selected.status} onChange={e => { void page.setFilter('status', e.target.value); }}><option value="ALL">Todos los estados</option>{RIDER_AUDIT_STATUSES.map(status => <option key={status} value={status}>{status}</option>)}</select></div>
      <div className="min-w-0"><label htmlFor="audit-online" className="block text-sm mb-1">Disponibilidad en el servidor</label><select id="audit-online" className="w-full min-w-0 rounded border p-2" value={page.selected.online} onChange={e => { void page.setFilter('online', e.target.value); }}><option value="ALL">Todos</option><option value="true">Online</option><option value="false">Offline</option></select></div>
    </CardContent></Card>
    {page.isLoading && <p role="status">Consultando auditoría…</p>}
    {page.error && <div role="alert" className="rounded border bg-red-50 p-4 text-red-800 space-y-2"><p>{page.error}</p><Button variant="outline" disabled={page.isLoading} onClick={() => { void page.retry(); }}>Reintentar consulta</Button></div>}
    {page.exportError && <p role="alert" className="rounded border bg-red-50 p-3 text-red-800">{page.exportError}</p>}
    {data && <section aria-label="Página de auditoría confirmada" aria-busy={page.isLoading} className="space-y-5">
      <div className="rounded border bg-white p-4 text-sm space-y-1"><p className="font-semibold">Consulta confirmada: estado {data.query.status}; disponibilidad {auditOnlineLabel(data.query.online)}.</p><p>Las métricas y el CSV solo abarcan las coincidencias de esta página. No se informa un total global de repartidores ni se suman importes de moneda desconocida.</p></div>
      <section aria-label="Métricas de las coincidencias de esta página" className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <Metric label="Filas cargadas en esta página" value={data.rows.length} /><Metric label="Coincidencias en esta página" value={page.visibleRows.length} />
        <Metric label="Online informado en las coincidencias" value={`${metrics.online} · ${metrics.unknownOnline} sin información`} /><Metric label="Órdenes activas de las coincidencias" value={metrics.activeOrders ?? 'Cantidad no calculable'} />
      </section>
      {!data.rows.length ? <p className="rounded border bg-white p-6">No hay repartidores en esta página de la consulta.</p> : !page.visibleRows.length ? <p className="rounded border bg-white p-6">Sin coincidencias en esta página. Puedes navegar o cambiar la búsqueda.</p> : <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {page.visibleRows.map(item => <Card key={item.rider_id} role="article" aria-label={`Auditoría de ${item.rider_id}`} className="min-w-0">
          <CardHeader><CardTitle className="break-words">{item.full_name ?? 'Nombre no informado'}</CardTitle><p className="text-sm break-all">{item.email ?? 'Email no informado'}</p><p className="text-sm font-mono break-all">ID rider: {item.rider_id}</p><p className="text-xs text-gray-600 font-mono break-all">ID usuario: {item.user_id}</p></CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3"><Field label="Estado registrado" value={item.status ?? 'No informado'} /><Field label="Disponibilidad informada" value={item.is_online === null ? 'No informada' : item.is_online ? 'Online' : 'Offline'} />
              <Field label="Órdenes asignadas (acumulado)" value={item.orders_assigned} /><Field label="Órdenes activas (agregado)" value={item.orders_active} /><Field label="Entregas reales (acumulado)" value={item.deliveries_total} /><Field label="Entregas completadas (acumulado)" value={item.deliveries_completed} /><Field label="Entregas fallidas (acumulado)" value={item.deliveries_failed} />
              <Field label="SLA informado" value={item.deliveries_total ? `${item.sla_compliance_rate}% · ${item.sla_compliant}/${item.deliveries_total} entregas` : 'Sin entregas en el denominador'} />
              <Field label="Créditos PROCESADO (acumulado)" value={payoutAmountLabel(item.total_earned, item.currency ?? undefined)} /><Field label="Retiros PENDIENTE (agregado)" value={payoutAmountLabel(item.pending_payouts, item.currency ?? undefined)} />
              <Field label="Tipo de vehículo" value={item.vehicle_type ?? 'No informado'} /><Field label="Placa" value={item.vehicle_plate ?? 'No informada'} /><Field label="Zona" value={item.operating_zone ?? 'No informada'} /><Field label="Teléfono" value={item.phone ?? 'No informado'} />
              <Field label="Última ubicación informada" value={item.last_lat !== null && item.last_lng !== null ? `${item.last_lat}, ${item.last_lng}` : 'No informada'} /><Field label="Fecha de ubicación informada" value={transactionDateLabel(item.last_location_at)} />
            </dl>
            <Link className="inline-block text-blue-700 underline" aria-label={`Ver auditoría de ${item.rider_id}`} href={`/manager/operations/rider-audit/${encodeURIComponent(item.rider_id)}`}>Ver detalle de auditoría</Link>
          </CardContent>
        </Card>)}
      </div>}
      <p className="text-xs text-gray-600">Cada tarjeta muestra agregados del servidor, con criterios distintos para créditos procesados y retiros pendientes. No son una confirmación bancaria ni un saldo disponible para retirar.</p>
    </section>}
    <nav aria-label="Páginas del catálogo de auditoría" className="flex flex-wrap items-center gap-3">
      <Button variant="outline" disabled={page.isLoading} onClick={() => { void page.first(); }}>Volver al inicio</Button><Button variant="outline" disabled={page.isLoading || !data || data.query.offset === 0} onClick={() => { void page.navigate(-1); }}>Anterior</Button>
      <span aria-live="polite">Página {(data?.query.offset ?? 0) / AUDIT_PAGE_SIZE + 1}</span><Button variant="outline" disabled={page.isLoading || !data?.hasNext} onClick={() => { void page.navigate(1); }}>Siguiente</Button>
    </nav>
    <p className="text-xs text-gray-600">La búsqueda y la exportación son de la página cargada. Los cambios de disponibilidad o nombre pueden mover filas entre páginas; si falla la navegación, vuelve al inicio.</p>
  </div></div>;
}
function Field({ label, value }: { label: string; value: ReactNode }) { return <div className="rounded border p-3 min-w-0"><dt className="text-xs text-gray-600">{label}</dt><dd className="font-semibold break-words">{value}</dd></div>; }
function Metric({ label, value }: { label: string; value: ReactNode }) { return <Card><CardContent className="p-4"><p className="text-sm text-gray-600">{label}</p><p className="text-lg font-bold">{value}</p></CardContent></Card>; }
