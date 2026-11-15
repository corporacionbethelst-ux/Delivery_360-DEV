// Synthetic values only: production exact amounts always arrive as decimal strings.
export function auditExactFixtureMoney(changes: Record<string, unknown> = {}) {
 const credit = Number(changes.total_earned ?? 25), pending = Number(changes.pending_payouts ?? 5);
 return {credit_usd:credit.toFixed(2),debit_usd:'0.00',adjustment_usd:'0.00',net_change_usd:credit.toFixed(2),pending_usd:pending.toFixed(2),ledger_rows:1,ledger_included:1,payout_rows:1,payout_included:1,
 ledger_exclusions:['FECHA_NO_REGISTRADA','MONEDA_NO_VERIFICADA','FECHA_FUTURA','ESTADO_NO_PROCESADO','TIPO_NO_ADMITIDO'].map(reason=>({reason,count:0})),
 payout_exclusions:['FECHA_NO_REGISTRADA','MONEDA_NO_VERIFICADA','FECHA_FUTURA','ESTADO_NO_PENDIENTE'].map(reason=>({reason,count:0}))};
}
export function exactAuditEnvelope(items: unknown[], params = new URLSearchParams('limit=51&offset=0')) {
 return {version:1,scope:'operational_rider_audit_usd',currency:'USD',viewer_user_id:'a',viewer_role:'GERENTE',generated_at:'2026-11-15T16:00:00.123456Z',snapshot_basis:'single_statement_visibility',ledger_basis:'processed_registered_movements',payout_basis:'current_pending_requests',available_balance_included:false,bank_verified:false,wallet_cents_included:false,content_sha256:'a'.repeat(64),filters:{status:params.get('status_filter'),online:params.has('is_online')?params.get('is_online')==='true':null,rider_id:params.get('rider_id')},limit:Number(params.get('limit')??51),offset:Number(params.get('offset')??0),total:items.length,items};
}
import { transactionResponse } from './transactions';
export const auditSummaryResponse = (id = 'rider-1', changes: Record<string, unknown> = {}) => ({ money: auditExactFixtureMoney(changes), rider_id: id, user_id: `user-${id}`, full_name: 'José Rider', email: 'rider@example.test', status: 'ACTIVO', is_online: false,
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
  if (parsed.pathname === '/riders/audit/summary/exact') return exactAuditEnvelope([auditSummaryResponse(riderId)], parsed.searchParams);
  if (parsed.pathname === '/riders/audit/summary') return auditSummaryPage([auditSummaryResponse(riderId)]);
  if (parsed.pathname === '/orders') return indexes.map(i => auditOrderResponse(`o-${i}`, riderId));
  if (parsed.pathname === '/deliveries') return auditDeliveryPage(indexes.map(i => auditDeliveryResponse(`d-${i}`, riderId)), offset, total);
  if (parsed.pathname === '/financial/transactions') return indexes.map(i => auditTransactionResponse(`tx-${i}`, riderId));
  throw new Error(`Unexpected HTTP path: ${parsed.pathname}`);
}
