'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore'; // ✅ CORRECCIÓN: Usar Zustand
import { TrendingUp, Award, Clock, Target, Activity, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface ProductivityStats {
  total_deliveries: number;
  avg_time_minutes: number;
  sla_compliance_rate: number;
  total_earnings: number;
  level?: number;
  points?: number;
}

export default function RiderProductivityPage() {
  const router = useRouter();
  // ✅ CORRECCIÓN: Obtener datos del store
  const { user, isAuthenticated } = useAuthStore(); 
  
  const [stats, setStats] = useState<ProductivityStats | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [isMounted, setIsMounted] = useState(false);

  // Efecto para evitar hidratación incorrecta
  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    // ✅ Seguridad: Verificar montaje, autenticación y rol
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== 'REPARTIDOR') {
      router.push('/login');
      return;
    }

    loadStats();
  }, [user, isAuthenticated, router, isMounted]);

  const loadStats = async () => {
    setLoadingData(true);
    try {
      // Mock data (Reemplazar con: const data = await productivityService.getStats())
      await new Promise(r => setTimeout(r, 800));
      setStats({
        total_deliveries: 42,
        avg_time_minutes: 28,
        sla_compliance_rate: 95.5,
        total_earnings: 450.00,
        level: 3,
        points: 1250
      });
    } catch (error) {
      console.error('Error loading productivity:', error);
    } finally {
      setLoadingData(false);
    }
  };

  // ✅ Seguridad: Mostrar carga mientras se verifica autenticación
  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Mi Productividad</h1>

        <Card className="mb-6 bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-lg">
          <CardContent className="p-6 flex justify-between items-center">
            <div>
              <p className="text-blue-100 text-sm font-medium uppercase tracking-wide">Nivel Actual</p>
              <h2 className="text-5xl font-bold mt-2">{stats.level ?? 1}</h2>
              <p className="text-blue-100 text-sm mt-2 flex items-center gap-2">
                <Award className="w-4 h-4" /> {stats.points ?? 0} puntos acumulados
              </p>
            </div>
            <Award className="w-20 h-20 text-blue-200 opacity-80 hidden sm:block" />
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2 text-gray-500">
                <Activity className="w-5 h-5 text-blue-600" />
                <CardTitle className="text-sm font-normal">Entregas Totales</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">{stats.total_deliveries}</p>
            </CardContent>
          </Card>

          <Card className="shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2 text-gray-500">
                <Clock className="w-5 h-5 text-orange-600" />
                <CardTitle className="text-sm font-normal">Tiempo Promedio</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">{Math.round(stats.avg_time_minutes)} <span className="text-sm font-normal text-gray-500">min</span></p>
            </CardContent>
          </Card>

          <Card className="shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2 text-gray-500">
                <Target className="w-5 h-5 text-green-600" />
                <CardTitle className="text-sm font-normal">Cumplimiento SLA</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">{stats.sla_compliance_rate.toFixed(1)}%</p>
            </CardContent>
          </Card>

          <Card className="shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2 text-gray-500">
                <TrendingUp className="w-5 h-5 text-emerald-600" />
                <CardTitle className="text-sm font-normal">Ganancias Acum.</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-emerald-600">${stats.total_earnings.toFixed(2)}</p>
            </CardContent>
          </Card>
        </div>

        <Card className="border-l-4 border-l-blue-500 shadow-sm">
          <CardContent className="p-6">
            <h3 className="font-semibold text-gray-900 mb-2 flex items-center gap-2">
              <Award className="w-5 h-5 text-blue-600" /> Consejo del día
            </h3>
            <p className="text-gray-600 text-sm leading-relaxed">
              Mantén tu tiempo promedio por debajo de 30 minutos y asegura un cumplimiento SLA superior al 90% para subir de nivel más rápido y desbloquear bonos exclusivos.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}