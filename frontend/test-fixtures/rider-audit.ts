import { transactionResponse } from './transactions';
export const auditSummaryResponse = (id = 'rider-1', changes: Record<string, unknown> = {}) => ({ rider_id: id, user_id: `user-${id}`, full_name: 'José Rider', email: 'rider@example.test', status: 'ACTIVO', is_online: false,
  orders_assigned: 9, orders_delivered: 3, orders_active: 4, deliveries_total: 8, deliveries_completed: 3, deliveries_failed: 1, deliveries_in_progress: 2, sla_compliant: 4, sla_compliance_rate: 50,
  total_earned: 25, pending_payouts: 5, available_to_payout: 20, last_lat: 0, last_lng: 0, last_location_at: '2026-11-07T12:00:00', ...changes });
export const auditOrderResponse = (id = 'order-1', rider = 'rider-1', changes: Record<string, unknown> = {}) => ({ id, external_id: 'EXT-1', assigned_rider_id: rider, rider_id: rider, status: 'ASIGNADO', customer_name: 'Ana', total: 0, created_at: '2026-11-07T12:00:00', ...changes });
export const auditDeliveryResponse = (id = 'delivery-1', rider = 'rider-1', changes: Record<string, unknown> = {}) => ({ id, order_id: `order-for-${id}`, rider_id: rider, status: 'COMPLETADA', customer_name: 'Ana', locked_bonus_amount: 0, updated_at: '2026-11-07T12:00:00', ...changes });
export const auditTransactionResponse = (id = 'tx-1', rider = 'rider-1') => transactionResponse(id, { rider_id: rider });
export const auditSummaryPage = (items = [auditSummaryResponse()], offset = 0) => ({ items, limit: 100, offset, total: items.length });
export const auditDeliveryPage = (items = [auditDeliveryResponse()], offset = 0, total = items.length) => ({ items, limit: 51, offset, total });
export function auditHttpResponse(url: string, total = 73, riderId = 'rider-1') {
  const parsed = new URL(url, 'https://test.invalid'), offset = Number(parsed.searchParams.get('offset') ?? 0);
  const indexes = Array.from({ length: Math.max(0, Math.min(51, total - offset)) }, (_, i) => i + offset);
  if (parsed.pathname === '/riders/audit/summary') return auditSummaryPage([auditSummaryResponse(riderId)]);
  if (parsed.pathname === '/orders') return indexes.map(i => auditOrderResponse(`o-${i}`, riderId));
  if (parsed.pathname === '/deliveries') return auditDeliveryPage(indexes.map(i => auditDeliveryResponse(`d-${i}`, riderId)), offset, total);
  if (parsed.pathname === '/financial/transactions') return indexes.map(i => auditTransactionResponse(`tx-${i}`, riderId));
  throw new Error(`Unexpected HTTP path: ${parsed.pathname}`);
}
