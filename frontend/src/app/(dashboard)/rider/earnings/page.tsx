'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { 
  DollarSign, 
  TrendingUp, 
  Clock, 
  CheckCircle, 
  ShieldCheck,
  AlertCircle, 
  ArrowRight, 
  Download, 
  Loader2, 
  Wallet,
  BarChart3
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency } from '@/lib/formatters';
import { financialService, RiderEarnings, FinancialTransaction } from '@/services/financial.service';
import { payoutService, PayoutBalance } from '@/services/payout.service';

// Importaciones directas de Recharts para asegurar el renderizado
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  Legend, 
  ResponsiveContainer,
  Cell
} from 'recharts';

const MIN_WITHDRAWAL_AMOUNT = 10;

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
};

export default function RiderEarningsPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();

  const [earnings, setEarnings] = useState<RiderEarnings | null>(null);
  const [balance, setBalance] = useState<PayoutBalance | null>(null);
  const [recentMovements, setRecentMovements] = useState<FinancialTransaction[]>([]);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== 'REPARTIDOR') {
      router.push('/login');
      return;
    }

    const loadEarnings = async () => {
      setLoadingData(true);
      setError(null);
      try {
        const [earningsResult, balanceResult, breakdownResult] = await Promise.allSettled([
          financialService.getMyEarnings(),
          payoutService.getAvailableBalance(),
          financialService.getMyEarningsBreakdown({ limit: 5 }),
        ]);

        if (earningsResult.status === 'rejected') {
          throw earningsResult.reason;
        }

        const earningsData = earningsResult.value;
        setEarnings(earningsData);

        if (balanceResult.status === 'fulfilled') {
          setBalance(balanceResult.value);
        } else {
          console.warn('No se pudo cargar el balance de payout; usando resumen de ganancias.', balanceResult.reason);
          setBalance({
            available: Number(earningsData.pending_payout ?? 0),
            pending: 0,
            processed: Math.max(Number(earningsData.total_earned ?? 0) - Number(earningsData.pending_payout ?? 0), 0),
            total_earned: Number(earningsData.total_earned ?? 0),
            currency: 'COP',
          });
        }

        setRecentMovements(breakdownResult.status === 'fulfilled' ? breakdownResult.value.items : []);
      } catch (err) {
        console.error('Error loading rider earnings:', err);
        setError(getErrorMessage(err, 'No se pudieron cargar tus ganancias reales.'));
        setEarnings(null);
        setBalance(null);
        setRecentMovements([]);
      } finally {
        setLoadingData(false);
      }
    };

    loadEarnings();
  }, [user, isAuthenticated, router, isMounted]);

  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin h-12 w-12 text-green-600 mx-auto mb-4" />
          <p className="text-gray-600">Cargando tus ganancias...</p>
        </div>
      </div>
    );
  }

  const totalEarned = Number(balance?.total_earned ?? earnings?.total_earned ?? 0);
  const availableBalance = Number(balance?.available ?? earnings?.pending_payout ?? 0);
  const pendingWithdrawals = Number(balance?.pending ?? 0);
  const processedWithdrawals = Number(balance?.processed ?? Math.max(totalEarned - availableBalance - pendingWithdrawals, 0));
  const completedDeliveries = Number(earnings?.completed_deliveries ?? 0);
  const canRequestWithdrawal = availableBalance >= MIN_WITHDRAWAL_AMOUNT;

  // Datos formateados para el gráfico
  const chartData = [
    { name: 'Total Ganado', value: totalEarned, color: '#16a34a' }, // green-600
    { name: 'Disponible', value: availableBalance, color: '#2563eb' }, // blue-600
    { name: 'En Proceso', value: pendingWithdrawals, color: '#9333ea' }, // purple-600
    { name: 'Pagado', value: processedWithdrawals, color: '#f97316' }, // orange-500
  ];

  return (
    <div className="p-6 bg-gray-50 min-h-screen pb-20">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Mis Ganancias</h1>
            <p className="text-gray-500">Resumen real de ingresos, saldo disponible y retiros solicitados.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => router.push('/rider/earnings/payouts')}>
              <Download className="w-4 h-4 mr-2" /> Historial
            </Button>
            <Button
              className="bg-green-600 hover:bg-green-700 text-white shadow-md shadow-green-200"
              onClick={() => router.push('/rider/earnings/withdraw')}
              disabled={!canRequestWithdrawal}
            >
              Solicitar Retiro
            </Button>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        )}

        {/* Tarjetas de Métricas Superiores */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="border-t-4 border-t-green-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Total Ganado</p>
                  <h3 className="text-3xl font-bold text-gray-900 mt-1">{formatCurrency(totalEarned)}</h3>
                </div>
                <div className="p-2 bg-green-100 rounded-full">
                  <DollarSign className="w-6 h-6 text-green-600" />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-xs text-green-600 font-medium">
                <TrendingUp className="w-3 h-3 mr-1" />
                <span>Calculado desde entregas reales</span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-blue-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Disponible para Retiro</p>
                  <h3 className="text-3xl font-bold text-gray-900 mt-1">{formatCurrency(availableBalance)}</h3>
                </div>
                <div className="p-2 bg-blue-100 rounded-full">
                  <Wallet className="w-6 h-6 text-blue-600" />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">Mínimo para retiro: {formatCurrency(MIN_WITHDRAWAL_AMOUNT)}</p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-purple-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Entregas Completadas</p>
                  <h3 className="text-3xl font-bold text-gray-900 mt-1">{completedDeliveries}</h3>
                </div>
                <div className="p-2 bg-purple-100 rounded-full">
                  <TrendingUp className="w-6 h-6 text-purple-600" />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-xs text-gray-500">
                <span>Histórico real del backend</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Gráfico de Barras Implementado Directamente con Recharts */}
        <Card className="shadow-sm overflow-hidden">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-blue-600" />
              Estado de tus ganancias
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis 
                    dataKey="name" 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: '#6b7280', fontSize: 12 }} 
                    dy={10}
                  />
                  <YAxis 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: '#6b7280', fontSize: 12 }} 
                    tickFormatter={(value) => `$${value.toLocaleString()}`}
                  />
                  <Tooltip 
                    cursor={{ fill: '#f3f4f6' }}
                    contentStyle={{ 
                      backgroundColor: '#fff', 
                      borderRadius: '8px', 
                      border: '1px solid #e5e7eb',
                      boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'
                    }}
                    formatter={(value: number) => formatCurrency(value)}
                  />
                  <Legend wrapperStyle={{ paddingTop: '20px' }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={60}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Últimos Movimientos */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">Últimos movimientos financieros</CardTitle>
          </CardHeader>
          <CardContent>
            {recentMovements.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-4">Aún no hay movimientos financieros para mostrar.</p>
            ) : (
              <div className="space-y-3">
                {recentMovements.map((movement) => (
                  <div key={movement.id} className="flex items-center justify-between border rounded-lg p-3 bg-white hover:shadow-sm transition-shadow">
                    <div>
                      <p className="font-semibold text-gray-900">{movement.description}</p>
                      <p className="text-xs text-gray-500">
                        {movement.transaction_type} · {movement.created_at ? new Date(movement.created_at).toLocaleString() : 'Sin fecha'}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className={`font-bold ${movement.amount >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {movement.amount >= 0 ? '+' : ''}{formatCurrency(movement.amount)}
                      </p>
                      <p className="text-xs text-gray-500">Saldo: {formatCurrency(movement.balance_after || 0)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Tarjetas de Retiros en Proceso y Completados */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Tarjeta: Retiros en Proceso */}
          <Card className="relative overflow-hidden border-l-4 border-l-indigo-500 shadow-sm hover:shadow-md transition-shadow duration-200">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <Clock className="w-24 h-24 text-indigo-600" />
            </div>
            
            <CardContent className="p-6 relative z-10">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-indigo-100 rounded-lg">
                    <Clock className="w-6 h-6 text-indigo-600" />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900 text-lg leading-tight">En Proceso</h3>
                    <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Solicitudes Pendientes</p>
                  </div>
                </div>
                <Badge variant="outline" className="bg-indigo-50 text-indigo-700 border-indigo-200">
                  Activo
                </Badge>
              </div>

              <div className="mb-4">
                <p className="text-3xl font-extrabold text-indigo-900 tracking-tight">
                  {formatCurrency(pendingWithdrawals)}
                </p>
                <p className="text-sm text-gray-600 mt-2 leading-relaxed">
                  Tienes este monto en solicitudes que están siendo revisadas o procesadas.
                </p>
              </div>

              <Button 
                variant="outline" 
                className="w-full justify-between group border-indigo-200 text-indigo-700 hover:bg-indigo-50 hover:text-indigo-900"
                onClick={() => router.push('/rider/earnings/payouts')}
              >
                <span className="font-semibold">Ver historial detallado</span>
                <ArrowRight className="w-4 h-4 ml-2 transition-transform group-hover:translate-x-1" />
              </Button>
            </CardContent>
          </Card>

          {/* Tarjeta: Pagos Procesados */}
          <Card className="relative overflow-hidden border-l-4 border-l-orange-500 shadow-sm hover:shadow-md transition-shadow duration-200">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <CheckCircle className="w-24 h-24 text-orange-600" />
            </div>
            
            <CardContent className="p-6 relative z-10">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-orange-100 rounded-lg">
                    <CheckCircle className="w-6 h-6 text-orange-600" />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900 text-lg leading-tight">Completados</h3>
                    <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Historial de Pagos</p>
                  </div>
                </div>
                <Badge variant="outline" className="bg-orange-50 text-orange-700 border-orange-200">
                  Finalizado
                </Badge>
              </div>

              <div className="mb-4">
                <p className="text-3xl font-extrabold text-orange-900 tracking-tight">
                  {formatCurrency(processedWithdrawals)}
                </p>
                <p className="text-sm text-gray-600 mt-2 leading-relaxed">
                  Total acumulado de retiros ya pagados a tu cuenta.
                </p>
              </div>

              <div className="flex items-center gap-2 p-3 bg-orange-50/50 rounded-lg border border-orange-100">
                <div className="p-1.5 bg-white rounded-md shadow-sm">
                  <ShieldCheck className="w-4 h-4 text-orange-600" />
                </div>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-orange-800">Datos Verificados</p>
                  <p className="text-[10px] text-orange-600/80 font-mono truncate">
                    Fuente: /payouts/balance + /financial/riders/me
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}