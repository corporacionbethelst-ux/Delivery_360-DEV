'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { alertService, Alert } from '@/services/alert.service';
import { deliveryService, Delivery } from '@/services/delivery.service';
import { orderService, Order } from '@/services/order.service';
import { riderService } from '@/services/rider.service';
import { shiftService, Shift } from '@/services/shift.service';
import { Clock, AlertTriangle, MapPin, Activity, Users, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

// Función auxiliar para extraer datos correctamente independientemente del formato de respuesta
// Esto soluciona el error "Argument of type 'DeliveryListResponse' is not assignable..."
const extractData = <T,>(result: PromiseSettledResult<any>): T[] => {
  if (result.status === 'fulfilled') {
    const value = result.value;
    // Si la respuesta es un objeto con propiedad 'data' (común en Axios o clientes fetch envueltos)
    if (value && typeof value === 'object' && Array.isArray(value.data)) {
      return value.data;
    }
    // Si la respuesta es directamente el array
    if (Array.isArray(value)) {
      return value;
    }
  }
  return [];
};

export default function OperatorDashboard() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [activeShift, setActiveShift] = useState<Shift | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState({ deliveriesToday: 0, pendingOrders: 0, activeRiders: 0 });
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false); // Estado para el botón de actualizar
  const [error, setError] = useState<string | null>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    const allowedRoles = ['OPERADOR', 'GERENTE', 'SUPERADMIN'];
    if (!allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    loadData();
  }, [user, isAuthenticated, router, isMounted]);

  const isToday = (value?: string | null) => {
    if (!value) return false;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return false;
    return date.toDateString() === new Date().toDateString();
  };

  const loadData = async () => {
    // Si es un refresco manual, activamos el estado de carga específico, si es inicial usamos el general
    if (!loading) setIsRefreshing(true);
    else setLoading(true);
    
    setError(null);
    try {
      const [ordersResult, deliveriesResult, shiftsResult, alertsResult, ridersResult] = await Promise.allSettled([
        orderService.getAll({ limit: 100 }),
        deliveryService.getAll({ limit: 100 }),
        shiftService.getAll({ limit: 100 }),
        alertService.getAll({ status: 'UNREAD', limit: 5 }),
        riderService.listRiders({ is_online: true, status_filter: 'ACTIVO' }),
      ]);

      // Extraemos los datos de forma segura usando la función auxiliar
      const orders: Order[] = extractData<Order>(ordersResult);
      const deliveries: Delivery[] = extractData<Delivery>(deliveriesResult);
      const shifts: Shift[] = extractData<Shift>(shiftsResult);
      const alerts: Alert[] = extractData<Alert>(alertsResult);
      const riders = extractData<any>(ridersResult);

      // Verificamos si hubo errores críticos en alguna llamada
      const results = [ordersResult, deliveriesResult, shiftsResult, alertsResult, ridersResult];
      const hasErrors = results.some(result => result.status === 'rejected');

      if (hasErrors) {
        console.warn('Algunos módulos del dashboard no pudieron cargarse completamente.');
        // No establecemos error bloqueante si tenemos al menos algunos datos, pero podrías mostrar un toast
      }

      // Lógica de negocio segura (verificando que sean arrays antes de operar)
      const active = shifts.find(s => s.status === 'ACTIVO') ?? shifts.find(s => s.status === 'PLANIFICADO') ?? null;
      setActiveShift(active);
      setRecentAlerts(alerts);

      setStats({
        deliveriesToday: Array.isArray(deliveries) ? deliveries.filter(d => isToday(d.completed_at ?? d.created_at)).length : 0,
        pendingOrders: Array.isArray(orders) ? orders.filter(o => o.status === 'PENDIENTE' || !o.assigned_rider_id).length : 0,
        activeRiders: Array.isArray(riders) ? riders.length : 0,
      });

    } catch (err) {
      console.error('Error crítico cargando dashboard:', err);
      setError('No se pudo conectar con el servidor de operaciones.');
      setActiveShift(null);
      setRecentAlerts([]);
      setStats({ deliveriesToday: 0, pendingOrders: 0, activeRiders: 0 });
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  const handleRefresh = async () => {
    await loadData();
  };

  if (!isMounted || !isAuthenticated || !user || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Panel de Operaciones</h1>
            <p className="text-gray-500">Supervisión en tiempo real de turnos e incidencias.</p>
          </div>
          <div className="flex gap-2">
            {/* Botón Actualizar Agregado */}
            <Button 
              variant="outline" 
              onClick={handleRefresh} 
              disabled={isRefreshing}
              className="gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              {isRefreshing ? 'Actualizando...' : 'Actualizar'}
            </Button>
            <Button onClick={() => router.push('/operator/live-map')} className="bg-blue-600 hover:bg-blue-700 shadow-sm">
              <MapPin className="w-4 h-4 mr-2" /> Ver Mapa en Vivo
            </Button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex justify-between items-center">
            <span>{error}</span>
            <Button variant="ghost" size="sm" onClick={loadData} className="text-red-700 hover:bg-red-100">Reintentar</Button>
          </div>
        )}

        {/* KPIs Rápidos */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card className="border-l-4 border-l-blue-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Entregas Hoy</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.deliveriesToday}</div>
              <p className="text-xs text-green-600 flex items-center mt-1">
                <RefreshCw className="w-3 h-3 mr-1" /> Datos en vivo
              </p>
            </CardContent>
          </Card>
          
          <Card className="border-l-4 border-l-yellow-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Pendientes</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.pendingOrders}</div>
              <p className="text-xs text-gray-500 mt-1">Asignación requerida</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-purple-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Repartidores Activos</CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.activeRiders}</div>
              <p className="text-xs text-gray-500 mt-1">En turno actual</p>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Widget: Turno Actual */}
          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-blue-600" /> Turno Actual
              </CardTitle>
            </CardHeader>
            <CardContent>
              {activeShift ? (
                <div className="space-y-4">
                  <div className="flex justify-between items-center p-3 bg-blue-50 rounded-lg border border-blue-100">
                    <div>
                      <p className="font-bold text-blue-900">{activeShift.rider_name}</p>
                      <p className="text-xs text-blue-700">ID: {activeShift.id}</p>
                    </div>
                    <Badge className="bg-green-100 text-green-800 border-green-200">
                      {activeShift.status}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-gray-500">Inicio</p>
                      <p className="font-medium">{new Date(activeShift.start_time).toLocaleTimeString()}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">Duración</p>
                      <p className="font-medium">
                        {Math.floor((Date.now() - new Date(activeShift.start_time).getTime()) / 60000)} min
                      </p>
                    </div>
                  </div>
                  <Button variant="outline" className="w-full mt-2" size="sm" onClick={() => router.push('/operator/shifts')}>
                    Gestionar Turno
                  </Button>
                </div>
              ) : (
                <p className="text-gray-500 text-center py-4">No hay turnos activos actualmente.</p>
              )}
            </CardContent>
          </Card>

          {/* Widget: Alertas Críticas */}
          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-red-600" /> Alertas Recientes
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {recentAlerts.length === 0 ? (
                  <p className="text-gray-500 text-center py-4">Todo bajo control.</p>
                ) : (
                  recentAlerts.map(alert => (
                    <div key={alert.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg border border-gray-100 hover:bg-gray-100 transition-colors cursor-pointer"
                         onClick={() => router.push('/operator/alerts')}>
                      <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                        alert.status === 'UNREAD' ? 'bg-red-500 animate-pulse' : 'bg-yellow-500'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{alert.title}</p>
                        <p className="text-xs text-gray-500">
                          {new Date(alert.createdAt).toLocaleTimeString()} • {alert.type}
                        </p>
                      </div>
                      <Badge variant="outline" className="text-xs shrink-0">
                        {alert.status}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
              {recentAlerts.length > 0 && (
                <Button variant="link" className="w-full text-blue-600 mt-2" onClick={() => router.push('/operator/alerts')}>
                  Ver todas las alertas
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}