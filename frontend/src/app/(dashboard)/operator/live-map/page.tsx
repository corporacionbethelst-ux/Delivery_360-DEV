'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { useRouter } from 'next/navigation';
import { Loader2, AlertTriangle, RefreshCw, Bike, MapPin } from 'lucide-react';
import { deliveryService } from '@/services/delivery.service';
import type { Delivery } from '@/types/delivery';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

// Nota: Asumimos que tienes un componente de mapa. Si usas react-leaflet o google maps, ajusta los imports.
// Para este ejemplo, simularemos un mapa o usaremos un placeholder si no hay librería de mapas instalada.
// Si tienes 'react-leaflet' instalado, descomenta y usa el componente LeafletMap.
// import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
// import 'leaflet/dist/leaflet.css';

export default function OperatorLiveMapPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  const [deliveries, setDeliveries] = useState<any[]>([]); // Usamos any[] temporalmente para flexibilidad
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const allowedRoles = ['SUPERADMIN', 'GERENTE', 'OPERADOR'];

  useEffect(() => {
    if (!isAuthenticated || !user || !allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    fetchDeliveries();
    
    // Polling cada 10 segundos para actualizaciones en vivo
    const interval = setInterval(fetchDeliveries, 10000);
    return () => clearInterval(interval);
  }, [isAuthenticated, user, router]);

  const fetchDeliveries = async () => {
    try {
      setLoading(true);
      // Obtenemos entregas activas
      const response = await deliveryService.getAll({ status: 'ACTIVE', limit: 100 });
      
      // Normalizamos los datos para asegurar que tengan lat/lng para el mapa
      const normalized = Array.isArray(response) ? response : (response as any).items || [];
      
      setDeliveries(normalized);
      setLastUpdated(new Date());
      setError(null);
    } catch (err: any) {
      console.error('Error fetching live deliveries:', err);
      setError('No se pudo cargar el mapa en tiempo real.');
    } finally {
      setLoading(false);
    }
  };

  // Filtramos solo las que tienen coordenadas válidas para el mapa
  const activeMarkers = useMemo(() => {
    return deliveries.filter((d) => {
      const lat = d.current_latitude ?? d.currentLatitude;
      const lng = d.current_longitude ?? d.currentLongitude;
      return lat !== null && lat !== undefined && lng !== null && lng !== undefined;
    });
  }, [deliveries]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETADA': return 'bg-green-100 text-green-800';
      case 'FALLIDA': return 'bg-red-100 text-red-800';
      case 'EN_ROUTE': 
      case 'EN_DESTINO': return 'bg-blue-100 text-blue-800';
      default: return 'bg-yellow-100 text-yellow-800';
    }
  };

  if (!isAuthenticated || !user) return null;

  return (
    <div className="p-6 h-screen flex flex-col bg-gray-50">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Mapa en Vivo</h1>
          <p className="text-sm text-gray-500">Seguimiento de repartidores y entregas activas.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">
            Actualizado: {lastUpdated.toLocaleTimeString()}
          </span>
          <Button variant="outline" size="sm" onClick={fetchDeliveries} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-4 min-h-0">
        {/* Lista Lateral */}
        <Card className="lg:col-span-1 overflow-hidden flex flex-col">
          <CardHeader className="py-3 border-b">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Bike className="w-4 h-4" /> Entregas Activas ({activeMarkers.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-y-auto flex-1">
            {loading && deliveries.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />
                Cargando...
              </div>
            ) : error ? (
              <div className="p-4 text-red-600 text-sm flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5" />
                {error}
              </div>
            ) : activeMarkers.length === 0 ? (
              <div className="p-4 text-gray-500 text-sm text-center">
                No hay entregas con ubicación activa en este momento.
              </div>
            ) : (
              <ul className="divide-y">
                {activeMarkers.map((delivery) => (
                  <li 
                    key={delivery.id} 
                    className="p-3 hover:bg-gray-50 cursor-pointer transition-colors border-l-4 border-transparent hover:border-blue-500"
                    onClick={() => router.push(`/operator/deliveries/${delivery.id}`)}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <span className="font-medium text-sm text-gray-900">
                        #{delivery.external_id || delivery.order_id?.slice(0, 8)}
                      </span>
                      <Badge className={`text-[10px] px-1.5 py-0 ${getStatusColor(delivery.status)}`}>
                        {delivery.status}
                      </Badge>
                    </div>
                    <div className="text-xs text-gray-500 flex items-center gap-1 mb-1">
                      <MapPin className="w-3 h-3" />
                      {delivery.rider_name || 'Sin repartidor'}
                    </div>
                    <div className="text-[10px] text-gray-400">
                      Destino: {delivery.delivery_address || delivery.order?.delivery_address || 'N/A'}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Área del Mapa */}
        <Card className="lg:col-span-3 overflow-hidden relative bg-white">
          <div className="absolute inset-0 flex items-center justify-center bg-gray-100 z-0">
             {/* 
                IMPORTANTE: Aquí debes integrar tu librería de mapas real (Leaflet, Google Maps, Mapbox).
                Como no sé cuál tienes instalada, dejo un placeholder visual.
                
                Ejemplo con React Leaflet:
                {activeMarkers.length > 0 ? (
                  <MapContainer center={[4.6097, -74.0817]} zoom={12} style={{ height: '100%', width: '100%' }}>
                    <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                    {activeMarkers.map((d) => (
                      <Marker key={d.id} position={[d.current_latitude, d.current_longitude]}>
                        <Popup>
                          <strong>Entrega #{d.external_id}</strong><br/>
                          Estado: {d.status}<br/>
                          Rider: {d.rider_name}
                        </Popup>
                      </Marker>
                    ))}
                  </MapContainer>
                ) : (
                  <div className="text-center text-gray-500">
                    <MapPin className="w-12 h-12 mx-auto mb-2 opacity-50" />
                    <p>No hay ubicaciones activas para mostrar en el mapa.</p>
                  </div>
                )}
             */}
             
             <div className="text-center p-8">
                <MapPin className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-600">Vista de Mapa</h3>
                <p className="text-gray-500 mt-2 max-w-md">
                  El contenedor del mapa está listo. 
                  <br/>
                  <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded mt-2 inline-block">
                    Nota: Integra tu proveedor de mapas (Leaflet/Google) en el código fuente.
                  </span>
                </p>
                {activeMarkers.length > 0 && (
                  <p className="mt-4 text-sm text-blue-600 font-medium">
                    {activeMarkers.length} entregas disponibles para renderizar.
                  </p>
                )}
             </div>
          </div>
        </Card>
      </div>
    </div>
  );
}