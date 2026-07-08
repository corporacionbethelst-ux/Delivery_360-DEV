'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService, Order } from '@/services/order.service';
import { Package, Clock, MapPin, DollarSign, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { OrderSkeleton } from '@/components/loaders/OrderSkeleton';
import { formatCurrency } from '@/lib/formatters';
import { resolveOrderCollectAmount } from '@/lib/order-amount';

export default function MyOrdersPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Función centralizada para cargar datos
  const loadOrders = async () => {
    try {
      // El backend filtra automáticamente por el rider autenticado
      const data = await orderService.getAll({ limit: 50 }); // Aumentado ligeramente para mejor UX
      setOrders(data);
    } catch (error) {
      console.error('Error loading orders:', error);
    }
  };

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== 'REPARTIDOR') {
      router.push('/login'); 
      return;
    }

    const init = async () => {
      setLoading(true);
      await loadOrders();
      setLoading(false);
    };
    
    init();
  }, [user, isAuthenticated, router, isMounted]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadOrders();
    setIsRefreshing(false);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ENTREGADO': return 'bg-green-100 text-green-800 border-green-200';
      case 'ASIGNADO': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'EN_RUTA': 
      case 'EN_RECOLECCION': 
      case 'RECOLECTADO': return 'bg-purple-100 text-purple-800 border-purple-200';
      case 'CANCELADO': return 'bg-red-100 text-red-800 border-red-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  if (!isMounted || !isAuthenticated || !user || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin h-12 w-12 text-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Cargando tus entregas...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto space-y-6">
        
        {/* Header con Título y Botón Actualizar */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white p-4 rounded-xl border shadow-sm">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Mis Entregas</h1>
            <p className="text-sm text-gray-500 mt-1">
              Historial y estado de tus asignaciones recientes
            </p>
          </div>
          <Button
            variant="outline"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="gap-2 bg-white min-w-[120px]"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Actualizando...' : 'Actualizar'}
          </Button>
        </div>

        {/* Grid de Tarjetas */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {loading && orders.length === 0
            ? Array.from({ length: 4 }).map((_, i) => <OrderSkeleton key={i} />)
            : orders.map((order) => (
                <Card 
                  key={order.id} 
                  className="group hover:shadow-lg transition-all duration-200 cursor-pointer border-l-4 border-l-blue-500 hover:border-l-blue-600 bg-white"
                  onClick={() => router.push(`/rider/my-orders/${order.id}`)}
                >
                  <CardHeader className="pb-3">
                    <div className="flex justify-between items-start">
                      <Badge className={`${getStatusColor(order.status)} border font-semibold text-xs uppercase tracking-wide`}>
                        {order.status.replace('_', ' ')}
                      </Badge>
                      <span className="text-xs text-gray-400 font-mono bg-gray-50 px-2 py-1 rounded">
                        #{order.external_id}
                      </span>
                    </div>
                    <CardTitle className="text-lg mt-3 text-gray-800 group-hover:text-blue-700 transition-colors">
                      Orden de Entrega
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-start gap-2 text-sm text-gray-600">
                      <MapPin className="w-4 h-4 mt-0.5 text-gray-400 shrink-0" />
                      <span className="line-clamp-2 font-medium">{order.delivery_address}</span>
                    </div>
                    
                    <div className="flex items-center justify-between pt-2">
                      <div className="flex items-center gap-2 text-sm text-gray-500">
                        <Clock className="w-4 h-4" />
                        <span>{new Date(order.created_at).toLocaleDateString()}</span>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-gray-400 uppercase font-semibold">A cobrar</p>
                        <p className="font-bold text-lg text-green-600">
                          {formatCurrency(resolveOrderCollectAmount(order))}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
        </div>

        {/* Estado Vacío */}
        {!loading && orders.length === 0 && (
          <div className="text-center py-16 bg-white rounded-lg border border-dashed border-gray-300 shadow-sm">
            <div className="bg-gray-50 w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-4">
              <Package className="w-10 h-10 text-gray-400" />
            </div>
            <h3 className="text-lg font-bold text-gray-900">No tienes entregas aún</h3>
            <p className="text-gray-500 mt-2 max-w-md mx-auto">
              Las asignaciones aparecerán aquí automáticamente cuando estés en línea y haya disponibilidad en tu zona.
            </p>
            <Button 
              variant="outline" 
              className="mt-6"
              onClick={handleRefresh}
              disabled={isRefreshing}
            >
              {isRefreshing ? 'Buscando...' : 'Buscar nuevamente'}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}