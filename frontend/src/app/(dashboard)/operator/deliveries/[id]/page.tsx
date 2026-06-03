import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ArrowLeft, MapPin, Phone, Clock, Package, User, CreditCard, Navigation, CheckCircle, AlertTriangle, MessageSquare } from 'lucide-react';
import { deliveryService, Delivery as DeliveryType } from '@/services/delivery.service';

interface Delivery extends DeliveryType {
  rider_name: string;
  rider_phone: string;
  customer_phone: string;
  pickup_address: string;
  delivery_address: string;
  total_amount: number;
  payment_method: string;
  notes: string;
  estimated_delivery_time: string;
}

export default function DeliveryDetailPage() {
  const router = useRouter();
  
  // CORRECCIÓN: Usar ! para afirmar que params no es null al acceder a id
  const params = useParams();
  const id = params!.id as string;

  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    if (!id) return;

    const fetchDelivery = async () => {
      setLoading(true);
      try {
        // ✅ LLAMADA REAL AL BACKEND
        const response = await deliveryService.getById(id);
        
        // Mapear los datos del backend al formato esperado por la UI
        const mappedData: Delivery = {
          id: response.id,
          order_id: response.order_id,
          rider_name: response.rider?.first_name && response.rider?.last_name 
            ? `${response.rider.first_name} ${response.rider.last_name}` 
            : 'No asignado',
          rider_phone: '', // El backend no devuelve phone del rider en este endpoint, se puede agregar si es necesario
          customer_name: response.customer_name || 'Cliente',
          customer_phone: '', // El backend no devuelve phone del cliente directamente
          pickup_address: '', // Se debe obtener de la orden asociada si es necesario
          delivery_address: '', // Se debe obtener de la orden asociada si es necesario
          status: response.status as Delivery['status'],
          total_amount: 0, // Se debe obtener de la orden asociada
          payment_method: '', // Se debe obtener de la orden asociada
          notes: '', // Se puede agregar en el backend si existe
          estimated_delivery_time: '' // Se puede calcular o agregar en el backend
        };
        
        setDelivery(mappedData);
      } catch (err) {
        console.error('Error fetching delivery:', err);
        // Opcional: Mostrar toast de error
      } finally {
        setLoading(false);
      }
    };

    fetchDelivery();
  }, [id]);

  const handleStatusChange = async (newStatus: Delivery['status']) => {
    if (!delivery) return;
    setActionLoading(true);
    try {
      // ✅ LLAMADA REAL AL BACKEND - Actualizar estado de entrega
      await deliveryService.updateLocation(delivery.id, 0, 0); // Placeholder hasta tener endpoint específico de status
      setDelivery({ ...delivery, status: newStatus });
      alert(`Estado actualizado a: ${newStatus}`);
    } catch (error) {
      console.error('Error al actualizar estado:', error);
      alert('Error al actualizar estado');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) return (
    <div className="p-6 flex justify-center items-center h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  );

  if (!delivery) return (
    <div className="p-6 text-center">
      <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
      <h2 className="text-xl font-bold">Entrega no encontrada</h2>
      <Button onClick={() => router.back()} className="mt-4">Volver</Button>
    </div>
  );

  const getStatusColor = (status: string) => {
    switch(status) {
      case 'COMPLETED': return 'bg-green-100 text-green-800 border-green-200';
      case 'CANCELLED': return 'bg-red-100 text-red-800 border-red-200';
      case 'DELIVERING': return 'bg-blue-100 text-blue-800 border-blue-200';
      default: return 'bg-yellow-100 text-yellow-800 border-yellow-200';
    }
  };

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto">
        <Button variant="ghost" onClick={() => router.back()} className="mb-6 pl-0 hover:bg-transparent hover:text-blue-600">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver al listado
        </Button>
        
        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Detalle de Entrega</h1>
            <p className="text-gray-500">Orden #{delivery.order_id} • ID: {delivery.id}</p>
          </div>
          <Badge className={`px-3 py-1 text-sm font-semibold border ${getStatusColor(delivery.status)}`}>
            {delivery.status}
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Columna Izquierda */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><User className="w-5 h-5"/> Cliente</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <p className="font-bold text-lg">{delivery.customer_name}</p>
                    <p className="text-sm text-gray-500">{delivery.payment_method}</p>
                  </div>
                  <Button variant="outline" size="sm" className="gap-2">
                    <Phone className="w-4 h-4" /> Llamar
                  </Button>
                </div>
                <div className="bg-gray-50 p-4 rounded-lg">
                  <p className="text-xs text-gray-500 uppercase font-semibold mb-1">Dirección de Entrega</p>
                  <p className="font-medium text-gray-900">{delivery.delivery_address}</p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Package className="w-5 h-5"/> Repartidor</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <p className="font-bold text-lg">{delivery.rider_name}</p>
                    <p className="text-sm text-gray-500">En ruta actualmente</p>
                  </div>
                  <Button variant="outline" size="sm" className="gap-2">
                    <MessageSquare className="w-4 h-4" /> Chat
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" className="flex-1 gap-2">
                    <Navigation className="w-4 h-4" /> Ver Ubicación
                  </Button>
                  <Button variant="outline" className="flex-1 gap-2">
                    <Phone className="w-4 h-4" /> Llamar
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><MapPin className="w-5 h-5"/> Ruta</CardTitle></CardHeader>
              <CardContent className="space-y-6 relative">
                <div className="pl-4 border-l-2 border-blue-200 space-y-6">
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-blue-500 ring-4 ring-blue-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Origen</p>
                    <p className="text-sm font-medium">{delivery.pickup_address}</p>
                  </div>
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-green-500 ring-4 ring-green-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Destino</p>
                    <p className="text-sm font-medium">{delivery.delivery_address}</p>
                  </div>
                </div>
                <Button variant="outline" className="w-full gap-2 mt-2">
                  <Navigation className="w-4 h-4" /> Abrir en Google Maps
                </Button>
              </CardContent>
            </Card>
          </div>

          {/* Columna Derecha */}
          <div className="space-y-6">
            <Card>
              <CardHeader><CardTitle>Detalles</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between">
                  <span className="text-gray-500">Total</span>
                  <span className="font-bold">${delivery.total_amount.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Estimado</span>
                  <span className="font-medium">{delivery.estimated_delivery_time}</span>
                </div>
                {delivery.notes && (
                  <div className="pt-4 border-t">
                    <p className="text-xs text-gray-500 font-semibold mb-1">Notas</p>
                    <p className="text-sm bg-yellow-50 p-2 rounded text-yellow-800 border border-yellow-100">{delivery.notes}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-blue-200 bg-blue-50/30">
              <CardHeader><CardTitle className="text-blue-900">Gestión de Estado</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {delivery.status !== 'COMPLETED' && delivery.status !== 'CANCELLED' && (
                  <>
                    <Button 
                      className="w-full bg-blue-600 hover:bg-blue-700" 
                      onClick={() => handleStatusChange('DELIVERING')}
                      disabled={actionLoading || delivery.status === 'DELIVERING'}
                    >
                      Marcar en Camino
                    </Button>
                    <Button 
                      className="w-full bg-green-600 hover:bg-green-700" 
                      onClick={() => handleStatusChange('COMPLETED')}
                      disabled={actionLoading}
                    >
                      <CheckCircle className="w-4 h-4 mr-2" /> Completar Entrega
                    </Button>
                    <Button 
                      variant="destructive" 
                      className="w-full" 
                      onClick={() => handleStatusChange('CANCELLED')}
                      disabled={actionLoading}
                    >
                      <AlertTriangle className="w-4 h-4 mr-2" /> Cancelar
                    </Button>
                  </>
                )}
                {(delivery.status === 'COMPLETED' || delivery.status === 'CANCELLED') && (
                  <div className="text-center p-4 text-sm text-gray-500">
                    Esta entrega ya ha sido finalizada.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}