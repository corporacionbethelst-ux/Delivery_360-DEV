'use client';

import { useEffect, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { useFinancialReports } from '@/hooks/useFinancialReports';
import { REPORT_EXPORT_LIMIT, type ReportRange } from '@/lib/financial-report-contract';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';

function rangeLabel(range: ReportRange) {
  return `${range.date_from ?? 'sin límite inicial'} → ${range.date_to ?? 'sin límite final'} (UTC)`;
}

export default function ReportsPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const allowed = isAuthenticated && !!user && ['GERENTE', 'SUPERADMIN'].includes(user.role);
  useEffect(() => { if (!allowed) router.replace('/login'); }, [allowed, router]);
  return allowed ? <ReportsView key={JSON.stringify([generation, user.id, user.role])} /> : <div role="status" className="p-6">Verificando acceso a reportes…</div>;
}

function ReportsView() {
  const page = useFinancialReports(), snapshot = page.snapshot;
  const orders = snapshot?.orders, reconciliation = snapshot?.reconciliation;
  const orderMoney = (value: number) => payoutAmountLabel(value, orders?.currency ?? undefined);
  const reconciledMoney = (value: number) => payoutAmountLabel(value, reconciliation?.currency ?? undefined);

  return <div className="p-4 md:p-6 bg-gray-50 min-h-screen">
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Reportes y Exportación</h1>
        <p className="text-gray-600">Consulta un rango y exporta sus órdenes verificadas.</p>
      </div>
      <Card><CardHeader><CardTitle>Rango de consulta</CardTitle>
        <CardDescription>Las fechas incluyen el día completo según el calendario UTC. Editarlas no cambia los datos confirmados hasta aplicar la consulta.</CardDescription>
      </CardHeader><CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <div><label htmlFor="report-start" className="block text-sm font-medium mb-1">Fecha inicio</label>
            <input id="report-start" type="date" value={page.draft.start} onChange={event => page.setDraft('start', event.target.value)} className="w-full min-w-0 rounded border p-2" /></div>
          <div><label htmlFor="report-end" className="block text-sm font-medium mb-1">Fecha fin</label>
            <input id="report-end" type="date" value={page.draft.end} onChange={event => page.setDraft('end', event.target.value)} className="w-full min-w-0 rounded border p-2" /></div>
          <div className="flex items-end"><Button variant="outline" className="w-full" onClick={() => { void page.apply(); }}>Aplicar consulta</Button></div>
          <div className="flex items-end"><Button className="w-full" disabled={!page.canExport} onClick={() => { void page.exportCsv(); }}>Exportar CSV</Button></div>
        </div>
        {page.dirty && <p className="text-sm text-amber-800">Hay fechas sin aplicar. Se mantienen los datos del rango confirmado; aplica la consulta antes de exportar.</p>}
        <p className="text-xs text-gray-600">Máximo {REPORT_EXPORT_LIMIT} órdenes por archivo. Para exportar un rango mayor, reduce las fechas; no se descarga un CSV truncado.</p>
      </CardContent></Card>
      {page.pending && <p role="status" className="text-sm text-blue-700">{page.pending === 'export' ? 'Verificando el rango confirmado y preparando el CSV…' : 'Consultando reporte y conciliación…'}</p>}
      {page.error && <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 space-y-2 text-red-800">
        <p>{page.error.message}</p>
        {page.error.retry && <Button variant="outline" disabled={page.retryDisabled} onClick={() => { void page.retry(); }}>{page.error.retry.mode === 'export' ? 'Reintentar exportación' : 'Reintentar consulta'}</Button>}
      </div>}
      {page.notice && <p role="status" className="rounded border bg-blue-50 p-3 text-sm text-blue-900">{page.notice}</p>}
      {!snapshot && !page.pending && <p className="text-gray-600">No se pudo comprobar el reporte. No hay cifras confirmadas para mostrar.</p>}
      {snapshot && orders && reconciliation && <section aria-label="Reporte confirmado" aria-busy={!!page.pending} className="space-y-6">
        <div className="rounded border bg-white p-4 text-sm text-gray-600 space-y-1">
          <p className="font-semibold text-gray-900">Rango confirmado: {rangeLabel(snapshot.range)}</p>
          <p>Ambos reportes corresponden al rango indicado. Las lecturas pueden cambiar mientras consultas.</p>
        </div>
        <Card><CardHeader><CardTitle>Órdenes del rango</CardTitle>
          <CardDescription>Incluye todos los estados. Los importes de órdenes no equivalen a ingresos cobrados.</CardDescription>
        </CardHeader><CardContent className="space-y-4">
          <p className="text-sm text-gray-600">{orders.currency ? `Moneda informada: ${orders.currency}` : 'Moneda no informada para órdenes'}</p>
          <dl className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {[
              { label: 'Total de órdenes', value: orders.total_orders.toLocaleString('es-VE') },
              { label: 'Órdenes entregadas', value: orders.completed_orders.toLocaleString('es-VE') },
              { label: 'Tarifas de todas las órdenes', value: orderMoney(orders.total_revenue) },
              { label: 'Valor bruto de órdenes', value: orderMoney(orders.gross_order_value) },
              { label: 'Clientes distintos informados', value: orders.active_customers.toLocaleString('es-VE') },
            ].map(item => <div key={item.label} className="rounded border bg-gray-50 p-3 min-w-0"><dt className="text-sm text-gray-600">{item.label}</dt><dd className="font-bold text-lg break-words">{item.value}</dd></div>)}
          </dl>
          <p className="text-sm text-gray-600">Filas cargadas: {orders.rows.length} de {orders.total_orders}. Se muestran hasta 10 como vista previa.</p>
          {orders.total_orders > REPORT_EXPORT_LIMIT && <p className="text-sm text-amber-800">Este rango supera el máximo de {REPORT_EXPORT_LIMIT} órdenes por CSV. Reduce las fechas para exportar el conjunto completo.</p>}
          {!orders.rows.length ? <p>No hay órdenes en el rango confirmado.</p> : <div className="overflow-x-auto">
            <table className="w-full text-sm"><caption className="text-left text-xs text-gray-600 mb-2">Vista previa de las órdenes cargadas</caption>
              <thead><tr className="border-b text-left"><th className="p-2">Orden</th><th className="p-2">Estado</th><th className="p-2">Total</th><th className="p-2">Método de pago</th></tr></thead>
              <tbody>{orders.rows.slice(0, 10).map(row => <tr key={row.id} className="border-b"><td className="p-2 break-all"><div>{row.external_id ?? 'Sin referencia externa'}</div><div className="text-xs text-gray-500 font-mono">{row.id}</div></td><td className="p-2">{row.status}</td><td className="p-2 whitespace-nowrap">{orderMoney(row.total)}</td><td className="p-2">{row.payment_method ?? 'No informado'}</td></tr>)}</tbody>
            </table>
          </div>}
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Conciliación del rango</CardTitle>
          <CardDescription>Entregas cobradas, ledger y estados internos de retiros. Su criterio contable puede diferir del reporte de todas las órdenes.</CardDescription>
        </CardHeader><CardContent className="space-y-4">
          <p className="text-sm text-gray-600">{reconciliation.currency ? `Moneda informada: ${reconciliation.currency}` : 'Moneda no informada para conciliación'}</p>
          <dl className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {[
              { label: 'Ingresos por entregas cobradas', value: reconciledMoney(reconciliation.delivery_revenue) },
              { label: 'Margen según conciliación', value: reconciledMoney(reconciliation.net_margin_after_rider_costs) },
              { label: 'Ganancias devengadas de riders', value: reconciledMoney(reconciliation.rider_earnings) },
              { label: 'Retiros pendientes', value: reconciledMoney(reconciliation.pending_payouts) },
              { label: 'Retiros en proceso o completados', value: reconciledMoney(reconciliation.processed_payouts) },
              { label: 'Obligación disponible informada', value: reconciledMoney(reconciliation.available_liability) },
              { label: 'Transacciones ledger', value: reconciliation.ledger_transactions.toLocaleString('es-VE') },
              { label: 'Solicitudes de retiro', value: reconciliation.payout_count.toLocaleString('es-VE') },
            ].map(item => <div key={item.label} className="rounded border bg-gray-50 p-3 min-w-0"><dt className="text-sm text-gray-600">{item.label}</dt><dd className="font-bold text-lg break-words">{item.value}</dd></div>)}
          </dl>
          <p className="text-xs text-gray-600">Los estados de retiros no certifican transferencias bancarias. El CSV contiene las órdenes, sin mezclar los agregados de conciliación.</p>
        </CardContent></Card>
      </section>}
    </div>
  </div>;
}
