'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService, OrderStatus } from '@/services/order.service';
import { Package, Clock, AlertCircle, Search, Filter, RefreshCw, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { formatCurrency } from '@/lib/formatters';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

// Definición explícita de roles permitidos para este dashboard
const ALLOWED_ROLES = ['SUPERADMIN', 'GERENTE', 'OPERADOR'];

// Opciones de paginación
const ROWS_PER_PAGE_OPTIONS = [20, 40, 50, 100];
const DEFAULT_PAGE_SIZE = 20;

export default function OperatorOrdersPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  // --- ESTADOS ---
  const [allOrders, setAllOrders] = useState<any[]>([]); // Datos crudos del servidor
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  // Estados de Paginación y Filtros
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<OrderStatus | 'ALL'>('ALL');
  const [isMounted, setIsMounted] = useState(false);

  // --- EFECTOS ---
  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    if (!ALLOWED_ROLES.includes(user.role)) {
      router.push('/login');
      return;
    }

    loadOrders();
  }, [isAuthenticated, user, router, isMounted]); 
  // NOTA: Quitamos page, pageSize, statusFilter de las dependencias para no recargar el servidor al cambiar filtros locales.

  // --- LÓGICA DE CARGA ---
  const loadOrders = async () => {
    if (!isRefreshing) setIsLoading(true);
    
    try {
      // ESTRATEGIA: Cargamos un lote suficiente (ej. 100) para filtrar en cliente.
      // Esto evita errores de offset/search que el backend no soporta.
      const params: any = {
        limit: 100, 
        status: statusFilter !== 'ALL' ? statusFilter : undefined,
      };

      const response = await orderService.getAll(params);

      // Normalización de respuesta
      const dataItems = Array.isArray(response) ? response : (response as any).items || (response as any).data || [];
      
      setAllOrders(dataItems);
      setPage(1); // Resetear a página 1 al cargar nuevos datos

    } catch (error) {
      console.error('Error loading orders:', error);
      setAllOrders([]);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadOrders();
  };

  // --- FILTRADO Y PAGINACIÓN EN CLIENTE ---
  // Esto soluciona el problema de "Mostrando 1-50 de 50" incorrectamente.
  const filteredOrders = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    
    return allOrders.filter(order => {
      // 1. Filtro de Estado
      const matchesStatus = statusFilter === 'ALL' || order.status === statusFilter;
      if (!matchesStatus) return false;

      // 2. Filtro de Búsqueda
      if (!term) return true;

      const matchesSearch = 
        (order.external_id && order.external_id.toLowerCase().includes(term)) ||
        (order.customer_name && order.customer_name.toLowerCase().includes(term)) ||
        (order.id && order.id.toLowerCase().includes(term));
      
      return matchesSearch;
    });
  }, [allOrders, searchTerm, statusFilter]);

  // Cálculos derivados de la paginación sobre los datos YA FILTRADOS
  const totalPages = Math.max(1, Math.ceil(filteredOrders.length / pageSize));
  
  // Ajuste de página si nos quedamos sin datos (ej. borrar filtro mientras estamos en pág 5)
  useEffect(() => {
    if (page > totalPages) {
      setPage(1);
    }
  }, [totalPages, page]);

  const startIndex = ((page - 1) * pageSize) + 1;
  const endIndex = Math.min(page * pageSize, filteredOrders.length);

  const paginatedOrders = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredOrders.slice(start, start + pageSize);
  }, [filteredOrders, page, pageSize]);

  // --- HANDLERS ---
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ENTREGADO': return 'bg-green-100 text-green-800 border-green-200';
      case 'EN_RUTA': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'PENDIENTE': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'ASIGNADO': return 'bg-indigo-100 text-indigo-800 border-indigo-200';
      case 'CANCELADO': return 'bg-red-100 text-red-800 border-red-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setPage(newPage);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const handlePageSizeChange = (newSize: string) => {
    setPageSize(Number(newSize));
    setPage(1);
  };

  const handleStatusChange = (val: string) => {
    setStatusFilter(val as any);
    setPage(1);
  };

  // --- RENDER ---
  if (!isMounted || !isAuthenticated || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (isLoading && allOrders.length === 0) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
        <p className="text-gray-500">Cargando órdenes...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Gestión de Órdenes</h1>
            <p className="text-gray-500">Monitoreo y control de pedidos en tiempo real</p>
          </div>
          <Button 
            variant="outline" 
            onClick={handleRefresh} 
            disabled={isRefreshing}
            className="gap-2 bg-white"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Actualizando...' : 'Actualizar'}
          </Button>
        </div>

        {/* Panel de Filtros y Paginación */}
        <Card className="shadow-sm border-l-4 border-l-blue-500">
          <CardContent className="p-4">
            <div className="flex flex-col lg:flex-row gap-4 justify-between items-end">
              
              <div className="flex flex-wrap gap-3 w-full lg:w-auto">
                {/* Buscador */}
                <div className="relative w-full sm:w-64">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                  <Input
                    placeholder="Buscar por ID o cliente..."
                    value={searchTerm}
                    onChange={(e) => {
                      setSearchTerm(e.target.value);
                      setPage(1);
                    }}
                    className="pl-9 h-9 bg-white"
                    disabled={isRefreshing}
                  />
                </div>

                {/* Filtro Estado */}
                <div className="w-full sm:w-40">
                  <Select value={statusFilter} onValueChange={handleStatusChange}>
                    <SelectTrigger className="h-9 bg-white">
                      <SelectValue placeholder="Estado" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">Todos</SelectItem>
                      <SelectItem value="PENDIENTE">Pendientes</SelectItem>
                      <SelectItem value="ASIGNADO">Asignados</SelectItem>
                      <SelectItem value="EN_RUTA">En Ruta</SelectItem>
                      <SelectItem value="ENTREGADO">Entregados</SelectItem>
                      <SelectItem value="CANCELADO">Cancelados</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Selector Filas por página */}
                <div className="w-full sm:w-32">
                   <Select value={String(pageSize)} onValueChange={handlePageSizeChange}>
                    <SelectTrigger className="h-9 bg-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROWS_PER_PAGE_OPTIONS.map(opt => (
                        <SelectItem key={opt} value={String(opt)}>{opt}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Info de Registros (CORREGIDO) */}
              <div className="text-xs font-medium text-gray-500 bg-gray-50 px-3 py-2 rounded-md border border-gray-200 whitespace-nowrap">
                {filteredOrders.length > 0 ? (
                  <>Mostrando <span className="text-gray-900 font-bold">{startIndex}-{endIndex}</span> de <span className="text-gray-900 font-bold">{filteredOrders.length}</span> registros</>
                ) : (
                  <>Sin registros</>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Tabla de Órdenes */}
        <Card className="shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-50 text-gray-500 uppercase border-b">
                <tr>
                  <th className="px-6 py-4 font-semibold">ID Orden</th>
                  <th className="px-6 py-4 font-semibold">Estado</th>
                  <th className="px-6 py-4 font-semibold">Cliente</th>
                  <th className="px-6 py-4 font-semibold text-right">Total</th>
                  <th className="px-6 py-4 font-semibold">Hora</th>
                  <th className="px-6 py-4 font-semibold text-center">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {paginatedOrders.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                      <div className="flex flex-col items-center justify-center">
                        <Package className="w-12 h-12 text-gray-300 mb-3" />
                        <p className="font-medium">No se encontraron órdenes</p>
                        <p className="text-xs mt-1">Intenta ajustar los filtros de búsqueda</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginatedOrders.map((order) => (
                    <tr key={order.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-6 py-4 font-mono text-xs font-medium text-gray-900">
                        #{order.external_id || order.id.slice(0, 8)}
                      </td>
                      <td className="px-6 py-4">
                        <Badge className={`${getStatusColor(order.status)} border font-medium text-xs`}>
                          {order.status}
                        </Badge>
                      </td>
                      <td className="px-6 py-4 font-medium text-gray-900">
                        {order.customer_name || order.customer?.first_name || 'N/A'}
                      </td>
                      <td className="px-6 py-4 text-right font-bold text-gray-900">
                        {formatCurrency(Number(order.total_amount || order.total || 0))}
                      </td>
                      <td className="px-6 py-4 text-gray-500 text-xs">
                        {order.created_at ? new Date(order.created_at).toLocaleString() : '-'}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          className="text-blue-600 hover:text-blue-800 hover:bg-blue-50"
                          onClick={() => router.push(`/operator/orders/${order.id}`)}
                          disabled={isRefreshing}
                        >
                          Ver Detalle
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          
          {/* Controles de Paginación Inferiores */}
          {!isLoading && filteredOrders.length > 0 && (
            <div className="border-t border-gray-200 bg-gray-50 px-6 py-4 flex items-center justify-between">
              <div className="text-xs text-gray-500 hidden md:block">
                Página <span className="font-medium text-gray-900">{page}</span> de <span className="font-medium text-gray-900">{totalPages}</span>
              </div>
              
              <div className="flex items-center gap-2 w-full md:w-auto justify-end">
                <Button 
                  variant="outline" size="sm" onClick={() => handlePageChange(1)} disabled={page === 1}
                  className="h-8 w-8 p-0 hover:bg-white disabled:opacity-50"
                >
                  <ChevronsLeft className="w-4 h-4" />
                </Button>
                <Button 
                  variant="outline" size="sm" onClick={() => handlePageChange(page - 1)} disabled={page === 1}
                  className="h-8 w-8 p-0 hover:bg-white disabled:opacity-50"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                
                <span className="text-sm font-medium text-gray-700 px-2 min-w-[3rem] text-center select-none">
                  {page}
                </span>
                
                <Button 
                  variant="outline" size="sm" onClick={() => handlePageChange(page + 1)} disabled={page >= totalPages}
                  className="h-8 w-8 p-0 hover:bg-white disabled:opacity-50"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
                <Button 
                  variant="outline" size="sm" onClick={() => handlePageChange(totalPages)} disabled={page >= totalPages}
                  className="h-8 w-8 p-0 hover:bg-white disabled:opacity-50"
                >
                  <ChevronsRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}