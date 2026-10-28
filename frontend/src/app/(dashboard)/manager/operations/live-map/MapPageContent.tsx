'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  MapPin,
  Truck,
  Search,
  RefreshCw,
  Clock,
  Phone,
  Package,
  AlertCircle,
  Play,
  Pause,
} from 'lucide-react';
import { DeliveryMap } from '@/components/maps/DeliveryMap';
import dynamic from 'next/dynamic';

// Feature-flag provider: Google Maps se carga SOLO si NEXT_PUBLIC_MAP_PROVIDER=google_maps.
// LiveTrackingMap es tolerante: si @react-google-maps/api o la API key faltan, reenvía a Leaflet.
const GoogleTrackingMap = dynamic(() => import('@/components/maps/LiveTrackingMap'), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-slate-200" />,
});
import { useTrackingWebSocket } from '@/hooks/useTrackingWebSocket';
import { useLiveMapData } from '@/hooks/useLiveMapData';
import { mergeMapPositions } from '@/lib/live-map-data';

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

export default function LiveMapPage() {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState<'ALL' | 'ONLINE' | 'BUSY'>('ALL');

  // Estado para controlar la simulación
  const [isSimulationActive, setIsSimulationActive] = useState(false);

  // === FASE 8: WebSocket real-time (canal 'dashboard') ===
  // REST y POSITION_UPDATE se combinan conservando la posición fechada más reciente.
  // Si el WS falla o WS_ACTIVE=false, el polling REST sigue funcionando (fallback).
  const {
    positions: wsPositions,
    isConnected: wsConnected,
    latencyMs: wsLatency,
    error: wsError,
    reconnect: wsReconnect,
  } = useTrackingWebSocket('dashboard', { enabled: WS_ACTIVE });

  const {
    riders: baseRiders,
    orders,
    onlineWithoutLocation,
    liveStats,
    isLoadingInitial,
    isRefreshing,
    error: mapError,
    accessDenied,
    fetchData,
    setRiders,
  } = useLiveMapData(wsConnected);
  const riders = useMemo(
    () =>
      accessDenied
        ? []
        : isSimulationActive
          ? baseRiders
          : mergeMapPositions(baseRiders, wsPositions),
    [baseRiders, wsPositions, isSimulationActive, accessDenied]
  );

  // Efecto separado para la simulación de movimiento rápido (cada 2s)
  useEffect(() => {
    let simInterval: NodeJS.Timeout;

    if (isSimulationActive) {
      simInterval = setInterval(() => {
        // La simulación explícita solo modifica la visualización local.
        setRiders((prevRiders) =>
          prevRiders.map((rider) => {
            const latOffset = (Math.random() - 0.5) * 0.0003;
            const lngOffset = (Math.random() - 0.5) * 0.0003;
            return {
              ...rider,
              lat: parseFloat((rider.lat + latOffset).toFixed(6)),
              lng: parseFloat((rider.lng + lngOffset).toFixed(6)),
            };
          })
        );
      }, 2000); // Movimiento cada 2 segundos
    }

    return () => {
      if (simInterval) clearInterval(simInterval);
    };
  }, [isSimulationActive, setRiders]);

  const filteredRiders = riders.filter((r) => {
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
      {mapError && (
        <div role="alert" className="px-4 py-2 bg-amber-50 text-amber-900 text-sm">
          {mapError}
        </div>
      )}
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
                <span
                  className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-amber-500'}`}
                />
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
            {isSimulationActive && (
              <span className="ml-2 text-red-500 font-bold animate-pulse">(SIMULACIÓN ACTIVA)</span>
            )}
            {onlineWithoutLocation > 0 && (
              <span className="ml-2 text-amber-600 font-semibold">
                • {onlineWithoutLocation} online sin ubicación válida
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={isSimulationActive ? 'destructive' : 'secondary'}
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
                    filterStatus === status
                      ? 'bg-white text-blue-600 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
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
                    {onlineWithoutLocation} online sin coordenadas válidas. Pídeles reconectar
                    ubicación.
                  </p>
                )}
              </div>
            ) : (
              filteredRiders.map((rider) => (
                <Card
                  key={rider.id}
                  className="hover:border-blue-300 transition-colors cursor-default group"
                >
                  <CardContent className="p-3 flex gap-3">
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 border-2 ${
                        rider.status === 'ONLINE'
                          ? 'bg-green-50 border-green-200 text-green-600'
                          : rider.status === 'BUSY'
                            ? 'bg-blue-50 border-blue-200 text-blue-600'
                            : 'bg-gray-50 border-gray-200 text-gray-400'
                      }`}
                    >
                      <Truck className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between items-start mb-1">
                        <p className="font-semibold text-sm truncate text-gray-900">{rider.name}</p>
                        <Badge
                          variant={rider.status === 'ONLINE' ? 'default' : 'secondary'}
                          className="text-[10px] h-5 px-1.5"
                        >
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
            <DeliveryMap riders={riders} orders={orders} onContactRider={handleContactRider} />
          )}
        </div>
      </div>
    </div>
  );
}
