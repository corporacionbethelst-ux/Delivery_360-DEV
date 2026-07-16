'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService } from '@/services/order.service';
import { deliveryService } from '@/services/delivery.service';
import { riderService } from '@/services/rider.service';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Bike, 
  Package, 
  Truck, 
  Users, 
  AlertCircle, 
  Clock, 
  MapPin, 
  ArrowRight,
  Loader2,
  RefreshCw
} from 'lucide-react';
import { formatCurrency } from '@/lib/formatters';

// Interfaces locales simplificadas para evitar conflictos de tipos externos
interface LocalOrder {
  id: string;
  external_id?: string;
  status: string;
  total_amount?: number;
  total?: number;
  customer_name?: string;
  created_at: string;
}

interface LocalDelivery {
  id: string;
  status: string;
  rider_name?: string;
  customer_name?: string;
  updated_at?: string;
  created_at: string;
}

interface LocalRider {
  id: string;
  first_name?: string;
  last_name?: string;
  is_online: boolean;
  status: string;
}

interface Stats {
  pendingOrders: number;
  activeDeliveries: number;
  onlineRiders: number;
  totalRevenueToday: number;
}

export default function OperatorDashboard() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Estados de datos
  const [stats, setStats] = useState<Stats>({
    pendingOrders: 0,
    activeDeliveries: 0,
    onlineRiders: 0,
    totalRevenueToday: 0,
  });
  
  const [recentOrders, setRecentOrders] = useState<LocalOrder[]>([]);
  const [activeDeliveriesList, setActiveDeliveriesList] = useState<LocalDelivery[]>([]);
  const [onlineRidersList, setOnlineRidersList] = useState<LocalRider[]>([]);

  // Helper para extraer items de respuestas paginadas o arrays directos
  const extractItems = (response: any): any[] => {
    if (Array.isArray(response)) return response;
    if (response && Array.isArray(response.items)) return response.items;
    if (response && Array.isArray(response.data)) return response.data;
    return [];
  };

  const loadData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    
    setError(null);

    try {
      // 1. Cargar Órdenes Pendientes
      // Usamos 'as any' en los params para evitar conflictos estrictos de tipos con el servicio
      const ordersRes = await orderService.getAll({ status: 'PENDIENTE', limit: 5 } as any);
      const orders = extractItems(ordersRes).slice(0, 5);
      setRecentOrders(orders);

      // 2. Cargar Entregas Activas
      const deliveriesRes = await deliveryService.getAll({ limit: 10 } as any);
      const allDeliveries = extractItems(deliveriesRes);
      const activeDeliveries = allDeliveries.filter((d: any) => 
        ['INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'EN_DESTINO'].includes(d.status)
      ).slice(0, 5);
      setActiveDeliveriesList(activeDeliveries);

      // 3. Cargar Riders (Filtramos en frontend para evitar problemas de params en el servicio)
      const ridersRes = await riderService.getAll(); 
      const allRiders = extractItems(ridersRes);
      const onlineRiders = allRiders.filter((r: any) => r.is_online === true).slice(0, 10);
      setOnlineRidersList(onlineRiders);

      // 4. Calcular Estadísticas
      setStats({
        pendingOrders: orders.length, // En una app real, esto vendría de un endpoint de stats
        activeDeliveries: activeDeliveries.length,
        onlineRiders: onlineRiders.length,
        totalRevenueToday: 0, // Placeholder hasta tener endpoint de finanzas
      });

    } catch (err: any) {
      console.error('Error cargando dashboard:', err);
      setError('No se pudieron cargar los datos del dashboard. Verifica tu conexión o permisos.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && user) {
      // Validar rol
      const allowedRoles = ['SUPERADMIN', 'GERENTE', 'OPERADOR'];
      if (!allowedRoles.includes(user.role)) {
        router.push('/unauthorized');
        return;
      }
      loadData();
    }
  }, [isAuthenticated, user, router]);

  if (!isAuthenticated || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[60vh]">
        <Loader2 className="h-12 w-12 animate-spin text-blue-600 mb-4" />
        <p className="text-gray-500">Cargando panel de control...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Panel de Operador</h1>
          <p className="text-gray-500">Monitor en tiempo real de operaciones</p>
        </div>
        <Button 
          variant="outline" 
          onClick={() => loadData(true)} 
          disabled={refreshing}
          className="gap-2"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Actualizar
        </Button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md flex items-center gap-2">
          <AlertCircle className="h-5 w-5" />
          {error}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard 
          title="Órdenes Pendientes" 
          value={stats.pendingOrders} 
          icon={Package} 
          color="text-yellow-600" 
          bg="bg-yellow-50"
          onClick={() => router.push('/operator/orders?status=PENDIENTE')}
        />
        <StatCard 
          title="Entregas Activas" 
          value={stats.activeDeliveries} 
          icon={Truck} 
          color="text-blue-600" 
          bg="bg-blue-50"
          onClick={() => router.push('/operator/deliveries')}
        />
        <StatCard 
          title="Riders Online" 
          value={stats.onlineRiders} 
          icon={Users} 
          color="text-green-600" 
          bg="bg-green-50"
          onClick={() => router.push('/operator/riders')}
        />
        <StatCard 
          title="Recaudo Hoy" 
          value={formatCurrency(stats.totalRevenueToday)} 
          icon={Clock} 
          color="text-purple-600" 
          bg="bg-purple-50"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Órdenes Recientes */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Package className="h-5 w-5 text-yellow-600" />
              Órdenes Pendientes
            </CardTitle>
            <Button variant="ghost" size="sm" onClick={() => router.push('/operator/orders')}>
              Ver todas <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            {recentOrders.length === 0 ? (
              <EmptyState message="No hay órdenes pendientes" />
            ) : (
              <div className="space-y-3">
                {recentOrders.map((order) => (
                  <div key={order.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-full bg-yellow-100 flex items-center justify-center text-yellow-700 font-bold">
                        #{order.external_id?.slice(-2) || '??'}
                      </div>
                      <div>
                        <p className="font-medium text-sm">Orden #{order.external_id || order.id.slice(-6)}</p>
                        <p className="text-xs text-gray-500">{order.customer_name || 'Cliente'}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-sm">{formatCurrency(order.total_amount || order.total || 0)}</p>
                      <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => router.push(`/operator/orders/${order.id}`)}>
                        Gestionar
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Riders Online */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Bike className="h-5 w-5 text-green-600" />
              Riders Activos
            </CardTitle>
            <Button variant="ghost" size="sm" onClick={() => router.push('/operator/riders')}>
              Ver todos <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            {onlineRidersList.length === 0 ? (
              <EmptyState message="No hay riders online actualmente" />
            ) : (
              <div className="space-y-3">
                {onlineRidersList.map((rider) => (
                  <div key={rider.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <div className="h-10 w-10 rounded-full bg-gray-200 flex items-center justify-center text-gray-600 font-bold">
                          {(rider.first_name?.[0] || '')}{(rider.last_name?.[0] || '')}
                        </div>
                        <span className="absolute bottom-0 right-0 h-3 w-3 bg-green-500 border-2 border-white rounded-full"></span>
                      </div>
                      <div>
                        <p className="font-medium text-sm">{rider.first_name} {rider.last_name}</p>
                        <p className="text-xs text-green-600 font-medium">En línea</p>
                      </div>
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {rider.status || 'Disponible'}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Entregas en Curso */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <MapPin className="h-5 w-5 text-blue-600" />
            Entregas en Progreso
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={() => router.push('/operator/deliveries')}>
            Ver mapa <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent>
          {activeDeliveriesList.length === 0 ? (
            <EmptyState message="No hay entregas activas en este momento" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 uppercase bg-gray-50">
                  <tr>
                    <th className="px-4 py-3">Estado</th>
                    <th className="px-4 py-3">Rider</th>
                    <th className="px-4 py-3">Cliente</th>
                    <th className="px-4 py-3 text-right">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {activeDeliveriesList.map((delivery) => (
                    <tr key={delivery.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                          {delivery.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-medium">{delivery.rider_name || 'No asignado'}</td>
                      <td className="px-4 py-3 text-gray-600">{delivery.customer_name || 'N/A'}</td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="outline" size="sm" onClick={() => router.push(`/operator/deliveries/${delivery.id}`)}>
                          Ver
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// Componentes Auxiliares
function StatCard({ title, value, icon: Icon, color, bg, onClick }: any) {
  return (
    <Card className={`cursor-pointer transition-shadow hover:shadow-md ${onClick ? 'hover:border-blue-300' : ''}`} onClick={onClick}>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-500">{title}</p>
            <p className="text-2xl font-bold mt-1">{value}</p>
          </div>
          <div className={`p-3 rounded-full ${bg} ${color}`}>
            <Icon className="h-6 w-6" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-8 text-gray-500 text-sm">
      <p>{message}</p>
    </div>
  );
}