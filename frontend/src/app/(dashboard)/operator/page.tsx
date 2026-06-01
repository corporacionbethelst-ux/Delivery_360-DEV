'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore'; // ✅ CORRECCIÓN: Usar Zustand
import { Clock, AlertTriangle, MapPin, Activity, TrendingUp, Users, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface Shift {
  id: string;
  status: string;
  start_time: string;
  end_time?: string;
  rider_name?: string;
}

interface Alert {
  id: string;
  title: string;
  status: string;
  created_at: string;
  type: string;
}

export default function OperatorDashboard() {
  const router = useRouter();
  // ✅ CORRECCIÓN: Obtener datos del store
  const { user, isAuthenticated } = useAuthStore();
  
  const [activeShift, setActiveShift] = useState<Shift | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState({ deliveries: 0, pending: 0, riders: 0 });
  const [loading, setLoading] = useState(true);
  const [isMounted, setIsMounted] = useState(false);

  // Efecto para evitar hidratación incorrecta
  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    // ✅ Seguridad: Verificar montaje, autenticación y rol
    if (!isMounted || !isAuthenticated || !user) return;

    const allowedRoles = ['OPERADOR', 'GERENTE', 'SUPERADMIN'];
    if (!allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    loadData();
  }, [user, isAuthenticated, router, isMounted]);

  const loadData = async () => {
    setLoading(true);
    try {
      // Simulación de carga de datos (Reemplazar con llamadas reales a shiftService/alertService)
      await new Promise(r => setTimeout(r, 800));

      // Mock Shift
      setActiveShift({
        id: 'SHIFT-001',
        status: 'ACTIVO',
        start_time: new Date().toISOString(),
        rider_name: 'Turno Mañana'
      });

      // Mock Alerts
      setRecentAlerts([
        { id: '1', title: 'Retraso en Zona Norte', status: 'NUEVA', created_at: new Date().toISOString(), type: 'RETRASO_SLA' },
        { id: '2', title: 'Falla GPS Repartidor #42', status: 'EN_PROCESO', created_at: new Date(Date.now() - 3600000).toISOString(), type: 'FALLA_GPS' }
      ]);

      setStats({ deliveries: 24, pending: 3, riders: 12 });
    } catch (error) {
      console.error('Error loading dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  // ✅ Seguridad: Mostrar carga mientras se verifica autenticación
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
          <Button onClick={() => router.push('/operator/map')} className="bg-blue-600 hover:bg-blue-700 shadow-sm">
            <MapPin className="w-4 h-4 mr-2" /> Ver Mapa en Vivo
          </Button>
        </div>

        {/* KPIs Rápidos */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card className="border-l-4 border-l-blue-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Entregas Hoy</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.deliveries}</div>
              <p className="text-xs text-green-600 flex items-center mt-1">
                <TrendingUp className="w-3 h-3 mr-1" /> +15% vs ayer
              </p>
            </CardContent>
          </Card>
          
          <Card className="border-l-4 border-l-yellow-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Pendientes</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.pending}</div>
              <p className="text-xs text-gray-500 mt-1">Asignación requerida</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-purple-500 shadow-sm">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Repartidores Activos</CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.riders}</div>
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
                        alert.status === 'NUEVA' ? 'bg-red-500 animate-pulse' : 'bg-yellow-500'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{alert.title}</p>
                        <p className="text-xs text-gray-500">
                          {new Date(alert.created_at).toLocaleTimeString()} • {alert.type}
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