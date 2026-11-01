'use client';

import React, { useState, useEffect, useRef, useSyncExternalStore } from 'react';
import { Order } from '@/types/order';
import OrderCard from './OrderCard';
import AssignRiderModal from './AssignRiderModal';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Search, Filter, ListFilter, X } from 'lucide-react';
import { useOrdersStore } from '@/stores/ordersStore';
import { Badge } from '@/components/ui/badge';
import type { OrderAssignmentPatch } from '@/lib/order-assignment';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { ORDER_STATUSES } from '@/lib/operational-catalog';
import { canAssignOrder } from '@/lib/order-view';
import { capturePrivateTask } from '@/lib/private-task';

interface OrderListProps {
  orders?: Order[];
  showFilters?: boolean;
  showActions?: boolean;
  onOrderSelect?: (order: Order) => void;
  compact?: boolean;
}

export default function OrderList(props: OrderListProps) {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  return <SessionOrderList key={generation} {...props} />;
}

function SessionOrderList({
  orders, 
  showFilters = true, 
  showActions = false,
  onOrderSelect,
  compact = false 
}: OrderListProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [priorityFilter, setPriorityFilter] = useState<string>('ALL');
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [confirmations, setConfirmations] = useState<Map<string, { original: Order; patch: OrderAssignmentPatch }>>(() => new Map());
  
  const { assignRider, orders: storeOrders } = useOrdersStore();
  
  const source = orders ?? storeOrders;
  const currentSource = useRef(source);
  currentSource.current = source;
  useEffect(() => {
    setConfirmations(previous => {
      const next = new Map(Array.from(previous).filter(([id, c]) => source.some(o => o.id === id && o === c.original)));
      return next.size === previous.size ? previous : next;
    });
    setSelectedOrder(previous => previous ? source.find(o => o.id === previous.id) ?? null : null);
  }, [source]);
  const orderList = source.map(order => {
    const confirmation = confirmations.get(order.id);
    return confirmation?.original === order ? { ...order, ...confirmation.patch } : order;
  });

  // Filtrar órdenes
  const filteredOrders = orderList.filter(order => {
    const searchLower = searchTerm.toLowerCase();
    
    // Búsqueda por campos disponibles en la interfaz Order
    const matchesSearch = 
      order.id.toLowerCase().includes(searchLower) ||
      (order.orderNumber && order.orderNumber.toLowerCase().includes(searchLower)) ||
      (order.customerName && order.customerName.toLowerCase().includes(searchLower)) ||
      (order.pickupAddress?.street && order.pickupAddress.street.toLowerCase().includes(searchLower));
    
    // Comparación normalizada a mayúsculas
    const orderStatus = order.status?.toUpperCase();
    const orderPriority = order.priority?.toUpperCase();

    const matchesStatus = statusFilter === 'ALL' || orderStatus === statusFilter;
    const matchesPriority = priorityFilter === 'ALL' || orderPriority === priorityFilter;
    
    return matchesSearch && matchesStatus && matchesPriority;
  });

  const handleAssignRider = (orderId: string) => {
    const order = orderList.find(o => o.id === orderId);
    if (order && canAssignOrder(order)) {
      setSelectedOrder(order);
      setShowAssignModal(true);
    }
  };

  const clearFilters = () => {
    setSearchTerm('');
    setStatusFilter('ALL');
    setPriorityFilter('ALL');
  };

  const hasActiveFilters = searchTerm || statusFilter !== 'ALL' || priorityFilter !== 'ALL';

  // Contar estados para resumen
  const statusCounts = orderList.reduce((acc, order) => {
    const status = order.status || 'UNKNOWN';
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="space-y-4">
      {/* Filters */}
      {showFilters && (
        <div className="bg-white p-4 rounded-lg shadow-sm border space-y-4">
          <div className="flex flex-col md:flex-row gap-4">
            {/* Search */}
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
              <Input
                placeholder="Buscar por ID, cliente o dirección..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            
            {/* Status Filter */}
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-full md:w-[180px]">
                <SelectValue placeholder="Estado" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Todos los estados</SelectItem>
                {ORDER_STATUSES.map(status => <SelectItem key={status} value={status}>{status.replaceAll('_', ' ')}</SelectItem>)}
              </SelectContent>
            </Select>
            
            {/* Priority Filter */}
            <Select value={priorityFilter} onValueChange={setPriorityFilter}>
              <SelectTrigger className="w-full md:w-[150px]">
                <SelectValue placeholder="Prioridad" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Todas</SelectItem>
                <SelectItem value="URGENTE">🔥 Urgente</SelectItem>
                <SelectItem value="ALTA">⚡ Alta</SelectItem>
                <SelectItem value="NORMAL">📋 Normal</SelectItem>
                <SelectItem value="MEDIA">Media (legacy)</SelectItem>
                <SelectItem value="BAJA">🐌 Baja</SelectItem>
              </SelectContent>
            </Select>
            
            {/* Clear Filters */}
            {hasActiveFilters && (
              <Button variant="outline" onClick={clearFilters} className="gap-2">
                <X className="w-4 h-4" />
                Limpiar
              </Button>
            )}
          </div>
          
          {/* Status Summary */}
          <div className="flex flex-wrap gap-2 pt-2 border-t">
            <Badge variant="outline" className="gap-1">
              <ListFilter className="w-3 h-3" />
              {filteredOrders.length} de {orderList.length} órdenes
            </Badge>
            {Object.entries(statusCounts).map(([status, count]) => {
              // Mapeo simple de emoji según estado (puedes mejorarlo)
              let emoji = '⚪';
              if (status.includes('PENDIENTE')) emoji = '🟡';
              if (status.includes('CONFIRMADO') || status.includes('ASIGNADO')) emoji = '🔵';
              if (status.includes('PREPARACION')) emoji = '🟣';
              if (status.includes('LISTO')) emoji = '🔷';
              if (status.includes('CAMINO') || status.includes('RECOGIENDO')) emoji = '🚚';
              if (status.includes('ENTREGADO')) emoji = '✅';
              if (status.includes('CANCELADO')) emoji = '❌';

              return (
                <Badge 
                  key={status} 
                  variant="outline"
                  className={`cursor-pointer hover:bg-gray-100 ${statusFilter === status ? 'bg-gray-100' : ''}`}
                  onClick={() => setStatusFilter(statusFilter === status ? 'ALL' : status)}
                >
                  {emoji} {count}
                </Badge>
              );
            })}
          </div>
        </div>
      )}
      
      {/* Order List */}
      <div className={`space-y-4 ${compact ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3' : ''}`}>
        {filteredOrders.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg border">
            <div className="text-gray-400 mb-2">
              <ListFilter className="w-12 h-12 mx-auto" />
            </div>
            <h3 className="text-lg font-medium text-gray-900">No se encontraron órdenes</h3>
            <p className="text-gray-500 mt-1">
              {hasActiveFilters 
                ? 'Intenta ajustar los filtros de búsqueda' 
                : 'Comienza creando una nueva orden'}
            </p>
            {hasActiveFilters && (
              <Button variant="link" onClick={clearFilters} className="mt-2">
                Limpiar filtros
              </Button>
            )}
          </div>
        ) : (
          filteredOrders.map((order) => (
            <OrderCard
              key={order.id}
              order={order}
              onSelect={onOrderSelect || ((o) => setSelectedOrder(o))}
              onAssignRider={handleAssignRider}
              showActions={showActions}
            />
          ))
        )}
      </div>
      
      {/* Assign Rider Modal */}
      {selectedOrder && showAssignModal && (
        <AssignRiderModal
          order={selectedOrder}
          onClose={() => {
            setShowAssignModal(false);
            setSelectedOrder(null);
          }}
          onAssign={async (riderId) => {
            const task = capturePrivateTask();
            const original = source.find(o => o.id === selectedOrder.id);
            if (!original || !canAssignOrder(original)) throw new Error("El pedido cambió; revisa su estado");
            const patch = await assignRider(original.id, riderId);
            task.assertCurrent();
            if (currentSource.current.includes(original)) {
              setConfirmations(previous => new Map(previous).set(original.id, { original, patch }));
            }
            setShowAssignModal(false);
            setSelectedOrder(null);
          }}
        />
      )}
    </div>
  );
}
