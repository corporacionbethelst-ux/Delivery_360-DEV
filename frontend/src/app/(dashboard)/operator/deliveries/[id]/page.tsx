'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ArrowLeft, MapPin, Phone, Clock, User, Navigation, AlertTriangle, Loader2 } from 'lucide-react';
import { deliveryService } from '@/services/delivery.service';
import type { Delivery } from '@/types/delivery';
import { formatCurrency } from '@/lib/formatters';

const ACTIVE_STATUSES = ['INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'EN_DESTINO'];

export default function DeliveryDetailPage() {
  const router = useRouter();
  const params = useParams() as { id?: string };
  const id = params.id;
  const { user, isAuthenticated } = useAuthStore();

  const [delivery, setDelivery] = useState<any | null>(null); // Cambiado a any para evitar errores de tipo estricto
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

    const fetchDelivery = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await deliveryService.getById(id);
        setDelivery(response);
      } catch (err: any) {
        console.error('Error fetching delivery:', err);
        setError(err?.message || 'No se pudo cargar la entrega.');
        setDelivery(null);
      } finally {
        setLoading(false);
      }
    };

    fetchDelivery();
  }, [id, isAuthenticated, isMounted, router, user]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETADA': return 'bg-green-100 text-green-800 border-green-200';
      case 'FALLIDA': return 'bg-red-100 text-red-800 border-red-200';
      case 'EN_ROUTE':
      case 'EN_DESTINO': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'EN_PICKUP':
      case 'INICIADA': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
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

  if (error || !delivery) {
    return (
      <div className="p-6 text-center">
        <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold">Entrega no encontrada</h2>
        <p className="mt-2 text-sm text-gray-500">{error || 'No existe una entrega con ese identificador.'}</p>
        <Button onClick={() => router.back()} className="mt-4">Volver</Button>
      </div>
    );
  }

  // Accesos seguros usando notación de corchetes o any para evitar errores TS
  const riderName = delivery.rider
    ? `${delivery.rider.first_name || ''} ${delivery.rider.last_name || ''}`.trim()
    : delivery.rider_name || 'No asignado';
  
  const customerName = delivery.customer_name || delivery.order?.customer_name || 'Cliente no disponible';
  const customerPhone = delivery.customer_phone || delivery.order?.customer_phone || '';
  
  // Intentamos ambas formas (snake_case y camelCase) para direcciones
  const deliveryAddress = delivery.delivery_address || delivery.deliveryAddress || delivery.order?.delivery_address || delivery.order?.deliveryAddress || 'Dirección no disponible';
  const pickupAddress = delivery.pickup_address || delivery.pickupAddress || 'Origen no disponible';
  
  const totalAmount = Number(delivery.total_amount ?? delivery.totalAmount ?? delivery.order?.total_amount ?? delivery.order?.totalAmount ?? 0);
  
  const hasCoordinates = (delivery.current_latitude !== null && delivery.current_latitude !== undefined) || 
                         (delivery.currentLatitude !== null && delivery.currentLatitude !== undefined);
  const lat = delivery.current_latitude ?? delivery.currentLatitude;
  const lng = delivery.current_longitude ?? delivery.currentLongitude;

  // Fechas y tiempos
  const startedAt = delivery.started_at || delivery.startedAt;
  const totalTime = delivery.total_time ?? delivery.totalTime;
  const slaCompliant = delivery.sla_compliant ?? delivery.slaCompliant;
  const externalId = delivery.external_id || delivery.externalId || delivery.order_id || delivery.orderId;
  const status = delivery.status;
  const paymentMethod = delivery.payment_method || delivery.paymentMethod;

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto">
        <Button variant="ghost" onClick={() => router.back()} className="mb-6 pl-0 hover:bg-transparent hover:text-blue-600">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver al listado
        </Button>
        
        <div className="flex justify-between items-start mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Detalle de Entrega</h1>
            <p className="text-gray-500">Orden #{externalId} • ID: {delivery.id}</p>
          </div>
          <Badge className={`px-3 py-1 text-sm font-semibold border ${getStatusColor(status)}`}>
            {status}
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><User className="w-5 h-5"/> Cliente</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <p className="font-bold text-lg">{customerName}</p>
                    <p className="text-sm text-gray-500">{paymentMethod || 'Método de pago no disponible'}</p>
                  </div>
                  {customerPhone && (
                    <Button variant="outline" size="sm" className="gap-2" asChild>
                      <a href={`tel:${customerPhone}`}><Phone className="w-4 h-4" /> Llamar</a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><MapPin className="w-5 h-5"/> Ruta</CardTitle></CardHeader>
              <CardContent>
                <div className="relative pl-6 border-l-2 border-dashed border-gray-300 space-y-8">
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-blue-500 ring-4 ring-blue-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Origen</p>
                    <p className="text-sm font-medium">{pickupAddress}</p>
                  </div>
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full bg-green-500 ring-4 ring-green-100"></div>
                    <p className="text-xs text-gray-500 font-semibold">Destino</p>
                    <p className="text-sm font-medium">{deliveryAddress}</p>
                  </div>
                </div>
                {hasCoordinates && lat && lng && (
                  <Button variant="outline" className="w-full gap-2 mt-4" asChild>
                    <a href={`https://www.google.com/maps?q=${lat},${lng}`} target="_blank" rel="noreferrer">
                      <Navigation className="w-4 h-4" /> Abrir ubicación actual
                    </a>
                  </Button>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader><CardTitle>Detalles</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between">
                  <span className="text-gray-500">Repartidor</span>
                  <span className="font-medium text-right">{riderName}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Total</span>
                  <span className="font-bold">{formatCurrency(totalAmount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Inicio</span>
                  <span className="font-medium">{startedAt ? new Date(startedAt).toLocaleString() : '-'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Duración</span>
                  <span className="font-medium">{totalTime ? `${Math.round(totalTime)} min` : '-'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">SLA</span>
                  <span className={slaCompliant === false ? 'font-medium text-red-600' : 'font-medium text-green-600'}>
                    {slaCompliant === null || slaCompliant === undefined ? 'Pendiente' : slaCompliant ? 'Cumple' : 'Incumplido'}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-blue-200 bg-blue-50/30">
              <CardHeader><CardTitle className="text-blue-900 flex items-center gap-2"><Clock className="w-5 h-5" /> Seguimiento</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm text-blue-900">
                {ACTIVE_STATUSES.includes(status) ? (
                  <p>Entrega activa. El operador puede monitorear la ruta y coordinar incidencias; los cambios de estado operativo los ejecuta el rider desde su flujo.</p>
                ) : (
                  <p>Entrega sin acciones operativas pendientes para el operador.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}