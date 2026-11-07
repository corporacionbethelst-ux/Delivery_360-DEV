'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { financialService, type FinancialPeriod, type FinancialSummary } from '@/services/financial.service';
import { capturePrivateTask } from '@/lib/private-task';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { FINANCIAL_PERIODS, periodLabel } from '@/lib/financial-summary-contract';
import { payoutAmountLabel } from '@/lib/payout-contract';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface Snapshot { period: FinancialPeriod; data: FinancialSummary }

export default function ManagerFinancialPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const allowed = isAuthenticated && !!user && ['GERENTE', 'SUPERADMIN'].includes(user.role);
  useEffect(() => { if (!allowed) router.replace('/login'); }, [allowed, router]);
  return allowed ? <FinancialSummaryView key={JSON.stringify([generation, user.id, user.role])} />
    : <div role="status" className="p-6">Verificando acceso financiero…</div>;
}

function FinancialSummaryView() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pending, setPending] = useState<FinancialPeriod | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(false), sequence = useRef(0), attempt = useRef<FinancialPeriod>('week');
  const load = useCallback(async (period: FinancialPeriod) => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    attempt.current = period;
    setIsLoading(true); setPending(period); setError(null);
    try {
      task = capturePrivateTask();
      const data = await financialService.getSummary({ period });
      task.assertCurrent();
      if (current()) setSnapshot({ period, data });
    } catch {
      if (current()) setError(`No se pudo comprobar el resumen de ${periodLabel(period)}. Se conservan los últimos datos disponibles.`);
    } finally {
      if (current()) { setIsLoading(false); setPending(null); }
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load('week');
    return () => { alive.current = false; sequence.current++; };
  }, [load]);

  const data = snapshot?.data;
  const selected = pending ?? snapshot?.period ?? 'week';
  const amount = (value: number | null | undefined) => value == null ? 'No informado' : payoutAmountLabel(value, data?.currency ?? undefined);
  const chart = data ? [
    { label: 'Ingresos', value: data.total_revenue, color: 'bg-blue-600' },
    { label: 'Costos', value: data.total_costs, color: 'bg-red-500' },
    { label: 'Neto', value: data.net_margin, color: 'bg-emerald-600' },
  ] : [];
  const maximum = Math.max(1, ...chart.map(item => Math.abs(item.value)));
  const date = (value: string) => new Intl.DateTimeFormat('es-VE', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value));

  return <div className="p-4 md:p-6 bg-gray-50 min-h-screen">
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-full">
          <h1 className="text-2xl font-bold text-gray-900">Resumen Financiero</h1>
          <p className="text-gray-600">Ingresos por entregas cobradas y costos registrados del período.</p>
        </div>
        <div role="group" aria-label="Período financiero" className="flex max-w-full flex-wrap gap-2">
          {FINANCIAL_PERIODS.map(period => <Button key={period} aria-pressed={selected === period}
            variant={selected === period ? 'default' : 'outline'} onClick={() => { void load(period); }}>{periodLabel(period)}</Button>)}
          <Button variant="outline" onClick={() => { void load(snapshot?.period ?? 'week'); }}>Actualizar resumen</Button>
        </div>
      </div>
      {isLoading && <p role="status" className="text-sm text-blue-700">Consultando {periodLabel(pending ?? 'week')}…</p>}
      {error && <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 space-y-2 text-red-800">
        <p>{error}</p>
        <Button variant="outline" disabled={isLoading} onClick={() => { void load(attempt.current); }}>Reintentar consulta</Button>
      </div>}
      {!data && !isLoading && <p className="text-gray-600">No se pudo comprobar el resumen. Consulta de nuevo antes de interpretar las cifras.</p>}
      {data && <section aria-label="Resumen confirmado" aria-busy={isLoading} className="space-y-6">
        <div className="rounded border bg-white p-4 text-sm text-gray-600 space-y-1">
          <p className="font-semibold text-gray-900">Datos confirmados: {periodLabel(snapshot!.period)}</p>
          <p>{data.period_start && data.period_end ? `Rango consultado (UTC): ${date(data.period_start)} – ${date(data.period_end)}` : 'Rango no informado por el servidor'}</p>
          <p>{data.currency ? `Moneda informada: ${data.currency}` : 'Moneda no informada por el servidor'}</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {[
            { label: 'Ingresos por entregas', value: amount(data.total_revenue) },
            { label: 'Movimientos registrados', value: data.total_transactions.toLocaleString('es-VE') },
            { label: 'Costos operativos', value: amount(data.total_costs) },
            { label: 'Margen neto', value: amount(data.net_margin) },
          ].map(item => <Card key={item.label}><CardHeader>
            <CardTitle className="text-sm font-medium text-gray-600">{item.label}</CardTitle>
          </CardHeader><CardContent className="text-xl font-bold break-words">{item.value}</CardContent></Card>)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card><CardHeader><CardTitle>Comparativa general</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              <p className="text-sm text-gray-600">Los valores negativos se muestran a la izquierda de cero.</p>
              {chart.map(item => {
                const width = Math.abs(item.value) / maximum * 50;
                return <div key={item.label} className="space-y-1">
                  <div className="flex flex-wrap justify-between gap-2 text-sm"><span>{item.label}</span><span>{amount(item.value)}</span></div>
                  <div role="img" aria-label={`${item.label}: ${amount(item.value)}`} className="relative h-5 rounded bg-gray-100">
                    <span className="absolute top-0 bottom-0 left-1/2 border-l border-gray-400" />
                    <span data-direction={item.value < 0 ? 'negative' : 'positive'} className={`absolute h-5 rounded ${item.color}`}
                      style={{ left: `${item.value < 0 ? 50 - width : 50}%`, width: `${width}%` }} />
                  </div>
                </div>;
              })}
            </CardContent>
          </Card>
          <Card><CardHeader><CardTitle>Desglose de costos</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {[
                { label: 'Costo reconocido de repartidores', value: data.total_rider_payouts },
                { label: 'Otros costos informados', value: data.other_costs },
                { label: 'Retiros en proceso o completados', value: data.cash_payouts_processed },
                { label: 'Ingresos devengados por repartidores', value: data.rider_earnings_accrued },
                { label: 'Deducciones registradas', value: data.rider_deductions },
              ].map(item => <div key={item.label} className="flex flex-wrap justify-between gap-2 rounded border bg-gray-50 p-3 text-sm">
                <span className="text-gray-600">{item.label}</span><span className="font-semibold">{amount(item.value)}</span>
              </div>)}
              <p className="text-xs text-gray-600">Los costos pueden incluir devengos. Un retiro en proceso no confirma una transferencia bancaria.</p>
            </CardContent>
          </Card>
        </div>
      </section>}
    </div>
  </div>;
}
