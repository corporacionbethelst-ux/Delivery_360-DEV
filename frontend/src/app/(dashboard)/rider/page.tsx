'use client';

import React, { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore'; // ✅ CORRECCIÓN: Usar Zustand
import { DollarSign, Package, MapPin, TrendingUp, Clock, Bike, AlertCircle, Wifi, WifiOff, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency } from '@/lib/formatters';
import { riderService } from '@/services/rider.service';

interface Order {
  id: string;
  status: string;
  delivery_address: string;
  total_amount: number;
  created_at: string;
}

export default function RiderDashboard() {
  const router = useRouter();
  // ✅ CORRECCIÓN: Obtener datos del store
  const { user, isAuthenticated } = useAuthStore();
  
  const [earnings, setEarnings] = useState({ today: 0, week: 0, pending: 0 });
  const [nextDelivery, setNextDelivery] = useState<Order | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [isMounted, setIsMounted] = useState(false);
  
  // Estados para geolocalización
  const [riderId, setRiderId] = useState<string | null>(null);
  const [isOnline, setIsOnline] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [sendingLocation, setSendingLocation] = useState(false);
  
  // Usamos ref para el watchId para evitar problemas de cierre en efectos
  const watchIdRef = useRef<number | null>(null);

  // Efecto para evitar hidratación incorrecta
  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    // ✅ Seguridad: Verificar montaje, autenticación y rol
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== 'REPARTIDOR') {
      if (['SUPERADMIN', 'GERENTE'].includes(user.role)) router.push('/manager');
      else if (user.role === 'OPERADOR') router.push('/operator');
      else router.push('/login');
      return;
    }

    // Cargar perfil del rider para obtener su ID
    const initRiderData = async () => {
      try {
        const profile = await riderService.getProfile(); // Usamos getProfile que es estándar
        setRiderId(profile.id);
        
        // Si ya estaba "online" en la sesión anterior (opcional), reconectar
        // Por ahora empezamos offline por defecto al cargar la página
      } catch (error) {
        console.error('Error cargando perfil de repartidor:', error);
        setLocationError('No se pudo cargar el perfil de repartidor');
      }
    };

    initRiderData();

    // Cargar datos iniciales del dashboard
    const loadData = async () => {
      try {
        // Simulación de carga (Reemplazar con llamadas reales a servicios si existen)
        // const stats = await financialService.getRiderEarnings(); 
        await new Promise(r => setTimeout(r, 800));

        setEarnings({
          today: 45000,
          week: 280000,
          pending: 120000
        });

        // Simular próxima entrega (Reemplazar con orderService.getNextActive())
        setNextDelivery(null); // Inicialmente null, o datos reales si los hay
        
      } catch (error) {
        console.error('Error cargando datos del dashboard:', error);
      } finally {
        setLoadingData(false);
      }
    };

    loadData();
    
    // Limpieza al desmontar: detener geolocalización si está activa
    return () => {
      if (watchIdRef.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current);
      }
    };
  }, [user, isAuthenticated, router, isMounted]);

  // Función para enviar ubicación al backend
  const sendLocation = async (lat: number, lng: number) => {
    if (!riderId) return;
    
    try {
      setSendingLocation(true);
      await riderService.sendHeartbeat(riderId, lat, lng);
      setLocationError(null);
    } catch (error: any) {
      console.error('Error enviando ubicación:', error);
      setLocationError(error.response?.data?.detail || 'No se pudo actualizar la ubicación');
      setIsOnline(false);
    } finally {
      setSendingLocation(false);
    }
  };

  // Activar/Desactivar modo en línea
  const toggleOnlineMode = () => {
    if (isOnline) {
      // Desconectar
      if (watchIdRef.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      setIsOnline(false);
      
      if (riderId) {
        riderService.toggleOnline(riderId, false).catch(console.error);
      }
      return;
    }

    // Conectar
    if (!navigator.geolocation) {
      setLocationError('La geolocalización no es soportada por este navegador');
      return;
    }

    if (!riderId) {
      setLocationError('Cargando perfil de repartidor...');
      return;
    }

    setLocationError(null);
    
    // Obtener posición inicial
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        sendLocation(latitude, longitude);
        setIsOnline(true);

        // Vigilar cambios de posición
        const id = navigator.geolocation.watchPosition(
          (pos) => {
            const { latitude, longitude } = pos.coords;
            sendLocation(latitude, longitude);
          },
          (err) => {
            console.error('Error de geolocalización:', err);
            setLocationError('Error al obtener ubicación. Verifica los permisos.');
            setIsOnline(false);
          },
          {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 5000
          }
        );
        watchIdRef.current = id;
      },
      (err) => {
        console.error('Error obteniendo posición inicial:', err);
        setLocationError('Permiso de ubicación denegado. Actívalo para recibir pedidos.');
      }
    );
  };

  // ✅ Seguridad: Mostrar carga mientras se verifica autenticación
  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin h-12 w-12 text-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Cargando panel de repartidor...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen pb-20">
      <div className="max-w-5xl mx-auto">
        {/* Header con Estado de Conexión */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Hola, {user.first_name} {user.last_name}</h1>
            <p className="text-gray-500 flex items-center gap-2">
              {isOnline ? (
                <>
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                  </span>
                  En línea - Recibiendo ubicaciones
                </>
              ) : (
                <>
                  <span className="inline-block h-3 w-3 rounded-full bg-gray-400"></span>
                  Desconectado
                </>
              )}
            </p>
          </div>
          
          <div className="flex gap-2">
            <Button 
              onClick={toggleOnlineMode}
              variant={isOnline ? "destructive" : "default"}
              disabled={sendingLocation && isOnline || !riderId}
              className={isOnline ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}
            >
              {sendingLocation && isOnline ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : isOnline ? (
                <WifiOff className="w-4 h-4 mr-2" />
              ) : (
                <Wifi className="w-4 h-4 mr-2" />
              )}
              {isOnline ? 'Desconectarse' : 'Conectarse'}
            </Button>
            
            <Button onClick={() => router.push('/rider/my-orders')} variant="outline">
              <Package className="w-4 h-4 mr-2" /> Mis Entregas
            </Button>
          </div>
        </div>

        {locationError && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-red-800">Error de Ubicación</h3>
              <p className="text-sm text-red-700">{locationError}</p>
            </div>
          </div>
        )}

        {/* Resumen Financiero */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card className="bg-gradient-to-br from-green-50 to-white border-green-200 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-green-800">Ganado Hoy</p>
                  <h3 className="text-3xl font-bold text-green-900 mt-1">{formatCurrency(earnings.today)}</h3>
                </div>
                <DollarSign className="w-6 h-6 text-green-600" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-green-700 flex items-center">
                <TrendingUp className="w-3 h-3 mr-1" /> +12% vs ayer
              </p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-blue-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Esta Semana</p>
                  <h3 className="text-2xl font-bold text-gray-900 mt-1">{formatCurrency(earnings.week)}</h3>
                </div>
                <Package className="w-6 h-6 text-blue-600" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">Total acumulado</p>
            </CardContent>
          </Card>

          <Card className="border-t-4 border-t-purple-500 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm font-medium text-gray-500">Por Cobrar</p>
                  <h3 className="text-2xl font-bold text-gray-900 mt-1">{formatCurrency(earnings.pending)}</h3>
                </div>
                <Clock className="w-6 h-6 text-purple-600" />
              </div>
            </CardHeader>
            <CardContent>
              <Button variant="link" className="p-0 h-auto text-xs text-purple-600 font-semibold" onClick={() => router.push('/rider/earnings')}>
                Solicitar retiro →
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Próxima Entrega */}
          <Card className="shadow-md border-l-4 border-l-blue-600">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MapPin className="w-5 h-5 text-blue-600" /> Próxima Entrega
              </CardTitle>
            </CardHeader>
            <CardContent>
              {nextDelivery ? (
                <div className="space-y-4">
                  <div className="flex justify-between items-start">
                    <div>
                      <Badge className="mb-2 bg-blue-100 text-blue-800 border-blue-200">{nextDelivery.status}</Badge>
                      <h3 className="font-bold text-lg text-gray-900">Orden #{nextDelivery.id}</h3>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-gray-500">Valor</p>
                      <p className="font-bold text-green-600">{formatCurrency(nextDelivery.total_amount)}</p>
                    </div>
                  </div>
                  
                  <div className="bg-gray-50 p-3 rounded-lg border border-gray-100">
                    <p className="text-xs text-gray-500 uppercase font-semibold mb-1">Dirección</p>
                    <p className="text-sm font-medium text-gray-900">{nextDelivery.delivery_address}</p>
                  </div>

                  <div className="flex gap-2">
                    <Button className="flex-1 bg-blue-600 hover:bg-blue-700" onClick={() => router.push(`/rider/my-orders/${nextDelivery.id}`)}>
                      Iniciar Ruta
                    </Button>
                    <Button 
                      variant="outline" 
                      size="icon" 
                      onClick={() => {
                        const address = encodeURIComponent(nextDelivery.delivery_address);
                        window.open(`https://www.google.com/maps/search/?api=1&query=${address}`, '_blank');
                      }}
                    >
                      <MapPin className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  <Bike className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No tienes entregas asignadas ahora mismo.</p>
                  <p className="text-xs mt-2">Conéctate y espera nuevas asignaciones.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Accesos Rápidos */}
          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle>Gestión Rápida</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <Button variant="outline" className="h-24 flex flex-col gap-2 hover:bg-green-50 hover:border-green-200" onClick={() => router.push('/rider/earnings')}>
                <DollarSign className="w-6 h-6 text-green-600" />
                <span className="text-sm font-medium">Mis Ganancias</span>
              </Button>
              <Button variant="outline" className="h-24 flex flex-col gap-2 hover:bg-blue-50 hover:border-blue-200" onClick={() => router.push('/rider/profile')}>
                <Bike className="w-6 h-6 text-blue-600" />
                <span className="text-sm font-medium">Mi Perfil</span>
              </Button>
              <Button variant="outline" className="h-24 flex flex-col gap-2 hover:bg-orange-50 hover:border-orange-200" onClick={() => router.push('/rider/notifications')}>
                <Clock className="w-6 h-6 text-orange-600" />
                <span className="text-sm font-medium">Notificaciones</span>
              </Button>
              <Button variant="outline" className="h-24 flex flex-col gap-2 hover:bg-purple-50 hover:border-purple-200" onClick={() => router.push('/rider/productivity')}>
                <TrendingUp className="w-6 h-6 text-purple-600" />
                <span className="text-sm font-medium">Productividad</span>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}