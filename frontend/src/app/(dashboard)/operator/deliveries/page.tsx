'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { deliveryService } from '@/services/delivery.service';
// Importamos el tipo pero somos flexibles con su uso debido a inconsistencias backend/frontend
import type { Delivery } from '@/types/delivery';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Bike, Search, Filter, Eye, AlertCircle, RefreshCw } from 'lucide-react';
import { formatCurrency } from '@/lib/formatters';

// Tipos locales para los filtros
type StatusFilter = 'TODOS' | 'INICIADA' | 'EN_PICKUP' | 'EN_ROUTE' | 'EN_DESTINO' | 'COMPLETADA' | 'FALLIDA';

export default function OperatorDeliveriesPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [deliveries, setDeliveries] = useState<any[]>([]); // Usamos any[] temporalmente para evitar errores de tipo estricto
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Filtros
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('TODOS');
  const [dateFilter, setDateFilter] = useState<'today' | 'week' | 'month' | 'all'>('today');

  const loadDeliveries = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);
    try {
      // Obtenemos todas las entregas (el backend debería permitir filtrar, pero aquí filtramos en frontend por ahora)
      const response = await deliveryService.getAll({ limit: 100 });
      // Aseguramos que sea un array
      const items = Array.isArray(response) ? response : (response as any).items || [];
      setDeliveries(items);
    } catch (err: any) {
      console.error('Error loading deliveries:', err);
      setError(err?.message || 'No se pudieron cargar las entregas.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      loadDeliveries();
    }
  }, [isAuthenticated]);

  // Lógica de filtrado segura accediendo a propiedades dinámicas
  const filteredDeliveries = useMemo(() => {
    return deliveries.filter((d: any) => {
      // Normalización de propiedades (soporta snake_case y camelCase)
      const status = d.status || d.delivery_status;
      const externalId = d.external_id || d.order_id;
      const riderName = d.rider_name || d.rider?.first_name || '';
      const customerName = d.customer_name || d.order?.customer_name || '';
      
      // Filtro de texto
      const searchLower = searchTerm.toLowerCase();
      const matchesSearch = 
        String(externalId).toLowerCase().includes(searchLower) ||
        riderName.toLowerCase().includes(searchLower) ||
        customerName.toLowerCase().includes(searchLower);

      // Filtro de estado
      const matchesStatus = statusFilter === 'TODOS' || status === statusFilter;

      // Filtro de fecha (usando created_at o started_at)
      const dateStr = d.started_at || d.created_at;
      let matchesDate = true;
      if (dateFilter !== 'all' && dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        if (dateFilter === 'today') {
          matchesDate = date.toDateString() === now.toDateString();
        } else if (dateFilter === 'week') {
          const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
          matchesDate = date >= weekAgo;
        } else if (dateFilter === 'month') {
          matchesDate = date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
        }
      }

      return matchesSearch && matchesStatus && matchesDate;
    });
  }, [deliveries, searchTerm, statusFilter, dateFilter]);

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

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Gestión de Entregas</h1>
            <p className="text-gray-500">Monitoreo en tiempo real de entregas activas y completadas.</p>
          </div>
          <Button onClick={loadDeliveries} variant="outline" disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Actualizar
          </Button>
        </div>

        {/* Filtros */}
        <Card>
          <CardContent className="pt-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-2 relative">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                <Input
                  placeholder="Buscar por orden, repartidor o cliente..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                <SelectTrigger>
                  <SelectValue placeholder="Estado" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="TODOS">Todos los estados</SelectItem>
                  <SelectItem value="INICIADA">Iniciada</SelectItem>
                  <SelectItem value="EN_PICKUP">En Pickup</SelectItem>
                  <SelectItem value="EN_ROUTE">En Ruta</SelectItem>
                  <SelectItem value="EN_DESTINO">En Destino</SelectItem>
                  <SelectItem value="COMPLETADA">Completada</SelectItem>
                  <SelectItem value="FALLIDA">Fallida</SelectItem>
                </SelectContent>
              </Select>
              <Select value={dateFilter} onValueChange={(v) => setDateFilter(v as any)}>
                <SelectTrigger>
                  <SelectValue placeholder="Fecha" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="today">Hoy</SelectItem>
                  <SelectItem value="week">Esta semana</SelectItem>
                  <SelectItem value="month">Este mes</SelectItem>
                  <SelectItem value="all">Todo el historial</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Error Alert */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded-md flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        )}

        {/* Tabla */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bike className="w-5 h-5 text-blue-600" />
              Listado de Entregas ({filteredDeliveries.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex justify-center py-12">
                <RefreshCw className="animate-spin h-8 w-8 text-blue-600" />
              </div>
            ) : filteredDeliveries.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                No se encontraron entregas con los filtros actuales.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600 uppercase text-xs">Orden</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600 uppercase text-xs">Estado</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600 uppercase text-xs">Repartidor</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600 uppercase text-xs">Cliente</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600 uppercase text-xs">Inicio</th>
                      <th className="px-4 py-3 text-right font-semibold text-gray-600 uppercase text-xs">Acciones</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {filteredDeliveries.map((delivery: any) => {
                      // Acceso seguro a propiedades
                      const id = delivery.id;
                      const externalId = delivery.external_id || delivery.order_id;
                      const status = delivery.status || delivery.delivery_status;
                      const riderName = delivery.rider_name || `${delivery.rider?.first_name || ''} ${delivery.rider?.last_name || ''}`.trim() || 'No asignado';
                      const customerName = delivery.customer_name || delivery.order?.customer_name || 'Cliente';
                      const startedAt = delivery.started_at || delivery.created_at;
                      
                      return (
                        <tr key={id} className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-3 font-medium text-gray-900">#{externalId}</td>
                          <td className="px-4 py-3">
                            <Badge variant="outline" className={`${getStatusColor(status)} border`}>
                              {status}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 text-gray-700">{riderName}</td>
                          <td className="px-4 py-3 text-gray-700">{customerName}</td>
                          <td className="px-4 py-3 text-gray-500">
                            {startedAt ? new Date(startedAt).toLocaleString() : '-'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => router.push(`/operator/deliveries/${id}`)}
                            >
                              <Eye className="w-4 h-4 mr-1" /> Ver
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}