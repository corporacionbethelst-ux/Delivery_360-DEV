'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore'; // ✅ CORRECCIÓN: Usar Zustand
import { DollarSign, TrendingUp, Clock, AlertCircle, ArrowRight, Download, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { SimpleBarChart } from '@/components/charts/SimpleBarChart';
import { formatCurrency } from '@/lib/formatters';

interface LocalEarningsData {
  total_earned: number;
  pending_payout: number;
  completed_deliveries: number;
  [key: string]: any;
}

export default function RiderEarningsPage() { 
  const router = useRouter();
  
  // ✅ CORRECCIÓN 1: No desestructurar 'isLoading' porque no existe en el store simple
  // Si tu store tiene 'loading', úsalo, si no, usamos la ausencia de user como indicador.
  const { user, isAuthenticated } = useAuthStore(); 
  
  const [earnings, setEarnings] = useState<LocalEarningsData | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    // ✅ CORRECCIÓN 2: Lógica de protección sin 'isLoading' externo
    
    // 1. Si no ha montado o no hay usuario, esperamos (o redirigimos si pasó mucho tiempo)
    if (!isMounted || !user) return;

    // 2. Si el usuario no es repartidor, redirigir
    if (user.role !== 'REPARTIDOR') {
      router.push('/login');
      return;
    }

    // 3. Cargar datos
    const loadEarnings = async () => {
      setLoadingData(true);
      setError(null);
      try {
        await new Promise(r => setTimeout(r, 800));
        
        const rawData: any = {
          total_earned: 450.50,
          pending_payout: 120.00,
          completed_deliveries: 42
        };

        if (rawData) {
          const total = Number(rawData['total_earned'] ?? 0);
          const pending = Number(rawData['pending_payout'] ?? 0);
          const completed = Number(rawData['completed_deliveries'] ?? 0);

          setEarnings({
            total_earned: total,
            pending_payout: pending,
            completed_deliveries: completed,
            ...rawData
          });
        }
      } catch (err: any) {
        console.error('Error loading earnings:', err);
        setError('No se pudieron cargar tus ganancias.');
        setEarnings({
          total_earned: 0,
          pending_payout: 0,
          completed_deliveries: 0
        });
      } finally {
        setLoadingData(false);
      }
    };

    loadEarnings();
  }, [user, router, isMounted]); // ✅ CORRECCIÓN 3: Eliminar 'isLoading' de las dependencias

  // ✅ CORRECCIÓN 4: Condición de carga unificada
  // Mostramos loader si: no ha montado, no hay usuario (esperando auth), o estamos cargando datos financieros
  if (!isMounted || !user || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Cargando tus ganancias...</p>
        </div>
      </div>
    );
  }

  // Si no hay usuario o datos (seguridad extra)
  if (!user || !earnings) return null;

  const totalEarned = earnings.total_earned;
  const pendingPayout = earnings.pending_payout;
  const completedDeliveries = earnings.completed_deliveries;
  
  const chartData = [
    { label: 'Lun', value: 30 }, { label: 'Mar', value: 45 },
    { label: 'Mié', value: 25 }, { label: 'Jue', value: 50 },
    { label: 'Vie', value: 80 }, { label: 'Sáb', value: 95 },
    { label: 'Dom', value: 60 },
  ];

  return (
    <div className="p-6 bg-gray-50 min-h-screen pb-20">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Mis Ganancias</h1>
            <p className="text-gray-500">Resumen de ingresos y retiros disponibles.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => router.push('/rider/earnings/payouts')}>
              <Download className="w-4 h-4 mr-2" /> Historial
            </Button>
            <Button 
              className="bg-green-600 hover:bg-green-700 text-white shadow-md shadow-green-200"
              onClick={() => router.push('/rider/earnings/withdraw')}
              disabled={pendingPayout < 10} // ✅ Corrección: < en lugar de <= para permitir exactamente 10 si fuera el caso, aunque el mensaje dice "al menos 10"
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

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="border-t-4 border-t-green-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Total Acumulado</p>
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
                <span>+12% vs mes anterior</span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-blue-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Disponible para Retiro</p>
                  <h3 className="text-3xl font-bold text-gray-900 mt-1">{formatCurrency(pendingPayout)}</h3>
                </div>
                <div className="p-2 bg-blue-100 rounded-full">
                  <Clock className="w-6 h-6 text-blue-600" />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">Mínimo para retiro: {formatCurrency(10)}</p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-purple-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Entregas Realizadas</p>
                  <h3 className="text-3xl font-bold text-gray-900 mt-1">{completedDeliveries}</h3>
                </div>
                <div className="p-2 bg-purple-100 rounded-full">
                  <TrendingUp className="w-6 h-6 text-purple-600" />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-xs text-gray-500">
                <span>Este mes</span>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">Rendimiento Semanal</CardTitle>
          </CardHeader>
          <CardContent>
            <SimpleBarChart data={chartData} height={250} showValues={false} className="pt-4" />
          </CardContent>
        </Card>

        {/* Sección informativa adicional */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card className="bg-gradient-to-br from-indigo-50 to-white border-indigo-100">
            <CardContent className="p-6">
              <h3 className="font-bold text-indigo-900 mb-2">¿Sabías qué?</h3>
              <p className="text-sm text-indigo-700 mb-4">
                Completar más de 10 entregas los fines de semana te da un bono extra del 10%.
              </p>
              <Button variant="link" className="p-0 h-auto text-indigo-600 font-semibold">
                Ver programa de incentivos <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-orange-50 to-white border-orange-100">
            <CardContent className="p-6">
              <h3 className="font-bold text-orange-900 mb-2">Próximo Pago</h3>
              <p className="text-sm text-orange-700 mb-4">
                Los pagos se procesan todos los viernes. Si solicitas tu retiro antes del jueves a las 14hs, lo recibes el mismo viernes.
              </p>
              <div className="text-xs font-mono text-orange-600 bg-orange-100 inline-block px-2 py-1 rounded">
                Próxima fecha: Viernes, 18 Oct
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}