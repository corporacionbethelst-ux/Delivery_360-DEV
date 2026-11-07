'use client';
import Link from 'next/link';
import { useTransactionHistory, TRANSACTION_PAGE_SIZE } from '@/hooks/useTransactionHistory';
import { TRANSACTION_STATUSES, TRANSACTION_TYPES, transactionDateLabel } from '@/lib/transaction-contract';
import { TransactionAccess } from '@/components/financial/TransactionAccess';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

export default function TransactionsPage() { return <TransactionAccess><History /></TransactionAccess>; }
function History() {
  const page = useTransactionHistory();
  return <div className="p-4 md:p-6 bg-gray-50 min-h-screen"><div className="max-w-7xl mx-auto space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 max-w-full"><h1 className="text-2xl font-bold">Transacciones</h1><p className="text-gray-600">Movimientos contables registrados, en páginas de hasta 50 filas.</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { void page.refresh(); }}>Actualizar consulta</Button>
        <Button disabled={page.isLoading || !page.loaded || !!page.error || !page.visibleRows.length} onClick={page.exportPage}>Exportar página CSV</Button></div>
    </div>
    <Card><CardContent className="pt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
      <div><label htmlFor="transaction-search" className="block text-sm mb-1">Buscar solo en esta página</label><input id="transaction-search" className="w-full min-w-0 rounded border p-2" value={page.search} onChange={e => page.setSearch(e.target.value)} placeholder="ID, descripción, referencia o rider" /></div>
      <div><label htmlFor="transaction-type" className="block text-sm mb-1">Tipo en el servidor</label><select id="transaction-type" className="w-full min-w-0 rounded border p-2" value={page.selected.type} onChange={e => { void page.setFilter('type', e.target.value); }}><option value="ALL">Todos los tipos</option>{TRANSACTION_TYPES.map(type => <option key={type} value={type}>{type}</option>)}</select></div>
      <div><label htmlFor="transaction-status" className="block text-sm mb-1">Estado en el servidor</label><select id="transaction-status" className="w-full min-w-0 rounded border p-2" value={page.selected.status} onChange={e => { void page.setFilter('status', e.target.value); }}><option value="ALL">Todos los estados</option>{TRANSACTION_STATUSES.map(status => <option key={status} value={status}>{status}</option>)}</select></div>
    </CardContent></Card>
    {page.error && <div role="alert" className="rounded border bg-red-50 p-4 text-red-800 space-y-2"><p>{page.error}</p><Button variant="outline" disabled={page.isLoading} onClick={() => { void page.retry(); }}>Reintentar consulta</Button></div>}
    {page.exportError && <p role="alert" className="rounded border bg-red-50 p-3 text-red-800">{page.exportError}</p>}
    {page.isLoading && <p role="status" className="text-sm text-blue-700">Consultando transacciones…</p>}
    {page.loaded ? <section aria-label="Página confirmada" aria-busy={page.isLoading} className="space-y-4">
      <div className="rounded border bg-white p-4 text-sm text-gray-600 space-y-1">
        <p className="font-semibold text-gray-900">Consulta confirmada: tipo {page.type}; estado {page.status}.</p>
        <p>{page.rows.length} filas cargadas; {page.visibleRows.length} coincidencias visibles. La búsqueda y el CSV solo abarcan esta página.</p>
        <p>El importe conserva su signo registrado; un retiro positivo no se convierte en ingreso. El estado contable no certifica una transferencia bancaria.</p>
      </div>
      <Card><CardContent className="p-0 overflow-x-auto">
        {!page.rows.length ? <p className="p-6">No hay transacciones en esta página de la consulta.</p> : !page.visibleRows.length ? <p className="p-6">Sin coincidencias en esta página. Puedes navegar o cambiar la búsqueda.</p> : <table className="w-full text-sm"><caption className="text-left p-3 text-gray-600">Movimientos de la página confirmada; fechas en UTC</caption><thead><tr className="border-b text-left"><th className="p-3">Transacción</th><th className="p-3">Fecha registrada</th><th className="p-3">Tipo / estado</th><th className="p-3">Importe registrado</th><th className="p-3">Detalle</th></tr></thead>
          <tbody>{page.visibleRows.map(row => <tr key={row.id} className="border-b"><td className="p-3"><p className="font-mono break-all">{row.id}</p><p>{row.description ?? 'Descripción no informada'}</p><p className="text-xs text-gray-600">Rider: {row.rider_id ?? 'No informado'}</p>{row.reference_id && <p className="text-xs text-gray-600">Ref: {row.reference_id}</p>}</td><td className="p-3 whitespace-nowrap">{transactionDateLabel(row.created_at)}</td><td className="p-3"><p>{row.type}</p><p className="font-semibold">{row.status}</p></td><td className="p-3 font-semibold whitespace-nowrap">{payoutAmountLabel(row.amount, row.currency ?? undefined)}</td><td className="p-3"><Link className="text-blue-700 underline whitespace-nowrap" aria-label={`Ver transacción ${row.id}`} href={`/manager/financial/transactions/${encodeURIComponent(row.id)}`}>Ver detalle</Link></td></tr>)}</tbody></table>}
      </CardContent></Card>
    </section> : !page.isLoading && <p>No se pudo comprobar el historial. No hay movimientos confirmados para mostrar.</p>}
    <nav aria-label="Paginación de transacciones" className="flex flex-wrap items-center gap-3 text-sm">
      <Button variant="outline" disabled={page.isLoading || !page.loaded && !page.error || page.offset === 0 && !page.error} onClick={() => { void page.first(); }}>Volver al inicio</Button>
      <Button variant="outline" disabled={page.isLoading || page.offset === 0} onClick={() => { void page.previous(); }}>Anterior</Button>
      <span aria-live="polite">Página {page.offset / TRANSACTION_PAGE_SIZE + 1}</span>
      <Button variant="outline" disabled={page.isLoading || !page.hasNext} onClick={() => { void page.next(); }}>Siguiente</Button>
    </nav>
    <p className="text-xs text-gray-600">El servidor usa desplazamientos: cambios concurrentes pueden mover filas. Si el historial cambia, vuelve al inicio. No se informa un total global ni se exporta el historial completo.</p>
  </div></div>;
}
