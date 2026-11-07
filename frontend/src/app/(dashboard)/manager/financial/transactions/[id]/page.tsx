'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useTransactionDetail } from '@/hooks/useTransactionDetail';
import { TransactionAccess } from '@/components/financial/TransactionAccess';
import { transactionDateLabel, transactionId } from '@/lib/transaction-contract';
import { capturePrivateTask } from '@/lib/private-task';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

export default function TransactionDetailPage() {
  const params = useParams(), id = typeof params.id === 'string' ? params.id : '';
  return <TransactionAccess resource={id}><Detail id={id} /></TransactionAccess>;
}
function Detail({ id }: { id: string }) {
  const page = useTransactionDetail(id), data = page.data;
  const [printError, setPrintError] = useState<string | null>(null);
  const print = () => {
    try { capturePrivateTask().assertCurrent(); if (!data || data.id !== transactionId(id) || page.isLoading || page.error) return; window.print(); setPrintError(null); }
    catch { setPrintError('No se pudo imprimir el registro confirmado.'); }
  };
  const amount = (value: number | null) => payoutAmountLabel(value, data?.currency ?? undefined);
  return <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-2xl font-bold">Detalle de transacción</h1><p className="font-mono text-sm break-all">ID solicitado: {id || 'No informado'}</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => { setPrintError(null); void page.refresh(); }}>Consultar transacción</Button><Button variant="outline" disabled={!data || page.isLoading || !!page.error} onClick={print}>Imprimir registro</Button></div></div>
    <Link className="inline-block text-blue-700 underline" href="/manager/financial/transactions">Volver al historial</Link>
    {page.isLoading && <p role="status">Consultando el registro…</p>}
    {page.error && <div role="alert" className="rounded border bg-red-50 p-4 text-red-800 space-y-2"><p>{page.error}</p><Button variant="outline" disabled={page.isLoading} onClick={() => { void page.refresh(); }}>Reintentar lectura</Button></div>}
    {printError && <p role="alert" className="text-red-800">{printError}</p>}
    {!data && !page.isLoading && <p>No hay una transacción confirmada para esta consulta.</p>}
    {data && <section aria-label="Transacción confirmada" aria-busy={page.isLoading} className="space-y-5">
      <Card><CardHeader><CardTitle>Importes y estado registrados</CardTitle></CardHeader><CardContent className="space-y-4">
        <p className="font-mono break-all">ID confirmado: {data.id}</p>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">{[
          ['Importe registrado', amount(data.amount)], ['Moneda', data.currency ?? 'No informada'],
          ['Tipo registrado', data.type], ['Estado registrado', data.status],
          ['Saldo anterior informado', amount(data.balance_before)], ['Saldo posterior informado', amount(data.balance_after)],
        ].map(([label, value]) => <div key={label} className="rounded border bg-gray-50 p-3 min-w-0"><dt className="text-sm text-gray-600">{label}</dt><dd className="font-semibold break-words">{value}</dd></div>)}</dl>
        <p className="text-sm text-gray-600">El signo es el del importe guardado, sin reinterpretar cargos como ingresos. Este registro contable y sus estados no son una confirmación bancaria.</p>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Origen y trazabilidad informados</CardTitle></CardHeader><CardContent><dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">{[
        ['Descripción', data.description ?? 'No informada'], ['Referencia', data.reference_id ?? 'No informada'],
        ['Rider asociado', data.rider_id ?? 'No informado'], ['Tipo de origen', data.source_type ?? 'No informado'],
        ['ID de origen', data.source_id ?? 'No informado'], ['Clave de idempotencia informada', data.idempotency_key ?? 'No informada'],
        ['Actor creador informado', data.created_by_user_id ?? 'No informado'],
        ['Fecha de creación registrada', transactionDateLabel(data.created_at)], ['Última actualización registrada', transactionDateLabel(data.updated_at)],
        ['Fecha de proceso informada', transactionDateLabel(data.processed_at)],
      ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-sm text-gray-600">{label}</dt><dd className="break-all">{value}</dd></div>)}</dl></CardContent></Card>
    </section>}
  </div>;
}
