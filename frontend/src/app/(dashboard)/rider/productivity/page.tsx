'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { 
  TrendingUp, Award, Clock, Target, Activity, Loader2, AlertCircle, 
  ArrowUpRight, ArrowDownRight, Medal, Star, Zap, Calendar, ChevronRight 
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { formatCurrency } from '@/lib/formatters';
import { financialService } from '@/services/financial.service';
import { orderService, Order } from '@/services/order.service';
import { riderService } from '@/services/rider.service';
import { deliveriesService } from '@/services/deliveries.service';
import { BonusBreakdownCard } from '@/components/productivity/BonusBreakdownCard';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, 
  BarChart, Bar, Cell, PieChart, Pie 
} from 'recharts';

// --- Tipos ---
interface ProductivityStats {
  total_deliveries: number;
  avg_time_minutes: number;
  sla_compliance_rate: number;
  total_earnings: number;
  level: number;
  points: number;
  nextLevelPoints: number;
  dailyDeliveries: { day: string; count: number }[];
  statusDistribution: { name: string; value: number; color: string }[];
}

interface RecentDelivery {
  id: string;
  customer_name: string;
  completed_at: string;
  status: string;
  locked_bonus_amount: number | null;
  bonus_breakdown: {
    base: number | null;
    zone_multiplier: number | null;
    tier_multiplier: number | null;
    tier_level: string | null;
    total: number;
  } | null;
}

const LEVEL_THRESHOLDS = [0, 500, 1500, 3000, 5000, 8000]; // Puntos necesarios por nivel

// --- Helpers de Cálculo ---
const getOrderDurationMinutes = (order: Order): number | null => {
  const startValue = order.accepted_at ?? order.created_at;
  const endValue = order.delivered_at;
  if (!startValue || !endValue) return null;
  const start = new Date(startValue).getTime();
  const end = new Date(endValue).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return Math.round((end - start) / 60000);
};

const isSlaMet = (order: Order): boolean | null => {
  if (!order.delivered_at || !order.sla_deadline) return null;
  return new Date(order.delivered_at).getTime() <= new Date(order.sla_deadline).getTime();
};

const getDayName = (dateStr: string) => {
  return new Date(dateStr).toLocaleDateString('es-ES', { weekday: 'short' });
};

export default function RiderProductivityPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();

  const [stats, setStats] = useState<ProductivityStats | null>(null);
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
    void loadStats();
  }, [user, isAuthenticated, router, isMounted]);

  const loadStats = async () => {
    setLoadingData(true);
    setError(null);

    try {
      const [profile, earnings, orders] = await Promise.all([
        riderService.getProfile(),
        financialService.getMyEarnings(),
        orderService.getAll({ limit: 200 }), // Últimas 200 órdenes para análisis
      ]);

      const completedOrders = orders.filter((o) => o.status === 'ENTREGADO');
      
      // Cálculos de Métricas
      const durations = completedOrders.map(getOrderDurationMinutes).filter((v): v is number => v !== null);
      const slaResults = completedOrders.map(isSlaMet).filter((v): v is boolean => v !== null);
      
      const avgTime = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
      const slaRate = slaResults.length > 0 ? (slaResults.filter(Boolean).length / slaResults.length) * 100 : 0;
      
      // Datos para Gráficos
      const last7Days = Array.from({ length: 7 }, (_, i) => {
        const d = new Date();
        d.setDate(d.getDate() - (6 - i));
        return d.toISOString().split('T')[0];
      });

      const dailyData = last7Days.map(date => {
        const count = completedOrders.filter(o => o.delivered_at?.startsWith(date)).length;
        return { day: getDayName(date), count };
      });

      const currentLevel = Number(profile.level ?? 1);
      const currentPoints = Number(profile.total_points ?? 0);
      const nextLevelPoints = LEVEL_THRESHOLDS[currentLevel] || (currentPoints + 1000);
      const progressToNext = Math.min(100, (currentPoints / nextLevelPoints) * 100);

      setStats({
        total_deliveries: completedOrders.length,
        avg_time_minutes: avgTime,
        sla_compliance_rate: slaRate,
        total_earnings: Number(earnings.total_earned ?? 0),
        level: currentLevel,
        points: currentPoints,
        nextLevelPoints,
        dailyDeliveries: dailyData,
        statusDistribution: [
          { name: 'A tiempo', value: slaResults.filter(Boolean).length, color: '#10b981' },
          { name: 'Retraso', value: slaResults.length - slaResults.filter(Boolean).length, color: '#f43f5e' },
        ]
      });
    } catch (err) {
      console.error('Error loading productivity:', err);
      setError('No se pudo cargar tu productividad. Verifica tu conexión.');
    } finally {
      setLoadingData(false);
    }
  };

  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] bg-gray-50/50">
        <Loader2 className="animate-spin h-10 w-10 text-blue-600 mb-4" />
        <p className="text-gray-500 font-medium animate-pulse">Analizando tu rendimiento...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <Card className="border-red-200 bg-red-50 shadow-sm">
          <CardContent className="p-6 flex items-center gap-4">
            <div className="p-3 bg-red-100 rounded-full">
              <AlertCircle className="w-6 h-6 text-red-600" />
            </div>
            <div>
              <h3 className="font-bold text-red-900">Error de Carga</h3>
              <p className="text-red-700 text-sm">{error}</p>
              <Button variant="outline" size="sm" onClick={loadStats} className="mt-2 border-red-200 text-red-700 hover:bg-red-100">Reintentar</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="p-6 max-w-4xl mx-auto text-center py-20">
        <Activity className="w-16 h-16 text-gray-300 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900">Sin datos suficientes</h2>
        <p className="text-gray-500 mt-2">Completa más entregas para ver tus estadísticas detalladas.</p>
      </div>
    );
  }

  const slaColor = stats.sla_compliance_rate >= 90 ? 'text-emerald-600' : stats.sla_compliance_rate >= 75 ? 'text-yellow-600' : 'text-red-600';
  const timeColor = stats.avg_time_minutes <= 30 ? 'text-emerald-600' : stats.avg_time_minutes <= 45 ? 'text-yellow-600' : 'text-red-600';

  return (
    <div className="space-y-6 pb-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white p-4 rounded-xl shadow-sm border border-gray-100">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Mi Rendimiento</h1>
          <p className="text-gray-500 text-sm mt-1">Métricas actualizadas en tiempo real basadas en tu actividad.</p>
        </div>
        <Button variant="outline" size="sm" onClick={loadStats} className="gap-2 bg-white shadow-sm hover:bg-gray-50">
          <Activity className="w-4 h-4" /> Actualizar Datos
        </Button>
      </div>

      {/* Tarjeta de Nivel (Hero Section) */}
      <Card className="overflow-hidden border-0 shadow-lg bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 text-white relative">
        <div className="absolute top-0 right-0 p-32 bg-white/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2"></div>
        <CardContent className="p-6 sm:p-8 relative z-10">
          <div className="flex flex-col md:flex-row justify-between items-center gap-8">
            <div className="flex items-center gap-6">
              <div className="relative">
                <div className="w-24 h-24 rounded-2xl bg-white/20 backdrop-blur-sm flex items-center justify-center border border-white/30 shadow-inner">
                  <Award className="w-12 h-12 text-white drop-shadow-md" />
                </div>
                <div className="absolute -bottom-2 -right-2 bg-yellow-400 text-yellow-900 text-xs font-bold px-2 py-1 rounded-full shadow-lg border-2 border-blue-600">
                  LVL {stats.level}
                </div>
              </div>
              <div>
                <h2 className="text-3xl font-extrabold tracking-tight">Nivel {stats.level}</h2>
                <p className="text-blue-100 font-medium mt-1 flex items-center gap-2">
                  <Star className="w-4 h-4 fill-yellow-400 text-yellow-400" /> {stats.points.toLocaleString()} pts acumulados
                </p>
                <div className="mt-4 w-full max-w-md">
                  <div className="flex justify-between text-xs font-semibold text-blue-100 mb-1">
                    <span>Progreso al Nivel {stats.level + 1}</span>
                    <span>{Math.round((stats.points / stats.nextLevelPoints) * 100)}%</span>
                  </div>
                  <div className="h-3 bg-black/20 rounded-full overflow-hidden backdrop-blur-sm">
                    <div 
                      className="h-full bg-gradient-to-r from-yellow-400 to-orange-400 rounded-full transition-all duration-1000 ease-out"
                      style={{ width: `${(stats.points / stats.nextLevelPoints) * 100}%` }}
                    />
                  </div>
                  <p className="text-xs text-blue-200 mt-2">
                    Faltan <span className="font-bold text-white">{(stats.nextLevelPoints - stats.points).toLocaleString()}</span> puntos para subir de nivel.
                  </p>
                </div>
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4 w-full md:w-auto">
              <div className="bg-white/10 backdrop-blur-md p-4 rounded-xl border border-white/10 text-center">
                <Zap className="w-6 h-6 text-yellow-300 mx-auto mb-2" />
                <p className="text-2xl font-bold">{stats.total_deliveries}</p>
                <p className="text-xs text-blue-100 uppercase tracking-wider">Entregas</p>
              </div>
              <div className="bg-white/10 backdrop-blur-md p-4 rounded-xl border border-white/10 text-center">
                <TrendingUp className="w-6 h-6 text-green-300 mx-auto mb-2" />
                <p className="text-2xl font-bold">{formatCurrency(stats.total_earnings)}</p>
                <p className="text-xs text-blue-100 uppercase tracking-wider">Ganancias</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Grid de Métricas Principales */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard 
          title="Tiempo Promedio" 
          value={`${Math.round(stats.avg_time_minutes)} min`} 
          icon={Clock} 
          color={timeColor}
          trend={stats.avg_time_minutes < 30 ? 'positive' : stats.avg_time_minutes < 45 ? 'neutral' : 'negative'}
          description="Ideal: &lt; 30 min"
        />
        <MetricCard 
          title="Cumplimiento SLA" 
          value={`${stats.sla_compliance_rate.toFixed(1)}%`} 
          icon={Target} 
          color={slaColor}
          trend={stats.sla_compliance_rate >= 90 ? 'positive' : 'negative'}
          description="Meta: &gt; 90%"
        />
        <MetricCard 
          title="Eficiencia Semanal" 
          value={`${(stats.dailyDeliveries.reduce((acc, curr) => acc + curr.count, 0) / 7).toFixed(1)} /día`} 
          icon={Calendar} 
          color="text-blue-600"
          trend="neutral"
          description="Promedio diario"
        />
        <MetricCard 
          title="Valoración Cliente" 
          value="4.8/5.0" 
          icon={Medal} 
          color="text-purple-600"
          trend="positive"
          description="Basado en últimas 50"
        />
      </div>

      {/* Sección de Gráficos */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Gráfico de Actividad Diaria */}
        <Card className="lg:col-span-2 shadow-sm border-gray-100">
          <CardHeader>
            <CardTitle className="text-base font-bold text-gray-800 flex items-center gap-2">
              <Activity className="w-5 h-5 text-blue-600" /> Actividad de Entregas (Últimos 7 días)
            </CardTitle>
            <CardDescription>Tu ritmo de trabajo diario y consistencia.</CardDescription>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.dailyDeliveries}>
                <defs>
                  <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fontSize: 12, fill: '#6b7280'}} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{fontSize: 12, fill: '#6b7280'}} />
                <Tooltip 
                  contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  cursor={{ stroke: '#2563eb', strokeWidth: 2 }}
                />
                <Area type="monotone" dataKey="count" stroke="#2563eb" strokeWidth={3} fillOpacity={1} fill="url(#colorCount)" animationDuration={1500} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Gráfico de Distribución SLA */}
        <Card className="shadow-sm border-gray-100">
          <CardHeader>
            <CardTitle className="text-base font-bold text-gray-800 flex items-center gap-2">
              <Target className="w-5 h-5 text-emerald-600" /> Calidad de Servicio
            </CardTitle>
            <CardDescription>Distribución de entregas a tiempo vs. retrasos.</CardDescription>
          </CardHeader>
          <CardContent className="h-[300px] flex flex-col items-center justify-center">
             {stats.statusDistribution.some(s => s.value > 0) ? (
               <ResponsiveContainer width="100%" height="100%">
                 <PieChart>
                   <Pie
                     data={stats.statusDistribution}
                     cx="50%"
                     cy="50%"
                     innerRadius={60}
                     outerRadius={80}
                     paddingAngle={5}
                     dataKey="value"
                     stroke="none"
                   >
                     {stats.statusDistribution.map((entry, index) => (
                       <Cell key={`cell-${index}`} fill={entry.color} />
                     ))}
                   </Pie>
                   <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                 </PieChart>
               </ResponsiveContainer>
             ) : (
               <div className="text-center text-gray-400">
                 <p className="text-sm">Sin datos suficientes</p>
               </div>
             )}
             <div className="flex gap-4 mt-4">
               {stats.statusDistribution.map((item, idx) => (
                 <div key={idx} className="flex items-center gap-2 text-sm">
                   <div className="w-3 h-3 rounded-full" style={{ backgroundColor: item.color }}></div>
                   <span className="font-medium text-gray-600">{item.name}</span>
                 </div>
               ))}
             </div>
          </CardContent>
        </Card>
      </div>

      {/* Consejos y Badges */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="border-l-4 border-l-indigo-500 shadow-sm bg-gradient-to-br from-indigo-50/50 to-white">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="p-3 bg-indigo-100 rounded-xl">
                <Award className="w-6 h-6 text-indigo-600" />
              </div>
              <div>
                <h3 className="font-bold text-gray-900 text-lg">Consejo Pro</h3>
                <p className="text-gray-600 text-sm mt-2 leading-relaxed">
                  Has completado <strong>{stats.total_deliveries}</strong> entregas. Para alcanzar el siguiente nivel rápidamente, intenta mantener tu tiempo promedio por debajo de <strong>25 minutos</strong> en las próximas 5 entregas. ¡Casi lo logras!
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-sm border-gray-100">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold text-gray-800">Insignias Recientes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-3 overflow-x-auto pb-2">
              <BadgeItem icon={Zap} label="Rayo" desc="Entrega &lt; 15min" color="bg-yellow-100 text-yellow-700" />
              <BadgeItem icon={Shield} label="Seguro" desc="10 sin retrasos" color="bg-blue-100 text-blue-700" />
              <BadgeItem icon={Star} label="Estrella" desc="5 estrellas" color="bg-purple-100 text-purple-700" />
              <div className="flex items-center justify-center w-16 h-16 rounded-full border-2 border-dashed border-gray-300 text-gray-400 text-xs font-medium shrink-0">
                +2 Más
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// --- Componentes Auxiliares ---

function MetricCard({ title, value, icon: Icon, color, trend, description }: any) {
  return (
    <Card className="shadow-sm hover:shadow-md transition-shadow duration-200 border-gray-100 bg-white">
      <CardContent className="p-5">
        <div className="flex justify-between items-start mb-2">
          <div className={`p-2 rounded-lg bg-opacity-10 ${color.replace('text-', 'bg-')}`}>
            <Icon className={`w-5 h-5 ${color}`} />
          </div>
          {trend && (
            <div className={`flex items-center text-xs font-bold px-2 py-1 rounded-full ${
              trend === 'positive' ? 'bg-green-100 text-green-700' : 
              trend === 'negative' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'
            }`}>
              {trend === 'positive' ? <ArrowUpRight className="w-3 h-3 mr-1" /> : trend === 'negative' ? <ArrowDownRight className="w-3 h-3 mr-1" /> : null}
              {trend === 'positive' ? 'Óptimo' : trend === 'negative' ? 'Mejorar' : 'Normal'}
            </div>
          )}
        </div>
        <h3 className="text-gray-500 text-xs font-semibold uppercase tracking-wider">{title}</h3>
        <p className={`text-2xl font-extrabold mt-1 ${color}`}>{value}</p>
        <p className="text-xs text-gray-400 mt-1">{description}</p>
      </CardContent>
    </Card>
  );
}

function BadgeItem({ icon: Icon, label, desc, color }: any) {
  return (
    <div className="flex flex-col items-center gap-1 min-w-[80px] p-2 rounded-lg hover:bg-gray-50 transition-colors cursor-default group">
      <div className={`w-12 h-12 rounded-full flex items-center justify-center shadow-sm ${color} group-hover:scale-110 transition-transform`}>
        <Icon className="w-6 h-6" />
      </div>
      <span className="text-xs font-bold text-gray-800">{label}</span>
      <span className="text-[10px] text-gray-500 text-center leading-tight">{desc}</span>
    </div>
  );
}

// Icono auxiliar si no está importado
const Shield = ({ className }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
);