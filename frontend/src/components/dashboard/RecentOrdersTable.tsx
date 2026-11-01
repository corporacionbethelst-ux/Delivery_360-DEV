import { useState } from 'react'; 
import { canAssignOrder } from '@/lib/order-view';
import OrderStatusBadge from '@/components/orders/OrderStatusBadge';
import { Order } from '@/types/order';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';
import { Eye, Truck, Phone, MapPin } from 'lucide-react';

interface RecentOrdersTableProps {
  orders: Order[];
  onViewOrder?: (order: Order) => void;
  onAssignRider?: (order: Order) => void;
}

export function RecentOrdersTable({ orders, onViewOrder, onAssignRider }: RecentOrdersTableProps) {
  const [filter, setFilter] = useState<'all' | 'pending' | 'active'>('all');

  const filteredOrders = orders.filter(order => {
    if (filter === 'all') return true;
    if (filter === 'pending') return ['PENDIENTE'].includes(order.status);
    if (filter === 'active') return ['ASIGNADO', 'EN_RECOLECCION', 'RECOLECTADO', 'EN_RUTA'].includes(order.status);
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Pedidos Recientes</h3>
        <div className="flex gap-2">
          <Button variant={filter === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setFilter('all')}>Todos</Button>
          <Button variant={filter === 'pending' ? 'default' : 'outline'} size="sm" onClick={() => setFilter('pending')}>Pendientes</Button>
          <Button variant={filter === 'active' ? 'default' : 'outline'} size="sm" onClick={() => setFilter('active')}>Activos</Button>
        </div>
      </div>

      <div className="rounded-md border">
        <table className="w-full">
          <thead className="bg-muted">
            <tr>
              <th className="p-3 text-left font-medium">ID</th>
              <th className="p-3 text-left font-medium">Cliente</th>
              <th className="p-3 text-left font-medium">Dirección</th>
              <th className="p-3 text-left font-medium">Estado</th>
              <th className="p-3 text-left font-medium">Repartidor</th>
              <th className="p-3 text-left font-medium">Tiempo</th>
              <th className="p-3 text-left font-medium">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {filteredOrders.map(order => {
              
              // ✅ CORRECCIÓN LÍNEAS 71-72: Acceso seguro directo sin casts complejos
              const customerName = 
                (order as any).customerName || 
                (order as any).customer_name || 
                order.id.slice(0, 8);
              
              // ✅ CORRECCIÓN LÍNEA 76: Manejo flexible de dirección
              const deliveryAddress = order.deliveryAddress;
              const address = typeof deliveryAddress === 'string' 
                ? deliveryAddress 
                : deliveryAddress?.street ||
                  'Sin dirección';

              // ✅ CORRECCIÓN LÍNEA 84: Acceso seguro al repartidor
              const assignedRider = (order as any).assigned_rider || (order as any).assignedRider;
              const riderName = assignedRider 
                ? assignedRider.full_name || 
                  assignedRider.fullName || 
                  assignedRider.first_name || 
                  'Repartidor' 
                : null;

              return (
                <tr key={order.id} className="border-t hover:bg-muted/50">
                  <td className="p-3 font-mono text-sm">{order.id.slice(0, 8)}</td>
                  <td className="p-3">
                    <div className="font-medium">{customerName}</div>
                  </td>
                  <td className="p-3 max-w-xs truncate">
                    <div className="flex items-center gap-1">
                      <MapPin className="h-3 w-3 text-muted-foreground" />
                      <span className="truncate">{address}</span>
                    </div>
                  </td>
                  <td className="p-3">
                    <OrderStatusBadge status={order.status} />
                  </td>
                  {/* ✅ CORRECCIÓN LÍNEA 96: Renderizado condicional seguro */}
                  <td className="p-3">
                    {assignedRider ? (
                      <div className="flex items-center gap-2">
                        <Truck className="h-4 w-4 text-muted-foreground" />
                        <span>{riderName}</span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground text-sm">{order.assignedRiderId || order.delivery?.riderId || order.delivery?.rider_id ? 'Asignado (datos no informados)' : 'Sin asignar'}</span>
                    )}
                  </td>
                  <td className="p-3 text-sm text-muted-foreground">
                    {order.createdAt && Number.isFinite(order.createdAt.getTime()) ? formatDistanceToNow(order.createdAt, { addSuffix: true, locale: es }) : 'No informada'}
                  </td>
                  {/* ✅ CORRECCIÓN LÍNEA 101: Acciones seguras */}
                  <td className="p-3">
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => onViewOrder?.(order)}>
                        <Eye className="h-4 w-4" />
                      </Button>
                      {canAssignOrder(order) && (
                        <Button aria-label="Asignar repartidor" variant="default" size="sm" onClick={() => onAssignRider?.(order)}>
                          <Truck className="h-4 w-4" />
                        </Button>
                      )}
                      <Button variant="outline" size="sm">
                        <Phone className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filteredOrders.length === 0 && (
          <div className="p-8 text-center text-muted-foreground">No hay pedidos recientes</div>
        )}
      </div>
    </div>
  );
}
