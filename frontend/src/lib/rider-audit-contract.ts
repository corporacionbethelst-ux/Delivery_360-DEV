import { record, validateHttpOrder } from '@/lib/operational-catalog';
import { summaryDate } from '@/lib/financial-summary-contract';
import { transactionId } from '@/lib/transaction-contract';
import { DeliveryStatus } from '@/types/delivery';

export const AUDIT_PAGE_SIZE = 50;
export const RIDER_AUDIT_STATUSES = ['ACTIVO', 'INACTIVO', 'OCUPADO', 'PENDIENTE', 'SUSPENDIDO'] as const;
export const AUDIT_SUMMARY_PAGE_SIZE = 100;
export const AUDIT_SUMMARY_MAX_PAGES = 5;
const invalid = (): never => { throw new Error('La auditoría está incompleta o no coincide con el repartidor solicitado'); };
export const auditId = transactionId;
const text = (value: unknown): string | null => value == null ? null : typeof value === 'string' ? value : invalid();
const date = (value: unknown): string | null => value == null ? null : summaryDate(value).iso;
const count = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid();
export const auditMoney = (value: unknown): number => {
  if ((typeof value !== 'number' && typeof value !== 'string') || !/^-?\d+(?:\.\d{1,2})?$/.test(String(value))) return invalid();
  const cents = Math.round(Number(value) * 100);
  return Number.isSafeInteger(cents) ? cents === 0 ? 0 : cents / 100 : invalid();
};
const optionalMoney = (value: unknown): number | null => value == null ? null : auditMoney(value);
const currency = (value: unknown): string | null => value == null ? null : typeof value === 'string' && /^[A-Z]{3}$/.test(value) ? value : invalid();
const sameId = (value: unknown, expected: string): string => auditId(value) === expected ? expected : invalid();
const coordinate = (value: unknown, max: number): number | null => value == null ? null : typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= max ? value : invalid();

export function normalizeAuditSummary(value: unknown) {
  const row = record(value);
  const counts = {
    orders_assigned: count(row.orders_assigned), orders_delivered: count(row.orders_delivered), orders_active: count(row.orders_active),
    deliveries_total: count(row.deliveries_total), deliveries_completed: count(row.deliveries_completed),
    deliveries_failed: count(row.deliveries_failed), deliveries_in_progress: count(row.deliveries_in_progress), sla_compliant: count(row.sla_compliant),
  };
  if (counts.orders_delivered + counts.orders_active > counts.orders_assigned ||
      counts.deliveries_completed + counts.deliveries_failed + counts.deliveries_in_progress > counts.deliveries_total || counts.sla_compliant > counts.deliveries_total) return invalid();
  const rate = row.sla_compliance_rate;
  const expectedRate = counts.deliveries_total ? counts.sla_compliant / counts.deliveries_total * 100 : 0;
  if (typeof rate !== 'number' || !Number.isFinite(rate) || rate < 0 || rate > 100 || Math.abs(rate - expectedRate) > 0.005 + Number.EPSILON * 100) return invalid();
  const earned = auditMoney(row.total_earned), pending = auditMoney(row.pending_payouts);
  // This legacy derived field subtracts binary floats in Python, without rounding.
  // Validate its calculation without applying cent precision to the float residue.
  const available = typeof row.available_to_payout === 'number' ? row.available_to_payout : auditMoney(row.available_to_payout);
  const expectedAvailable = Math.max(0, earned - pending);
  if (pending < 0 || !Number.isFinite(available) || Math.abs(available - expectedAvailable) > Number.EPSILON * Math.max(1, Math.abs(expectedAvailable)) * 4) return invalid();
  if (row.status != null && !RIDER_AUDIT_STATUSES.includes(row.status as never)) return invalid();
  if (row.is_online != null && typeof row.is_online !== 'boolean') return invalid();
  return { ...counts, rider_id: auditId(row.rider_id), user_id: auditId(row.user_id),
    full_name: text(row.full_name), email: text(row.email), phone: text(row.phone), status: text(row.status),
    vehicle_type: text(row.vehicle_type), vehicle_plate: text(row.vehicle_plate), operating_zone: text(row.operating_zone),
    zone_id: row.zone_id == null ? null : auditId(row.zone_id), current_order_id: row.current_order_id == null ? null : auditId(row.current_order_id),
    is_online: row.is_online == null ? null : row.is_online as boolean,
    last_lat: coordinate(row.last_lat, 90), last_lng: coordinate(row.last_lng, 180), last_location_at: date(row.last_location_at),
    sla_compliance_rate: rate, total_earned: earned, pending_payouts: pending, currency: currency(row.currency) };
}
export type AuditSummary = ReturnType<typeof normalizeAuditSummary>;
export function normalizeSummaryPage(value: unknown, offset: number, limit = AUDIT_SUMMARY_PAGE_SIZE) {
  const envelope = record(value);
  if ((!Number.isInteger(limit) || limit < 1 || limit > 500) || envelope.limit !== limit || envelope.offset !== offset || !Array.isArray(envelope.items) || envelope.items.length > limit || envelope.total !== envelope.items.length) return invalid();
  const ids = new Set<string>(), users = new Set<string>();
  return envelope.items.map(value => {
    const row = normalizeAuditSummary(value);
    if (ids.has(row.rider_id) || users.has(row.user_id)) return invalid();
    ids.add(row.rider_id); users.add(row.user_id); return row;
  });
}

export function normalizeAuditOrder(value: unknown, riderId: string) {
  validateHttpOrder(value);
  const row = record(value), total = optionalMoney(row.total), alias = optionalMoney(row.total_amount);
  if (total !== null && alias !== null && total !== alias) return invalid();
  sameId(row.assigned_rider_id ?? row.rider_id, riderId);
  return { id: auditId(row.id), external_id: text(row.external_id), customer_name: text(row.customer_name),
    status: row.status as string, amount: total ?? alias, currency: currency(row.currency), created_at: date(row.created_at) };
}
export type AuditOrder = ReturnType<typeof normalizeAuditOrder>;
export function normalizeAuditDelivery(value: unknown, riderId: string) {
  const row = record(value), orderId = auditId(row.order_id), id = auditId(row.id);
  sameId(row.rider_id, riderId);
  if (row.rider != null) sameId(record(row.rider).id, riderId);
  if (row.orderId !== undefined) sameId(row.orderId, orderId);
  if (row.riderId !== undefined) sameId(row.riderId, riderId);
  if (!Object.values(DeliveryStatus).includes(row.status as DeliveryStatus)) return invalid();
  const fallback = id.startsWith('order-');
  if (fallback && id !== `order-${orderId}`) return invalid();
  const bonus = optionalMoney(row.locked_bonus_amount);
  if (row.bonus_breakdown != null && (bonus === null || auditMoney(record(row.bonus_breakdown).total) !== bonus)) return invalid();
  return { id, order_id: orderId, external_id: text(row.external_id), customer_name: text(row.customer_name),
    status: row.status as string, locked_bonus_amount: bonus, currency: currency(row.currency),
    created_at: date(row.created_at), updated_at: date(row.updated_at), fallback };
}
export type AuditDelivery = ReturnType<typeof normalizeAuditDelivery>;
export interface AuditPage<T> { rows: T[]; offset: number; hasNext: boolean }
export function boundedAuditPage<T extends { id: string }>(value: unknown, offset: number, adapt: (row: unknown) => T): AuditPage<T> {
  if (!Array.isArray(value) || value.length > AUDIT_PAGE_SIZE + 1) return invalid();
  const ids = new Set<string>();
  const rows = value.map(value => { const row = adapt(value); if (ids.has(row.id)) return invalid(); ids.add(row.id); return row; });
  return { rows: rows.slice(0, AUDIT_PAGE_SIZE), offset, hasNext: rows.length > AUDIT_PAGE_SIZE };
}
export function normalizeAuditDeliveries(value: unknown, riderId: string, offset: number) {
  const envelope = record(value);
  if (!Array.isArray(envelope.items) || envelope.limit !== AUDIT_PAGE_SIZE + 1 || envelope.offset !== offset) return invalid();
  const items = envelope.items.map(value => normalizeAuditDelivery(value, riderId));
  if (new Set(items.map(row => row.id)).size !== items.length) return invalid();
  const real = items.filter(row => !row.fallback), fallback = items.filter(row => row.fallback);
  if (fallback.length > 50 || offset > 0 && fallback.length > 0 || fallback.some(row => real.some(item => item.order_id === row.order_id))) return invalid();
  // The legacy endpoint appends up to 50 fallback orders only at offset zero.
  // Its total includes those fallback rows only in that first response.
  const realTotal = count(envelope.total) - fallback.length;
  if (realTotal < 0 || real.length !== Math.min(AUDIT_PAGE_SIZE + 1, Math.max(realTotal - offset, 0))) return invalid();
  return { ...boundedAuditPage(real, offset, row => row as AuditDelivery), fallback };
}
export interface AuditOffsets { orders: number; deliveries: number; transactions: number }
export const initialAuditOffsets: AuditOffsets = { orders: 0, deliveries: 0, transactions: 0 };
export function prepareAuditOffsets(value: Readonly<AuditOffsets>): AuditOffsets {
  if (Object.keys(value).some(key => !Object.keys(initialAuditOffsets).includes(key))) return invalid();
  const result = { ...value };
  if (Object.values(result).length !== 3 || Object.values(result).some(offset => !Number.isSafeInteger(offset) || offset < 0 || offset % AUDIT_PAGE_SIZE !== 0)) return invalid();
  return result;
}
