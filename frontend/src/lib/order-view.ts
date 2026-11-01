import type { Order, OrderAddress, OrderFilters, OrderItem } from '@/types/order';
import { numeric, record, text, validateHttpOrder } from '@/lib/operational-catalog';
import { formatCurrency } from '@/lib/utils';
import { DeliveryStatus } from '@/types/delivery';

const date = (value: unknown): Date | undefined => {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const d = new Date(value);
  return Number.isFinite(d.getTime()) ? d : undefined;
};
const coordinate = (value: unknown, bound: number): number | undefined => {
  const n = numeric(value);
  return n !== undefined && Math.abs(n) <= bound ? n : undefined;
};
const address = (street: unknown, lat: unknown, lng: unknown, reference?: unknown): OrderAddress => ({
  street: text(street) ?? '', latitude: coordinate(lat, 90), longitude: coordinate(lng, 180), reference: text(reference),
});
export function orderView(value: unknown, expectedId?: string): Order {
  validateHttpOrder(value, expectedId);
  const o = record(value);
  const rider = o.assigned_rider != null ? record(o.assigned_rider) : o.rider != null ? record(o.rider) : undefined;
  const delivery = o.delivery != null ? record(o.delivery) : undefined;
  const items = o.items == null ? undefined : (o.items as unknown[]).map((v, index): OrderItem => {
    const i = record(v);
    return { id: text(i.id) ?? `${o.id}:item:${index}`, name: text(i.product_name) ?? text(i.name) ?? 'Artículo sin nombre',
      quantity: numeric(i.quantity), unitPrice: numeric(i.unit_price), totalPrice: numeric(i.subtotal),
      description: text(i.description), observations: text(i.observations) };
  });
  return {
    id: o.id as string, orderNumber: text(o.external_id) ?? '', status: o.status as Order['status'],
    priority: text(o.priority) as Order['priority'],
    customerId: text(o.customer_id), customerName: text(o.customer_name), customerPhone: text(o.customer_phone), customerEmail: text(o.customer_email),
    pickupAddress: address(o.pickup_address, o.pickup_lat, o.pickup_lng),
    deliveryAddress: address(o.delivery_address, o.delivery_lat, o.delivery_lng, o.delivery_reference),
    items, subtotal: numeric(o.subtotal), deliveryFee: numeric(o.delivery_fee), discount: numeric(o.discount),
    total: o.total !== undefined && o.total !== null ? numeric(o.total) : numeric(o.total_amount),
    assignedRiderId: text(o.assigned_rider_id) ?? text(o.rider_id) ?? (rider ? text(rider.id) : undefined),
    assignedRider: rider ? { id: rider.id as string, full_name: text(rider.full_name), first_name: text(rider.first_name), last_name: text(rider.last_name), phone: text(rider.phone) } : undefined,
    delivery: delivery ? {
      id: delivery.id as string, orderId: o.id as string,
      riderId: text(delivery.rider_id), rider_id: text(delivery.rider_id), status: delivery.status as DeliveryStatus,
      started_at: text(delivery.started_at), arrived_pickup_at: text(delivery.arrived_pickup_at),
      left_pickup_at: text(delivery.left_pickup_at), arrived_delivery_at: text(delivery.arrived_delivery_at),
      completed_at: text(delivery.completed_at), sla_expected_minutes: numeric(delivery.sla_expected_minutes),
      sla_actual_minutes: numeric(delivery.sla_actual_minutes), sla_compliant: typeof delivery.sla_compliant === 'boolean' ? delivery.sla_compliant : undefined,
    } : undefined,
    createdAt: date(o.created_at), estimatedDeliveryTime: date(o.estimated_delivery_time),
    pickedUpAt: date(o.picked_up_at), deliveredAt: date(o.delivered_at),
    paymentMethod: text(o.payment_method)?.toUpperCase() as Order['paymentMethod'],
    paymentStatus: text(o.payment_status)?.toUpperCase() as Order['paymentStatus'],
    observations: text(o.notes), cancellation_reason: text(o.cancellation_reason), cancelled_by: text(o.cancelled_by),
    createdBy: text(o.created_by),
  };
}
export const amountLabel = (value: number | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? formatCurrency(value) : 'No informado';
export const itemCount = (items: OrderItem[] | undefined): number | undefined =>
  items && items.every(i => i.quantity !== undefined) ? items.reduce((sum, i) => sum + i.quantity!, 0) : undefined;
export const paymentLabel = (value: string | undefined): string => value ? ({
  EFECTIVO: 'Efectivo', TARJETA: 'Tarjeta', PIX: 'PIX', ONLINE: 'Online', DEBIT_CARD: 'Débito',
} as Record<string, string>)[value] ?? value : 'Método no informado';

/** First assignment only; the backend remains the final authority. */
export function canAssignOrder(order: Pick<Order, 'status' | 'assignedRiderId' | 'assignedRider' | 'delivery'>): boolean {
  return order.status === 'PENDIENTE' && !order.assignedRiderId && !order.assignedRider && !order.delivery?.riderId && !order.delivery?.rider_id &&
    (!order.delivery || order.delivery.status === DeliveryStatus.PENDIENTE);
}
export function filterOrderViews(orders: Order[], f: OrderFilters): Order[] {
  const from = f.dateFrom?.getTime(), to = f.dateTo?.getTime();
  if (from !== undefined && !Number.isFinite(from) || to !== undefined && !Number.isFinite(to)) throw new Error('Fecha de filtro inválida');
  return orders.filter(o => (!f.status?.length || f.status.includes(o.status)) &&
    (!f.priority?.length || !!o.priority && f.priority.includes(o.priority)) &&
    (!f.type?.length || !!o.type && f.type.includes(o.type)) &&
    (!f.riderId || o.assignedRiderId === f.riderId) &&
    (from === undefined || !!o.createdAt && o.createdAt.getTime() >= from) &&
    (to === undefined || !!o.createdAt && o.createdAt.getTime() <= to) &&
    (!f.paymentStatus || o.paymentStatus === f.paymentStatus) &&
    (!f.search || [o.id, o.orderNumber, o.customerName, o.customerPhone, o.pickupAddress.street, o.deliveryAddress.street]
      .some(v => v?.toLowerCase().includes(f.search!.toLowerCase()))));
}
