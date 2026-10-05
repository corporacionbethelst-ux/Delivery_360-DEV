'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { 
  MapPin, Truck, Search, RefreshCw, Clock, Phone, Package, AlertCircle, Play, Pause
} from 'lucide-react';
import { riderService } from '@/services/rider.service';
import { orderService } from '@/services/order.service';
import { DeliveryMap, MapRider, MapOrder } from '@/components/maps/DeliveryMap';
import dynamic from 'next/dynamic';

// Feature-flag provider: Google Maps se carga SOLO si NEXT_PUBLIC_MAP_PROVIDER=google_maps.
// LiveTrackingMap es tolerante: si @react-google-maps/api o la API key faltan, reenvía a Leaflet.
const GoogleTrackingMap = dynamic(
  () => import('@/components/maps/LiveTrackingMap'),
  { ssr: false, loading: () => <div className="h-full w-full animate-pulse bg-slate-200" /> }
);
import { trackingService } from '@/services/tracking.service';
import { useTrackingWebSocket } from '@/hooks/useTrackingWebSocket';

// ============================================================
// FEATURE FLAGS — Fase 8 (Mapas & Tracking)
//   NEXT_PUBLIC_MAP_PROVIDER: 'leaflet' (default) | 'google_maps'
//     Google Maps exige @react-google-maps/api + NEXT_PUBLIC_GOOGLE_MAPS_API_KEY.
//     Sin esos requisitos instalados, se degrada elegantemente a Leaflet.
//   NEXT_PUBLIC_TRACKING_WS: 'true' (default) | 'false'
//     false => solo polling REST legacy (modo compatibilidad).
// ============================================================
const MAP_PROVIDER = (process.env.NEXT_PUBLIC_MAP_PROVIDER || 'leaflet').toLowerCase();
const WS_ACTIVE = (process.env.NEXT_PUBLIC_TRACKING_WS || 'true').toLowerCase() !== 'false';

/** Fusiona posiciones del WebSocket sobre la lista base (polling REST). */
function mergeWsPositions(
  base: MapRider[],
  positions: { riderId: string; lat: number; lng: number }[]
): MapRider[] {
  if (!positions.length) return base;
  const byId = new Map(positions.map((pos) => [pos.riderId, pos]));
  const merged = base.map((r) => {
    const live = byId.get(r.id);
    if (!live) return r;
    return {
      ...r,
      lat: live.lat,
      lng: live.lng,
      lastUpdate: new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    };
  });
  // Riders nuevos reportados por WS pero ausentes en el snapshot REST
  for (const pos of positions) {
    if (!base.some((r) => r.id === pos.riderId)) {
      merged.push({
        id: pos.riderId,
        name: 'Repartidor',
        lat: pos.lat,
        lng: pos.lng,
        status: 'ONLINE',
        lastUpdate: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }),
      });
    }
  }
  return merged;
}

export default function LiveMapPage() {
  const [isLoadingInitial, setIsLoadingInitial] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState<'ALL' | 'ONLINE' | 'BUSY'>('ALL');
  const [onlineWithoutLocation, setOnlineWithoutLocation] = useState(0);
  
  // Estado para controlar la simulación
  const [isSimulationActive, setIsSimulationActive] = useState(false);
  
  const [riders, setRiders] = useState<MapRider[]>([]);
  const [orders, setOrders] = useState<MapOrder[]>([]);
  // === FASE 8: métricas del endpoint nativo de tracking (KPIs en vivo) ===
  const [liveStats, setLiveStats] = useState<{ activeCount: number; onlineTotal: number; staleOver15Min: number } | null>(null);

  // === FASE 8: WebSocket real-time (canal 'dashboard') ===
  // Los POSITION_UPDATE del WS sobrescriben las posiciones del polling.
  // Si el WS falla o WS_ACTIVE=false, el polling REST sigue funcionando (fallback).
  const {
    positions: wsPositions,
    isConnected: wsConnected,
    latencyMs: wsLatency,
    error: wsError,
    reconnect: wsReconnect,
  } = useTrackingWebSocket('dashboard', { enabled: WS_ACTIVE });

  // Función principal de carga de datos
  const fetchData = useCallback(async (isManual = false, simulateMovement = false) => {
    if (isManual) setIsRefreshing(true);
    
    try {
      // 1. Cargar Repartidores
      const ridersData = await riderService.getAll();
      
      const hasValidLocation = (r: any): boolean => {
        const lat = Number(r.last_lat);
        const lng = Number(r.last_lng);
        return Number.isFinite(lat) && Number.isFinite(lng) && lat !== 0 && lng !== 0;
      };

      setOnlineWithoutLocation(ridersData.filter(r => r.is_online === true && !hasValidLocation(r)).length);

      let mappedRiders: MapRider[] = ridersData
        .filter(hasValidLocation)
        .map(r => {
          const isOnline = r.is_online === true;
          const riderAny = r as any; 
          const hasActiveOrder = !!riderAny.current_order_id;

          let status: 'ONLINE' | 'BUSY' | 'OFFLINE' = 'OFFLINE';
          if (isOnline) {
            status = hasActiveOrder ? 'BUSY' : 'ONLINE';
          }

          return {
            id: r.id,
            name: `${r.first_name || ''} ${r.last_name || ''}`.trim() || 'Repartidor',
            lat: Number(r.last_lat),
            lng: Number(r.last_lng),
            status: status,
            lastUpdate: r.last_location_at 
              ? new Date(r.last_location_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) 
              : '--:--',
            orderId: riderAny.current_order_id || undefined,
            phone: r.phone ?? undefined 
          };
        });
      
      // LÓGICA DE SIMULACIÓN DE MOVIMIENTO (Solo si está activo)
      if (simulateMovement && mappedRiders.length > 0) {
        mappedRiders = mappedRiders.map(rider => {
          // Generar pequeño desplazamiento aleatorio (aprox 10-30 metros)
          const latOffset = (Math.random() - 0.5) * 0.0004; 
          const lngOffset = (Math.random() - 0.5) * 0.0004;
          
          return {
            ...rider,
            lat: parseFloat((rider.lat + latOffset).toFixed(6)),
            lng: parseFloat((rider.lng + lngOffset).toFixed(6))
          };
        });
        // NOTA: En simulación real, aquí enviaríamos el update al backend.
        // Para solo visualizar, actualizamos el estado local directamente.
        setRiders(mappedRiders);
      } else {
        setRiders(mappedRiders);
      }

      // 2. Cargar Órdenes Activas
      const ordersData = await orderService.getAll({ limit: 50 });
      const activeStatuses = ['EN_RUTA', 'PENDIENTE', 'ASIGNADO', 'EN_CAMINO', 'EN_RECOLECCION'];
      
      const mappedOrders: MapOrder[] = ordersData
        .filter(o => {
          const lat = Number((o as any).delivery_latitude || (o as any).delivery_lat);
          const lng = Number((o as any).delivery_longitude || (o as any).delivery_lng);
          return activeStatuses.includes(o.status) && !isNaN(lat) && !isNaN(lng) && lat !== 0 && lng !== 0;
        })
        .map(o => ({
          id: o.external_id || o.id,
          lat: Number((o as any).delivery_latitude || (o as any).delivery_lat),
          lng: Number((o as any).delivery_longitude || (o as any).delivery_lng),
          status: o.status,
          customer: o.customer_name || 'Cliente'
        }));
      
      setOrders(mappedOrders);

      // 3. FASE 8: KPIs del endpoint nativo de tracking (si falla, seguimos con los legacy)
      try {
        const live = await trackingService.getActiveRiders();
        setLiveStats(live.stats);
      } catch {
        /* endpoint no disponible aún: mantener fallback */
      }

    } catch (error) {
      console.error('❌ Error cargando datos del mapa:', error);
      // No detenemos la app si falla una petición, solo logueamos
    } finally {
      setIsLoadingInitial(false);
      setIsRefreshing(false);
    }
  }, []);

  // === FASE 8: fusión de posiciones en tiempo real (WS) sobre el snapshot REST ===
  useEffect(() => {
    if (!WS_ACTIVE || wsPositions.length === 0) return;
    setRiders((prev) => mergeWsPositions(prev, wsPositions));
  }, [wsPositions]);

  useEffect(() => {
    // Carga inicial
    fetchData();

    // Polling como FALLBACK: cada 10s con WS desconectado/legacy,
    // cada 60s cuando el WebSocket está sano (el WS entrega deltas <1s).
    const pollMs = WS_ACTIVE ? 60000 : 10000;
    const interval = setInterval(() => {
      fetchData(false, false);
    }, pollMs);

    return () => clearInterval(interval);
  }, [fetchData]);

  // Efecto separado para la simulación de movimiento rápido (cada 2s)
  useEffect(() => {
    let simInterval: NodeJS.Timeout;

    if (isSimulationActive) {
      simInterval = setInterval(() => {
        // Ejecutamos fetchData pero le decimos que aplique movimiento local
        // Nota: Para una simulación perfecta sin llamar al backend, 
        // podríamos manipular el estado 'riders' directamente aquí.
        // Pero para mantener consistencia, llamamos a la lógica de movimiento dentro de fetchData
        // o mejor aún, manipulamos el estado directamente aquí para evitar llamadas API innecesarias:
        
        setRiders(prevRiders => prevRiders.map(rider => {
          const latOffset = (Math.random() - 0.5) * 0.0003;
          const lngOffset = (Math.random() - 0.5) * 0.0003;
          return {
            ...rider,
            lat: parseFloat((rider.lat + latOffset).toFixed(6)),
            lng: parseFloat((rider.lng + lngOffset).toFixed(6))
          };
        }));
      }, 2000); // Movimiento cada 2 segundos
    }

    return () => {
      if (simInterval) clearInterval(simInterval);
    };
  }, [isSimulationActive]);

  const filteredRiders = riders.filter(r => {
    const matchesSearch = r.name.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesFilter = filterStatus === 'ALL' || r.status === filterStatus;
    return matchesSearch && matchesFilter;
  });

  const handleContactRider = (phone: string) => {
    window.location.href = `tel:${phone}`;
  };

  if (isLoadingInitial) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 flex-col gap-4">
        <RefreshCw className="animate-spin h-12 w-12 text-blue-600" />
        <p className="text-gray-600 font-medium">Inicializando sistema de mapas...</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] bg-gray-50 overflow-hidden">
      {/* Header Superior */}
      <div className="p-4 border-b bg-white flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 shadow-sm z-20">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <MapPin className="w-6 h-6 text-blue-600" />
            Mapa en Vivo
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {riders.length} repartidores • {orders.length} órdenes activas
            {WS_ACTIVE && (
              <span
                className={`ml-2 inline-flex items-center gap-1 font-semibold ${wsConnected ? 'text-green-600' : 'text-amber-600'}`}
                title={wsError || 'Estado de la conexión WebSocket de tracking'}
              >
                <span className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-amber-500'}`} />
                {wsConnected
                  ? `EN VIVO${wsLatency != null ? ` (${wsLatency}ms)` : ''}`
                  : 'POLLING (WS caído)'}
              </span>
            )}
            {liveStats && !wsConnected && (
              <span className="ml-2 text-gray-500">
                • {liveStats.activeCount} activos · {liveStats.staleOver15Min} inactivos &gt;15min
              </span>
            )}
            {isSimulationActive && <span className="ml-2 text-red-500 font-bold animate-pulse">(SIMULACIÓN ACTIVA)</span>}
            {onlineWithoutLocation > 0 && (
              <span className="ml-2 text-amber-600 font-semibold">
                • {onlineWithoutLocation} online sin ubicación válida
              </span>
            )}
          </p>
        </div>
        
        <div className="flex items-center gap-2">
          <Button 
            variant={isSimulationActive ? "destructive" : "secondary"}
            size="sm" 
            onClick={() => setIsSimulationActive(!isSimulationActive)}
            className="gap-2"
            title="Activar simulación de movimiento (Solo Dev)"
          >
            {isSimulationActive ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            {isSimulationActive ? 'Detener Simulación' : 'Simular Movimiento'}
          </Button>

          <Button 
            onClick={() => fetchData(true)} 
            variant="outline" 
            size="sm" 
            disabled={isRefreshing}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Actualizando...' : 'Actualizar'}
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Sidebar */}
        <div className="w-80 bg-white border-r flex flex-col z-10 shadow-md absolute sm:relative h-full transition-transform transform translate-x-0">
          <div className="p-4 border-b space-y-4 bg-gray-50/50">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input 
                placeholder="Buscar repartidor..." 
                className="pl-9 h-9"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="flex gap-1 p-1 bg-gray-100 rounded-lg">
              {(['ALL', 'ONLINE', 'BUSY'] as const).map((status) => (
                <button
                  key={status}
                  onClick={() => setFilterStatus(status)}
                  className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-all ${
                    filterStatus === status ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {status === 'ALL' ? 'Todos' : status === 'ONLINE' ? 'Libres' : 'Ocupados'}
                </button>
              ))}
            </div>
          </div>
          
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
             {filteredRiders.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-400">
                <Truck className="w-12 h-12 mb-2 opacity-20" />
                <p className="text-sm">No hay repartidores coincidentes</p>
                {onlineWithoutLocation > 0 && (
                  <p className="text-xs text-amber-600 text-center mt-2 px-4">
                    {onlineWithoutLocation} online sin coordenadas válidas. Pídeles reconectar ubicación.
                  </p>
                )}
              </div>
            ) : (
              filteredRiders.map((rider) => (
                <Card key={rider.id} className="hover:border-blue-300 transition-colors cursor-default group">
                  <CardContent className="p-3 flex gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 border-2 ${
                      rider.status === 'ONLINE' ? 'bg-green-50 border-green-200 text-green-600' :
                      rider.status === 'BUSY' ? 'bg-blue-50 border-blue-200 text-blue-600' : 'bg-gray-50 border-gray-200 text-gray-400'
                    }`}>
                      <Truck className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between items-start mb-1">
                        <p className="font-semibold text-sm truncate text-gray-900">{rider.name}</p>
                        <Badge variant={rider.status === 'ONLINE' ? 'default' : 'secondary'} className="text-[10px] h-5 px-1.5">
                          {rider.status === 'ONLINE' ? 'Disponible' : 'En Ruta'}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                        <Clock className="w-3 h-3" /> {rider.lastUpdate}
                      </div>
                      {rider.orderId && (
                        <div className="flex items-center gap-1 text-xs text-blue-600 font-medium bg-blue-50 px-2 py-1 rounded inline-block">
                          <Package className="w-3 h-3" /> 
                          <span className="truncate max-w-[120px]">{rider.orderId}</span>
                        </div>
                      )}
                      {rider.phone && (
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          className="h-7 mt-1 text-xs gap-2 w-full justify-start px-0 hover:bg-transparent hover:text-blue-600"
                          onClick={() => handleContactRider(rider.phone!)}
                        >
                          <Phone className="w-3 h-3" /> Llamar
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </div>

        {/* Área del Mapa */}
        <div className="flex-1 relative bg-slate-200">
          {/* Ya no necesitamos el componente RiderSimulator separado, la lógica está arriba */}
          
          {MAP_PROVIDER === 'google_maps' ? (
            <GoogleTrackingMap
              center={[4.60971, -74.08175]}
              height="h-full"
              riders={riders.map((r) => ({
                id: r.id,
                first_name: r.name.split(' ')[0] || r.name,
                last_name: r.name.split(' ').slice(1).join(' '),
                status: r.status as any,
                lat: r.lat,
                lng: r.lng,
                isOnline: r.status !== 'OFFLINE',
              }))}
            />
          ) : (
            <DeliveryMap
              riders={riders}
              orders={orders}
              onContactRider={handleContactRider}
            />
          )}
        </div>
      </div>
    </div>
  );
}