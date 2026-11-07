import { normalizeAuditSummary, normalizeSummaryPage, normalizeAuditOrder, normalizeAuditDelivery, normalizeAuditDeliveries, boundedAuditPage, prepareAuditOffsets, initialAuditOffsets } from '@/lib/rider-audit-contract';
import { auditSummaryResponse as summary, auditSummaryPage, auditOrderResponse as order, auditDeliveryResponse as delivery, auditDeliveryPage } from '../../test-fixtures/rider-audit';

it('keeps zero coordinates/money and unknown fields instead of inventing currency, dates or availability', () => {
  const result = normalizeAuditSummary(summary('rider-1', { full_name: null, status: null, is_online: null, last_location_at: null, total_earned: 0, pending_payouts: 0, available_to_payout: 0 }));
  expect(result).toMatchObject({ full_name: null, is_online: null, status: null, last_lat: 0, last_lng: 0, currency: null, last_location_at: null, total_earned: 0 });
});
it('canonicalizes actual UUIDs without conflating user and rider identities', () => {
  const id = '12345678-ABCD-1234-ABCD-123456789012'; const result = normalizeAuditSummary(summary(id));
  expect(result.rider_id).toBe(id.toLowerCase()); expect(result.user_id).toBe(`user-${id}`);
});
it.each([
  { orders_assigned: -1 }, { orders_active: 1.5 }, { deliveries_total: '8' }, { deliveries_completed: 9 }, { deliveries_failed: 6 },
  { orders_delivered: 6 }, { sla_compliant: 9 }, { sla_compliance_rate: 49 }, { sla_compliance_rate: NaN },
  { total_earned: '' }, { total_earned: true }, { total_earned: '1.001' }, { pending_payouts: -1 }, { available_to_payout: 19 },
  { total_earned: Number.MAX_SAFE_INTEGER }, { rider_id: '' }, { user_id: null }, { status: 'UNKNOWN' }, { is_online: 'false' },
  { last_lat: 91 }, { last_lng: -181 }, { last_lat: '' }, { last_location_at: '2026-02-30' }, { currency: 'cop' }, { email: {} },
])('rejects contradictory or malformed aggregate fields: %j', changes => expect(() => normalizeAuditSummary(summary('rider-1', changes))).toThrow());
it('handles zero SLA denominator and clamped legacy availability without claiming it is a bank balance', () => {
  expect(normalizeAuditSummary(summary('rider-1', { deliveries_total: 0, deliveries_completed: 0, deliveries_failed: 0, deliveries_in_progress: 0, sla_compliant: 0, sla_compliance_rate: 0, total_earned: -5, available_to_payout: 0 })).total_earned).toBe(-5);
});
it.each([null, [], { items: null }, auditSummaryPage([summary(), summary()]), auditSummaryPage([summary(), summary('other', { user_id: 'user-rider-1' })]), { ...auditSummaryPage(), total: 1000 }, { ...auditSummaryPage(), limit: 500 }, { ...auditSummaryPage(), offset: 100 }])('rejects malformed summary envelope/duplicate identities/false global totals', value => expect(() => normalizeSummaryPage(value, 0)).toThrow());
it('treats summary.total as the row count, including a full page', () => {
  const rows = Array.from({ length: 100 }, (_, i) => summary(`r-${i}`)); expect(normalizeSummaryPage(auditSummaryPage(rows), 0)).toHaveLength(100);
});
it('uses actual order fields, zero totals and UTC, leaving missing amounts unknown', () => {
  expect(normalizeAuditOrder(order(), 'rider-1')).toMatchObject({ amount: 0, currency: null, created_at: '2026-11-07T12:00:00Z' });
  expect(normalizeAuditOrder(order('o', 'rider-1', { total: null, created_at: null }), 'rider-1')).toMatchObject({ amount: null, created_at: null });
});
it.each([{ rider_id: 'other' }, { assigned_rider_id: 'other', rider_id: 'other' }, { total_amount: 1 }, { status: 'COMPLETADA' }, { created_at: 'yesterday' }, { total: 'abc' }, { currency: 'COPX' }, { delivery: { id: 'd', status: 'COMPLETADA', order_id: 'other' } }])('rejects unrelated or contradictory order rows: %j', changes => expect(() => normalizeAuditOrder(order('order-1', 'rider-1', changes), 'rider-1')).toThrow());
it('adapts snake_case delivery identity/date and preserves a frozen zero bonus', () => {
  const result = normalizeAuditDelivery(delivery('d', 'rider-1', { created_at: '2026-11-07T08:00:00-04:00', updated_at: null }), 'rider-1');
  expect(result).toMatchObject({ order_id: 'order-for-d', locked_bonus_amount: 0, currency: null, created_at: '2026-11-07T08:00:00-04:00', updated_at: null, fallback: false });
  expect(normalizeAuditDelivery(delivery('d', 'rider-1', { locked_bonus_amount: null }), 'rider-1').locked_bonus_amount).toBeNull();
});
it.each([{ rider_id: 'other' }, { rider: { id: 'other' } }, { riderId: 'other' }, { orderId: 'other' }, { order_id: '' }, { id: 'order-wrong' }, { status: 'ENTREGADO' }, { locked_bonus_amount: '2x' }, { bonus_breakdown: { total: 2 } }, { updated_at: false }])('rejects a delivery outside the captured relation/contract: %j', changes => expect(() => normalizeAuditDelivery(delivery('d', 'rider-1', changes), 'rider-1')).toThrow());
it('separates legacy fallback orders from registered deliveries and their pagination signal', () => {
  const real = Array.from({ length: 51 }, (_, i) => delivery(`d-${i}`));
  const fallback = Array.from({ length: 50 }, (_, i) => delivery(`order-f-${i}`, 'rider-1', { order_id: `f-${i}`, locked_bonus_amount: undefined }));
  const page = normalizeAuditDeliveries(auditDeliveryPage([...real, ...fallback], 0, 125), 'rider-1', 0);
  expect(page.rows).toHaveLength(50); expect(page.hasNext).toBe(true); expect(page.fallback).toHaveLength(50);
  const end = normalizeAuditDeliveries(auditDeliveryPage([delivery('end')], 50, 51), 'rider-1', 50); expect(end.hasNext).toBe(false);
});
it('does not treat 50 fallback-only orders as 50 actual completed deliveries or another page', () => {
  const fallback = Array.from({ length: 50 }, (_, i) => delivery(`order-f-${i}`, 'rider-1', { order_id: `f-${i}` }));
  const page = normalizeAuditDeliveries(auditDeliveryPage(fallback), 'rider-1', 0); expect(page.rows).toHaveLength(0); expect(page.hasNext).toBe(false); expect(page.fallback).toHaveLength(50);
});
it.each([
  { ...auditDeliveryPage(), total: -1 }, { ...auditDeliveryPage(), total: 2 }, { ...auditDeliveryPage(), offset: 50 },
  { ...auditDeliveryPage(), limit: 100 }, { ...auditDeliveryPage(), items: [] }, { ...auditDeliveryPage(), items: [delivery(), delivery()] },
  auditDeliveryPage([delivery(), delivery('order-order-for-delivery-1', 'rider-1', { order_id: 'order-for-delivery-1' })]),
])('rejects invalid delivery envelopes, total/count contradictions and fallback collisions', value => expect(() => normalizeAuditDeliveries(value, 'rider-1', 0)).toThrow());
it('rejects a fallback order on later offsets', () => expect(() => normalizeAuditDeliveries(auditDeliveryPage([delivery('order-f', 'rider-1', { order_id: 'f' })], 50, 51), 'rider-1', 50)).toThrow());
it.each([null, {}, Array.from({ length: 52 }, (_, i) => order(`o-${i}`)), [order(), order()]])('rejects unbounded, duplicate and malformed order pages', value => expect(() => boundedAuditPage(value, 0, row => normalizeAuditOrder(row, 'rider-1'))).toThrow());
it.each([{ orders: -50 }, { orders: 1 }, { orders: NaN }, { transactions: 0.5 }, { deliveries: Number.MAX_SAFE_INTEGER }, { extra: 1 }])('rejects invalid query offsets before HTTP: %j', changes => expect(() => prepareAuditOffsets({ ...initialAuditOffsets, ...changes })).toThrow());

it('accepts Python half-to-even SLA rounding at the exact half-cent boundary', () => {
  expect(normalizeAuditSummary(summary('rider-1', { deliveries_total: 800, sla_compliant: 9, sla_compliance_rate: 1.12 })).sla_compliance_rate).toBe(1.12);
  expect(() => normalizeAuditSummary(summary('rider-1', { deliveries_total: 800, sla_compliant: 9, sla_compliance_rate: 1.11 }))).toThrow();
});
it('accepts the actual unrounded Python availability subtraction without displaying a fabricated balance', () => {
  expect(normalizeAuditSummary(summary('rider-1', { total_earned: 0.3, pending_payouts: 0.1, available_to_payout: 0.19999999999999998 })).total_earned).toBe(0.3);
  expect(() => normalizeAuditSummary(summary('rider-1', { total_earned: 0.3, pending_payouts: 0.1, available_to_payout: 0.201 }))).toThrow();
});
