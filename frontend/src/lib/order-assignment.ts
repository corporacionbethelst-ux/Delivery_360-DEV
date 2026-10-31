import type { Order, OrderAssignedRider } from '@/types/order';
import { DeliveryStatus } from '@/types/delivery';

export type OrderAssignmentPatch = Pick<Order, 'status' | 'assignedRiderId' | 'assignedRider' | 'delivery'>;

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('La confirmación de asignación está incompleta; recarga el pedido');
  }
  return value as Record<string, unknown>;
};
const optionalText = (value: unknown): string | undefined => typeof value === 'string' ? value : undefined;
const timestamp = (value: unknown): string | null | undefined => value === null ? null : optionalText(value);
const metric = (value: unknown): number | null | undefined => value === null ? null :
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

/** Project only the assignment confirmed by the API, without replacing money or addresses. */
export function orderAssignmentPatch(value: unknown, orderId: string, riderId: string): OrderAssignmentPatch {
  const order = record(value), rider = record(order.assigned_rider), delivery = record(order.delivery);
  if (order.id !== orderId || order.status !== 'ASIGNADO' || order.assigned_rider_id !== riderId ||
      rider.id !== riderId || typeof delivery.id !== 'string' || !delivery.id ||
      delivery.order_id !== orderId || delivery.rider_id !== riderId || delivery.status !== 'INICIADA') {
    throw new Error('La confirmación de asignación no coincide; recarga el pedido');
  }
  const assignedRider: OrderAssignedRider = {
    id: riderId,
    full_name: optionalText(rider.full_name), first_name: optionalText(rider.first_name),
    last_name: optionalText(rider.last_name), phone: optionalText(rider.phone),
  };
  return {
    status: 'ASIGNADO', assignedRiderId: riderId, assignedRider,
    delivery: {
      id: delivery.id, orderId, riderId, rider_id: riderId, status: DeliveryStatus.INICIADA,
      started_at: timestamp(delivery.started_at), arrived_pickup_at: timestamp(delivery.arrived_pickup_at),
      left_pickup_at: timestamp(delivery.left_pickup_at), arrived_delivery_at: timestamp(delivery.arrived_delivery_at),
      completed_at: timestamp(delivery.completed_at),
      sla_expected_minutes: metric(delivery.sla_expected_minutes), sla_actual_minutes: metric(delivery.sla_actual_minutes),
      sla_compliant: delivery.sla_compliant === null ? null : typeof delivery.sla_compliant === 'boolean' ? delivery.sla_compliant : undefined,
    },
  };
}
