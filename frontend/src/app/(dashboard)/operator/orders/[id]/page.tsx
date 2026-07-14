'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService, Order } from '@/services/order.service';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ArrowLeft, MapPin, Phone, Clock, User, Package, AlertTriangle, Loader2, CreditCard, Bike } from 'lucide-react';
import { formatCurrency } from '@/lib/formatters';

const ACTIVE_STATUSES = ['PENDIENTE', 'CONFIRMADA', 'EN_PREPARACION', 'LISTA_PARA_DESPACHO', 'ASIGNADA', 'EN_CAMINO', 'ENTREGADO'];

export default function OperatorOrderDetailPage() {
  const router = useRouter();
  const params = useParams() as { id?: string };
  const id = params.id;
  const { user, isAuthenticated } = useAuthStore();

  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [isMounted, setIsMounted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user || !id) return;

    const allowedRoles = ['SUPERADMIN', 'GERENTE', 'OPERADOR'];
    if (!allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    const fetchOrder = async () => {
      setLoading(true);
      setError(null);
      try {
        // Asumimos que el servicio tiene un método getById o similar
        // Si el servicio retorna una lista filtrada, ajustar aquí
        const response = await orderService.getById(id);
        setOrder(response);
      } catch (err: any) {
        console.error('Error fetching order:', err);
        setError(err?.message || 'No se pudo cargar la orden.');
        setOrder(null);
      } finally {
        setLoading(false);
      }
    };

    fetchOrder();
  }, [id, isAuthenticated, isMounted, router, user]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ENTREGADO': return 'bg-green-100 text-green-800 border-green-200';
      case 'CANCELADO': return 'bg-red-100 text-red-800 border-red-200';
      case 'EN_CAMINO':
      case 'ASIGNADA': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'PENDIENTE':
      case 'CONFIRMADA': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  if (!isMounted || !isAuthenticated || !user || loading) {
    return (
      <div className="p-6 flex justify-center items-center h-screen">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold">Orden no encontrada</h2>
        <p className="mt-2 text-sm text-gray-500">{error || 'No existe una orden con ese identificador.'}</p>
        <Button onClick={() => router.back()} className="mt-4">Volver</Button>
      </div>
    );
  }

  const customerName = order.customer_name || 'Cliente no disponible';
  const customerPhone = order.customer_phone || '';
  const deliveryAddress = order.delivery_address || 'Dirección no disponible';
  const pickupAddress = order.pickup_address || 'Dirección de recogida no disponible';
  const riderName = order.rider 
    ? `${order.rider.first_name || ''} ${order.rider.last_name || ''}`.trim() 
    : (order as any).rider_name || 'No asignado';
  
  const totalAmount = Number(order.total_amount ?? order.total ?? 0);

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto">
        <Button variant="ghost" onClick={() => router.back()} className="mb-6 pl-0 hover:bg-transparent hover:text-blue-600">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver al listado
        </Button>
        
        <div className="flex justify-between items-start mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Detalle de Orden</h1>
            <p className="text-gray-500">#{order.external_id || order.id} • Creada: {new Date(order.created_at).toLocaleDateString()}</p>
          </div>
          <Badge className={`px-3 py-1 text-sm font-semibold border ${getStatusColor(order.status)}`}>
            {order.status}
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            {/* Información del Cliente */}
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><User className="w-5 h-5"/> Cliente</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <p className="font-bold text-lg">{customerName}</p>
                    <p className="text-sm text-gray-500 flex items-center gap-2">
                      <CreditCard className="w-3 h-3" /> {order.payment_method || 'No especificado'}
                    </p>
                  </div>
                  {customerPhone && (
                    <Button variant="outline" size="sm" className="gap-2" asChild>
                      <a href={`tel:${customerPhone}`}><Phone className="w-4 h-4" /> Llamar</a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Ruta */}
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><MapPin className="w-5 h-5"/> Ruta de Entrega</CardTitle></CardHeader>
              <CardContent>
                <div className="relative pl-6 border-l-2 border-dashed border-gray-300 space-y-8">
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-orange-500 ring-4 ring-orange-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Recogida</p>
                    <p className="text-sm font-medium">{pickupAddress}</p>
                  </div>
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-green-500 ring-4 ring-green-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Entrega</p>
                    <p className="text-sm font-medium">{deliveryAddress}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Items de la orden (si existen) */}
            {order.items && order.items.length > 0 && (
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Package className="w-5 h-5"/> Productos</CardTitle></CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 border-b">
                        <tr>
                          <th className="px-4 py-2 text-left font-semibold">Producto</th>
                          <th className="px-4 py-2 text-right font-semibold">Cantidad</th>
                          <th className="px-4 py-2 text-right font-semibold">Precio</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {order.items.map((item: any, idx: number) => (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-4 py-2">{item.name || 'Producto sin nombre'}</td>
                            <td className="px-4 py-2 text-right">{item.quantity}</td>
                            <td className="px-4 py-2 text-right">{formatCurrency(item.price || item.total || 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            {/* Resumen Financiero */}
            <Card>
              <CardHeader><CardTitle>Resumen</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between">
                  <span className="text-gray-500">Subtotal</span>
                  <span className="font-medium">{formatCurrency(totalAmount * 0.85)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Impuestos</span>
                  <span className="font-medium">{formatCurrency(totalAmount * 0.15)}</span>
                </div>
                <div className="flex justify-between pt-4 border-t">
                  <span className="font-bold text-lg">Total</span>
                  <span className="font-bold text-lg text-blue-600">{formatCurrency(totalAmount)}</span>
                </div>
              </CardContent>
            </Card>

            {/* Asignación de Repartidor */}
            <Card className={order.rider ? 'border-green-200 bg-green-50/30' : 'border-yellow-200 bg-yellow-50/30'}>
              <CardHeader>
                <CardTitle className={`flex items-center gap-2 ${order.rider ? 'text-green-900' : 'text-yellow-900'}`}>
                  <Bike className="w-5 h-5" /> 
                  Repartidor
                </CardTitle>
              </CardHeader>
              <CardContent>
                {order.rider ? (
                  <div className="space-y-2">
                    <p className="font-bold text-green-900">{riderName}</p>
                    <p className="text-sm text-green-700">Asignado correctamente</p>
                    <Button variant="outline" size="sm" className="w-full mt-2 text-green-900 border-green-200 hover:bg-green-100" asChild>
                       <a href={`/operator/riders/${(order.rider as any).id}`}>Ver Perfil</a>
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="font-medium text-yellow-900">Sin asignar</p>
                    <p className="text-sm text-yellow-700">Esta orden aún no tiene repartidor.</p>
                    <Button variant="outline" size="sm" className="w-full mt-2 text-yellow-900 border-yellow-200 hover:bg-yellow-100" disabled>
                      Asignar Manualmente
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Timeline / Estado */}
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Clock className="w-5 h-5" /> Historial</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">Creada:</span>
                  <span className="font-medium">{new Date(order.created_at).toLocaleTimeString()}</span>
                </div>
                {order.updated_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Actualizada:</span>
                    <span className="font-medium">{new Date(order.updated_at).toLocaleTimeString()}</span>
                  </div>
                )}
                <div className="pt-2 mt-2 border-t">
                  <p className="text-xs text-gray-400 italic">
                    {ACTIVE_STATUSES.includes(order.status) ? 'Orden en proceso activo.' : 'Orden finalizada o cancelada.'}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}