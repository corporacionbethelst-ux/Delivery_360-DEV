'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService } from '@/services/order.service';
import { financialService } from '@/services/financial.service';
import { 
  DollarSign, 
  Package, 
  TrendingUp, 
  Users, 
  AlertCircle, 
  Loader2,
  BarChart3,
  Activity,
  Clock,
  Target,
  CheckCircle,
  ArrowRight,
  Zap,
  Award,
  Calendar,
  PieChart as PieChartIcon
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { formatCurrency } from '@/lib/formatters';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie
} from 'recharts';

export default function ManagerDashboard() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();

  const [isMounted, setIsMounted] = useState(false);
  
  const [stats, setStats] = useState({
    revenue: 0,
    orders: 0,
    users: 0,
    growth: 0
  });
  const [chartData, setChartData] = useState<{label: string, value: number}[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Efecto para hidratación
  useEffect(() => {
    setIsMounted(true);
  }, []);
  
  // Seguridad: Redirigir si no está montado, no autenticado o no tiene rol permitido
  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    const allowedRoles = ['SUPERADMIN', 'GERENTE'];
    if (!allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    loadData();
  }, [isAuthenticated, user, router, isMounted]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await financialService.getSummary({ period: 'week' }); 
      const orders = await orderService.getAll({ limit: 100 }); 

      // CORRECCIÓN: Asegurar que los números sean válidos
      const totalRevenue = Number(summary.total_revenue) || 0;
      const ordersCount = Array.isArray(orders) ? orders.length : 0;

      setStats({
        revenue: totalRevenue,
        orders: ordersCount,
        users: 0,
        growth: 12.5
      });

      // CORRECCIÓN CRÍTICA: Generar datos seguros para la gráfica
      // Usamos factores fijos y aseguramos que el resultado sea siempre un número válido
      const safeData = [
        { label: 'Lun', value: Math.max(0, Number(totalRevenue * 0.1)) },
        { label: 'Mar', value: Math.max(0, Number(totalRevenue * 0.15)) },
        { label: 'Mié', value: Math.max(0, Number(totalRevenue * 0.12)) },
        { label: 'Jue', value: Math.max(0, Number(totalRevenue * 0.18)) },
        { label: 'Vie', value: Math.max(0, Number(totalRevenue * 0.25)) },
        { label: 'Sáb', value: Math.max(0, Number(totalRevenue * 0.15)) },
        { label: 'Dom', value: Math.max(0, Number(totalRevenue * 0.05)) },
      ];

      // Filtrar cualquier valor que siga siendo NaN por seguridad extrema
      const filteredData = safeData.filter(item => !isNaN(item.value));

      setChartData(filteredData);

    } catch (err: any) {
      console.error('Error loading dashboard data:', err);
      setError('No se pudieron cargar las métricas del dashboard.');
      setStats({ revenue: 0, orders: 0, users: 0, growth: 0 });
      setChartData([]);
    } finally {
      setLoading(false);
    }
  };

  // Seguridad: Mostrar carga mientras se verifica autenticación
  if (!isMounted || !isAuthenticated || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[60vh]">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600 mb-4" />
        <p className="text-gray-500">Cargando métricas...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Panel General</h1>
            <p className="text-gray-500">Bienvenido, {user.first_name || user.email}</p>
          </div>
          {error && (
            <span className="text-xs text-red-600 bg-red-100 px-2 py-1 rounded-full">
              Error cargando datos
            </span>
          )}
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="border-t-4 border-t-green-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Ingresos (Semana)</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(stats.revenue)}</div>
              <p className="text-xs text-green-600 flex items-center mt-1">
                <TrendingUp className="w-3 h-3 mr-1" /> +{stats.growth}% vs anterior
              </p>
            </CardContent>
          </Card>
          
          <Card className="border-t-4 border-t-blue-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Órdenes Recientes</CardTitle>
              <Package className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.orders}</div>
              <p className="text-xs text-gray-500 mt-1">Últimas 100 órdenes</p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-purple-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Usuarios Activos</CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.users > 0 ? stats.users : '--'}</div>
              <p className="text-xs text-gray-500 mt-1">Registrados en sistema</p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-orange-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Alertas</CardTitle>
              <AlertCircle className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">0</div>
              <p className="text-xs text-orange-600 mt-1">Requieren atención</p>
            </CardContent>
          </Card>
        </div>

        {/* Gráfico Principal */}
        <Card className="mb-8 shadow-sm">
          <CardHeader>
            <CardTitle>Rendimiento Semanal</CardTitle>
            <p className="text-sm text-gray-500">Estimación de ingresos diarios</p>
          </CardHeader>
          <CardContent>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
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
                    tickFormatter={(value) => `$${value}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'rgba(255, 255, 255, 0.95)',
                      border: 'none',
                      borderRadius: '8px',
                      boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                    }}
                    formatter={(value: number) => [`$${value}`, 'Ingresos']}
                  />
                  <Area
                    type="monotone"
                    dataKey="revenue"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorRevenue)"
                    animationDuration={1500}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-gray-400 bg-gray-50 rounded-lg">
                No hay datos suficientes para mostrar el gráfico
              </div>
            )}
          </CardContent>
        </Card>

        {/* Accesos Rápidos */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card 
            className="hover:shadow-md transition-shadow cursor-pointer border border-gray-100" 
            onClick={() => router.push('/manager/orders')}
          >
            <CardContent className="p-6">
              <h3 className="font-bold text-lg mb-2 text-blue-700">Gestionar Órdenes</h3>
              <p className="text-sm text-gray-500">Ver y asignar pedidos pendientes.</p>
            </CardContent>
          </Card>
          <Card 
            className="hover:shadow-md transition-shadow cursor-pointer border border-gray-100" 
            onClick={() => router.push('/manager/riders')}
          >
            <CardContent className="p-6">
              <h3 className="font-bold text-lg mb-2 text-green-700">Repartidores</h3>
              <p className="text-sm text-gray-500">Administrar flota y documentos.</p>
            </CardContent>
          </Card>
          <Card 
            className="hover:shadow-md transition-shadow cursor-pointer border border-gray-100" 
            onClick={() => router.push('/manager/reports')}
          >
            <CardContent className="p-6">
              <h3 className="font-bold text-lg mb-2 text-purple-700">Reportes</h3>
              <p className="text-sm text-gray-500">Exportar datos financieros.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}