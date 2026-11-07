'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import type { ReactNode } from 'react';
import { RiderAuditAccess } from '@/components/audit/RiderAuditAccess';
import { useRiderAudit } from '@/hooks/useRiderAudit';
import { AUDIT_PAGE_SIZE, type AuditPage } from '@/lib/rider-audit-contract';
import { transactionDateLabel } from '@/lib/transaction-contract';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function RiderAuditDetailPage() {
  const params = useParams(), id = typeof params.id === 'string' ? params.id : '';
  return <RiderAuditAccess riderId={id}><Detail riderId={id} /></RiderAuditAccess>;
}
function Detail({ riderId }: { riderId: string }) {
  const page = useRiderAudit(riderId), data = page.data, summary = data?.summary.row;
  return <div className="p-4 md:p-6 bg-gray-50 min-h-screen"><div className="max-w-7xl mx-auto space-y-5">
    <div className="flex flex-wrap justify-between items-start gap-3">
      <div className="min-w-0"><h1 className="text-2xl font-bold">Detalle de auditoría de repartidor</h1><p className="font-mono text-sm break-all">ID solicitado: {riderId || 'No informado'}</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { void page.refresh(); }}>Actualizar auditoría</Button><Button variant="outline" disabled={page.isLoading} onClick={() => { void page.first(); }}>Volver al inicio</Button></div>
    </div>
    <Link className="inline-block text-blue-700 underline" href="/manager/operations/rider-audit">Volver al catálogo de auditoría</Link>
    {page.isLoading && <p role="status">Consultando el conjunto de auditoría…</p>}
    {page.error && <div role="alert" className="rounded border bg-red-50 p-4 text-red-800 space-y-2"><p>{page.error}</p><Button variant="outline" disabled={page.isLoading} onClick={() => { void page.retry(); }}>Reintentar auditoría</Button></div>}
    {data && <section aria-label="Auditoría confirmada" aria-busy={page.isLoading} className="space-y-5">
      <div className="rounded border bg-white p-4 space-y-2 text-sm"><p className="font-mono break-all">Repartidor de la consulta confirmada: {data.riderId}</p><p>Órdenes, entregas y transacciones se confirman juntas en esta pantalla. Son lecturas independientes del servidor; pueden cambiar entre consultas.</p><p>Cada tabla muestra hasta 50 filas por página. Sus cantidades corresponden a la página cargada y no al historial completo.</p></div>
      <Card><CardHeader><CardTitle>Resumen agregado informado por el servidor</CardTitle></CardHeader><CardContent>
        {summary ? <div className="space-y-4">
          <p className="font-semibold break-all">{summary.full_name ?? 'Nombre no informado'}</p><p className="break-all">{summary.email ?? 'Email no informado'}</p>
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">{[
            ['Estado registrado', summary.status ?? 'No informado'], ['Disponibilidad informada', summary.is_online === null ? 'No informada' : summary.is_online ? 'Online' : 'Offline'],
            ['Órdenes asignadas (acumulado)', summary.orders_assigned], ['Órdenes entregadas (acumulado)', summary.orders_delivered], ['Órdenes activas (agregado)', summary.orders_active],
            ['Entregas reales (acumulado)', summary.deliveries_total], ['Entregas completadas (acumulado)', summary.deliveries_completed], ['Entregas fallidas (acumulado)', summary.deliveries_failed],
            ['SLA informado', summary.deliveries_total ? `${summary.sla_compliance_rate}% · ${summary.sla_compliant}/${summary.deliveries_total} entregas` : 'Sin entregas en el denominador'],
            ['Créditos PROCESADO (acumulado)', payoutAmountLabel(summary.total_earned, summary.currency ?? undefined)], ['Retiros PENDIENTE (agregado)', payoutAmountLabel(summary.pending_payouts, summary.currency ?? undefined)],
            ['Última ubicación informada', summary.last_lat !== null && summary.last_lng !== null ? `${summary.last_lat}, ${summary.last_lng}` : 'No informada'],
            ['Fecha de ubicación informada', transactionDateLabel(summary.last_location_at)],
          ].map(([label, value]) => <div key={label} className="rounded border p-3 min-w-0"><dt className="text-sm text-gray-600">{label}</dt><dd className="font-semibold break-words">{value}</dd></div>)}</dl>
          <p className="text-xs text-gray-600">Los agregados no se calculan desde estas páginas. Créditos procesados y retiros pendientes tienen criterios distintos; no acreditan una transferencia bancaria ni un saldo disponible para retirar.</p>
        </div> : <p role="status">Resumen no localizado en {data.summary.scanned} registros consultados{data.summary.limitReached ? ' (límite de búsqueda de 500 alcanzado)' : ''}. Esto no confirma que el repartidor no exista. Las tablas corresponden al ID solicitado.</p>}
      </CardContent></Card>
      <Panel title="Órdenes del repartidor" page={data.orders} loading={page.isLoading} navigate={direction => page.navigate('orders', direction)}>
        <table className="w-full text-sm"><caption className="text-left p-3">Órdenes de la página confirmada; fechas UTC</caption><thead><tr><Th>ID / referencia</Th><Th>Cliente</Th><Th>Estado</Th><Th>Importe informado</Th><Th>Creación registrada</Th><Th>Detalle</Th></tr></thead><tbody>{data.orders.rows.map(row => <tr key={row.id} className="border-t"><Td><p className="font-mono break-all">{row.id}</p><p>{row.external_id ?? 'Referencia no informada'}</p></Td><Td>{row.customer_name ?? 'No informado'}</Td><Td>{row.status}</Td><Td>{payoutAmountLabel(row.amount, row.currency ?? undefined)}</Td><Td>{transactionDateLabel(row.created_at)}</Td><Td><Link className="text-blue-700 underline" aria-label={`Ver orden ${row.id}`} href={`/manager/operations/orders/${encodeURIComponent(row.id)}`}>Ver orden</Link></Td></tr>)}</tbody></table>
      </Panel>
      <Panel title="Entregas registradas del repartidor" page={data.deliveries} loading={page.isLoading} navigate={direction => page.navigate('deliveries', direction)}>
        <table className="w-full text-sm"><caption className="text-left p-3">Solo registros de entregas; fechas UTC</caption><thead><tr><Th>ID de entrega</Th><Th>ID de orden</Th><Th>Cliente</Th><Th>Estado</Th><Th>Bono congelado informado</Th><Th>Actualización registrada</Th></tr></thead><tbody>{data.deliveries.rows.map(row => <tr key={row.id} className="border-t"><Td><p className="font-mono break-all">{row.id}</p></Td><Td><Link className="text-blue-700 underline break-all" aria-label={`Ver orden de entrega ${row.id}`} href={`/manager/operations/orders/${encodeURIComponent(row.order_id)}`}>{row.order_id}</Link></Td><Td>{row.customer_name ?? 'No informado'}</Td><Td>{row.status}</Td><Td>{payoutAmountLabel(row.locked_bonus_amount, row.currency ?? undefined)}</Td><Td>{transactionDateLabel(row.updated_at)}</Td></tr>)}</tbody></table>
      </Panel>
      <Card><CardHeader><CardTitle>Órdenes sin registro de entrega</CardTitle></CardHeader><CardContent className="space-y-3">
        <p className="text-sm text-gray-600">El servidor añade hasta 50 órdenes de apoyo solo en la primera página de entregas. Su estado es derivado de la orden; no son entregas registradas ni se cuentan como completadas.</p>
        {data.deliveries.offset > 0 ? <p>Vuelve al inicio para consultar este bloque.</p> : !data.deliveries.fallback.length ? <p>El servidor no informó órdenes de apoyo en esta lectura.</p> : <><p>{data.deliveries.fallback.length} órdenes de apoyo cargadas; alcance acotado, sin total global.</p><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><Th>ID de orden</Th><Th>Estado derivado</Th></tr></thead><tbody>{data.deliveries.fallback.map(row => <tr key={row.id} className="border-t"><Td><Link className="text-blue-700 underline break-all" aria-label={`Ver orden de apoyo ${row.order_id}`} href={`/manager/operations/orders/${encodeURIComponent(row.order_id)}`}>{row.order_id}</Link></Td><Td>{row.status}</Td></tr>)}</tbody></table></div></>}
      </CardContent></Card>
      <Panel title="Transacciones del repartidor" page={data.transactions} loading={page.isLoading} navigate={direction => page.navigate('transactions', direction)}>
        <table className="w-full text-sm"><caption className="text-left p-3">Registros contables de la página; signo almacenado y fechas UTC</caption><thead><tr><Th>ID / referencia</Th><Th>Tipo / estado</Th><Th>Importe registrado</Th><Th>Saldo posterior informado</Th><Th>Creación registrada</Th><Th>Detalle</Th></tr></thead><tbody>{data.transactions.rows.map(row => <tr key={row.id} className="border-t"><Td><p className="font-mono break-all">{row.id}</p><p>{row.reference_id ?? row.description ?? 'Referencia no informada'}</p></Td><Td>{row.type}<p>{row.status}</p></Td><Td>{payoutAmountLabel(row.amount, row.currency ?? undefined)}</Td><Td>{payoutAmountLabel(row.balance_after, row.currency ?? undefined)}</Td><Td>{transactionDateLabel(row.created_at)}</Td><Td><Link className="text-blue-700 underline" aria-label={`Ver transacción ${row.id}`} href={`/manager/financial/transactions/${encodeURIComponent(row.id)}`}>Ver transacción</Link></Td></tr>)}</tbody></table>
      </Panel>
      <p className="text-xs text-gray-600">Las páginas usan desplazamientos. Cambios concurrentes pueden mover filas; si falla la navegación, vuelve al inicio. No se informa un total global de estas tablas ni se suman monedas desconocidas.</p>
    </section>}
  </div></div>;
}
function Panel({ title, page, loading, navigate, children }: { title: string; page: AuditPage<{ id: string }>; loading: boolean; navigate: (direction: -1 | 1) => unknown; children: ReactNode }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-3"><section aria-label={title} aria-busy={loading}><p className="text-sm text-gray-600 mb-3">{page.rows.length} filas cargadas en la página {page.offset / AUDIT_PAGE_SIZE + 1}.</p><div className="overflow-x-auto">{page.rows.length ? children : <p>No hay registros en esta página confirmada.</p>}</div><nav aria-label={`Páginas de ${title}`} className="flex flex-wrap items-center gap-3 mt-4"><Button variant="outline" disabled={loading || page.offset === 0} onClick={() => { void navigate(-1); }}>Anterior</Button><span>Página {page.offset / AUDIT_PAGE_SIZE + 1}</span><Button variant="outline" disabled={loading || !page.hasNext} onClick={() => { void navigate(1); }}>Siguiente</Button></nav></section></CardContent></Card>;
}
function Th({ children }: { children: ReactNode }) { return <th className="p-3 text-left">{children}</th>; }
function Td({ children }: { children: ReactNode }) { return <td className="p-3 align-top">{children}</td>; }
