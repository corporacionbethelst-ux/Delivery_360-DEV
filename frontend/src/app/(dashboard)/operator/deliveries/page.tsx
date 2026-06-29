'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { deliveryService, Delivery, DeliveryStatus } from '@/services/delivery.service';
import { Package, Clock, CheckCircle, AlertCircle, MapPin, Search, Filter, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

export default function OperatorDeliveriesPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore(); 
  
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<DeliveryStatus | 'ALL'>('ALL');
  const [isMounted, setIsMounted] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // CORRECCIÓN 1: Lógica de carga separada y robusta
  const loadDeliveries = async () => {
    try {
      setError(null);
      // Llamamos al servicio
      const response = await deliveryService.getAll({ limit: 100 });
      
      // CORRECCIÓN CRÍTICA: El servicio devuelve { items: [], total: N }
      // Verificamos 'items' primero, luego 'data' por seguridad, y fallback a array directo.
      let deliveriesList: Delivery[] = [];
      
      if (Array.isArray(response)) {
        deliveriesList = response;
      } else if (response && typeof response === 'object') {
        // Aquí estaba el error: buscabas .data pero el servicio devuelve .items
        deliveriesList = (response as any).items || (response as any).data || [];
      }
      
      setDeliveries(deliveriesList);
    } catch (err: any) {
      console.error('Error loading deliveries:', err);
      setError('No se pudieron cargar las entregas. Intente nuevamente.');
      setDeliveries([]);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    // Si no está montado, no hacemos nada aún
    if (!isMounted) return;

    // Si no está autenticado o no hay usuario, detenemos carga y redirigimos
    if (!isAuthenticated || !user) {
      setIsLoading(false); 
      // Pequeño delay para evitar parpadeo si es un refresh rápido
      setTimeout(() => router.push('/login'), 100);
      return;
    }

    const allowedRoles = ['SUPERADMIN', 'GERENTE', 'OPERADOR'];
    if (!allowedRoles.includes(user.role)) {
      setIsLoading(false);
      router.push('/login');
      return;
    }

    // Si todo está bien, cargamos datos
    loadDeliveries();
    
    // Dependencia exclusiva de loadDeliveries para no crear bucles
  }, [isAuthenticated, user, router, isMounted]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadDeliveries();
  };

  const filteredDeliveries = deliveries.filter(d => {
    const orderId = d.order_id || d.external_id || '';
    const riderName = d.rider ? `${d.rider.first_name || ''} ${d.rider.last_name || ''}`.trim() : '';
    const customerName = d.customer_name || d.order?.customer_name || '';
    
    const term = searchTerm.toLowerCase();
    
    const matchesSearch = 
      orderId.toLowerCase().includes(term) ||
      riderName.toLowerCase().includes(term) ||
      customerName.toLowerCase().includes(term);
    
    const matchesStatus = statusFilter === 'ALL' || d.status === statusFilter;
    
    return matchesSearch && matchesStatus;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETADA': return 'bg-green-100 text-green-800 border-green-200';
      case 'EN_ROUTE':
      case 'EN_RUTA': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'INCIDENCIA': 
      case 'FALLIDA': return 'bg-red-100 text-red-800 border-red-200';
      case 'INICIADA': 
      case 'EN_PICKUP': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  // Renderizado condicional seguro
  if (!isMounted || (!isAuthenticated && !user)) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Gestión de Entregas</h1>
            <p className="text-gray-500">Monitoreo en tiempo real de todas las entregas</p>
          </div>
          <Button 
            variant="outline" 
            onClick={handleRefresh} 
            disabled={isRefreshing || isLoading}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Actualizando...' : 'Actualizar'}
          </Button>
        </div>

        {/* Alerta de Error */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 flex justify-between items-center">
            <span>{error}</span>
            <Button variant="outline" size="sm" onClick={loadDeliveries}>Reintentar</Button>
          </div>
        )}

        {/* Filtros */}
        <div className="bg-white p-4 rounded-xl shadow-sm mb-6 flex gap-4 flex-col md:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
            <Input 
              placeholder="Buscar por orden, cliente o repartidor..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
              disabled={isLoading}
            />
          </div>
          <select 
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
            className="px-4 py-2 border rounded-lg bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50"
            disabled={isLoading}
          >
            <option value="ALL">Todos los estados</option>
            <option value="PENDIENTE">Pendientes</option>
            <option value="INICIADA">Iniciadas</option>
            <option value="EN_ROUTE">En Ruta</option>
            <option value="COMPLETADA">Completadas</option>
            <option value="FALLIDA">Fallidas</option>
          </select>
        </div>

        {/* Lista */}
        <div className="grid gap-4">
          {isLoading && deliveries.length === 0 ? (
             <div className="flex justify-center py-20">
               <Loader2 className="animate-spin h-10 w-10 text-blue-600" />
             </div>
          ) : filteredDeliveries.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center text-gray-500">
                <Package className="w-12 h-12 mx-auto mb-4 opacity-20" />
                <p className="font-medium">
                  {error ? 'Error al cargar datos' : 'No se encontraron entregas'}
                </p>
                {!error && <p className="text-sm mt-2">Intenta ajustar los filtros o verifica que haya entregas activas.</p>}
              </CardContent>
            </Card>
          ) : (
            filteredDeliveries.map((delivery) => (
              <Card key={delivery.id} className="hover:shadow-md transition-shadow border-l-4 border-l-transparent hover:border-l-blue-500">
                <CardContent className="p-4">
                  <div className="flex flex-col md:flex-row justify-between md:items-center gap-4">
                    <div className="flex items-start gap-4">
                      <div className={`p-3 rounded-full ${delivery.status === 'COMPLETADA' ? 'bg-green-100' : 'bg-blue-100'}`}>
                        <Package className={`w-6 h-6 ${delivery.status === 'COMPLETADA' ? 'text-green-600' : 'text-blue-600'}`} />
                      </div>
                      <div>
                        <h3 className="font-semibold text-gray-900">
                          Orden #{delivery.external_id || delivery.order_id || 'N/A'}
                        </h3>
                        <div className="flex items-center gap-2 text-sm text-gray-500 mt-1">
                          <MapPin className="w-3 h-3" />
                          <span className="truncate max-w-[300px]">
                            {delivery.delivery_address || delivery.order?.delivery_address || 'Dirección no disponible'}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-sm text-gray-500 mt-1">
                          <span className="font-medium text-gray-700">Repartidor:</span>
                          {delivery.rider ? (
                            <span className="text-gray-900">{delivery.rider.first_name} {delivery.rider.last_name}</span>
                          ) : (
                            <span className="italic">Sin asignar</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-4">
                      <Badge className={`${getStatusColor(delivery.status)} border font-medium`}>
                        {delivery.status}
                      </Badge>
                      <div className="text-right">
                        <div className="text-xs text-gray-500">Duración</div>
                        <div className="font-medium text-gray-900">
                          {delivery.total_time ? `${Math.round(delivery.total_time)} min` : '-'}
                        </div>
                      </div>
                      {delivery.sla_compliant === false && (
                        <div className="relative group cursor-help" title="SLA Incumplido">
                          <AlertCircle className="w-5 h-5 text-red-500" />
                        </div>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => router.push(`/operator/deliveries/${delivery.id}`)}
                        disabled={isLoading}
                      >
                        Ver Detalle
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}