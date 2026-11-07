import { api } from '@/lib/api';
import { financialService } from '@/services/financial.service';
import { normalizeOrdersReport, normalizeReconciliation, ordersReportCsv, prepareReportQuery } from '@/lib/financial-report-contract';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { emptyOrders, emptyReconciliation, ordersResponse, reconciliationResponse, reportRow } from '../../test-fixtures/financial-reports';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get), range = { date_from: '2026-11-01', date_to: '2026-11-07' };
const query = { ...range, limit: 1000, offset: 0 };
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it('validates the real envelopes and keeps order currency unknown separately from reconciliation COP', () => {
  const orders = normalizeOrdersReport(ordersResponse(range), query), reconciliation = normalizeReconciliation(reconciliationResponse(range), range);
  expect(orders).toMatchObject({ total_orders: 1, currency: null, period_end: '2026-11-07T23:59:59.999999Z' });
  expect(reconciliation).toMatchObject({ currency: 'COP', total_costs: 5, adjustments: -2 });
});
it('retains measured zeros and explicit unbounded limits', () => {
  expect(normalizeOrdersReport(ordersResponse({}, emptyOrders), {})).toMatchObject({ total_orders: 0, total_revenue: 0, period_start: null });
  expect(normalizeReconciliation(reconciliationResponse({}, emptyReconciliation), {})).toMatchObject({ net_margin_after_rider_costs: 0, total_costs: 0 });
});
it.each([null, [], {}, { rows: [] }])('rejects partial or malformed order envelopes (%j)', value => {
  expect(() => normalizeOrdersReport(value, query)).toThrow();
});
it.each([
  { total_orders: 2 }, { total_orders: -1 }, { completed_orders: 2 }, { active_customers: 2 },
  { total_revenue: false }, { total_revenue: '10.001' }, { gross_order_value: '' }, { total_orders: '1' },
  { total_revenue: NaN }, { total_revenue: Infinity }, { total_revenue: '90071992547410' },
  { status_counts: { ENTREGADO: 2 } }, { status_counts: { PENDIENTE: 1 } }, { status_counts: { FUTURE: 1 } },
  { period_start: null }, { period_end: '2026-11-07T00:00:00' }, { period_start: undefined },
  { total_revenue: 11 }, { gross_order_value: 101 }, { degraded: true }, { currency: false },
])('rejects contradictory totals, ignored ranges or invalid metrics (%j)', changes => {
  expect(() => normalizeOrdersReport(ordersResponse(range, changes), query)).toThrow();
});
it.each([
  { id: '' }, { rider_id: false }, { status: 'PAID' }, { total: null }, { subtotal: true }, { total: -1 },
  { customer_name: {} }, { created_at: '2026-02-30T00:00:00' }, { delivered_at: '2026-11-08T00:00:00' },
  { delivered_at: null, created_at: null, ordered_at: null },
])('rejects malformed or out-of-range order rows (%j)', changes => {
  expect(() => normalizeOrdersReport(ordersResponse(range, { rows: [reportRow('order-1', changes)] }), query)).toThrow();
});
it('uses delivered_at then created_at then ordered_at, matching the report server', () => {
  expect(normalizeOrdersReport(ordersResponse(range, { rows: [reportRow('order-1', { delivered_at: null, created_at: null })] }), query).rows[0].ordered_at).toBe('2026-11-06T11:00:00Z');
});
it('does not lose zero amounts or invent optional CSV fields/dates/payment method', () => {
  const orders = normalizeOrdersReport(ordersResponse({}, { ...emptyOrders, total_orders: 1, completed_orders: 1, active_customers: 0, status_counts: { ENTREGADO: 1 }, rows: [reportRow('zero', { total: 0, subtotal: 0, delivery_fee: 0, created_at: null, ordered_at: null, delivered_at: null, customer_name: undefined, payment_method: null, rider_id: null })] }), {});
  expect(ordersReportCsv(orders)[0]).toMatchObject({ id_orden: 'zero', total: 0, subtotal: 0, fecha_base_reporte_utc: '', metodo_pago: '', cliente: '', moneda: '', rider_id: '' });
});
it('rejects repeated identities instead of deduplicating a short or overlapping page', () => {
  expect(() => normalizeOrdersReport(ordersResponse(range, { total_orders: 2, completed_orders: 2, total_revenue: 20, gross_order_value: 200, status_counts: { ENTREGADO: 2 }, rows: [reportRow(), reportRow()] }), query)).toThrow();
});
it('accepts a bounded partial page while retaining aggregate counts for the full query', () => {
  const page = normalizeOrdersReport(ordersResponse(range, { total_orders: 2, completed_orders: 2, total_revenue: 20, gross_order_value: 200, status_counts: { ENTREGADO: 2 } }), { ...query, limit: 1 });
  expect(page.rows).toHaveLength(1); expect(page.total_orders).toBe(2);
});
it.each([
  { net_rider_liability: 12 }, { available_liability: 9 }, { total_costs: 6 }, { net_margin_after_rider_costs: 6 },
  { ledger_transactions: -1 }, { payout_count: false }, { currency: 'usd' }, { processed_payouts: null },
  { adjustments: '' }, { pending_payouts: -1 }, { degraded: true }, { period_end: null },
])('rejects a contradictory reconciliation rather than a fake balanced report (%j)', changes => {
  expect(() => normalizeReconciliation(reconciliationResponse(range, changes), range)).toThrow();
});
it('keeps the server zero floors and a negative reconciliation margin', () => {
  const result = normalizeReconciliation(reconciliationResponse(range, { rider_earnings: 0, rider_deductions: 5, adjustments: -2, net_rider_liability: 0, available_liability: 0, delivery_revenue: 0, net_margin_after_rider_costs: -5 }), range);
  expect(result).toMatchObject({ net_rider_liability: 0, available_liability: 0, net_margin_after_rider_costs: -5 });
});
it.each([
  { date_from: '' }, { date_to: '2026-11-31' }, { date_from: '2026-11-07', date_to: '2026-11-06' },
  { statuses: ['ENTREGADO'] }, { rider_id: 'r' }, { date_from: false }, { offset: Number.MAX_SAFE_INTEGER + 1 },
])('rejects invalid or unsupported report queries before HTTP (%j)', async params => {
  await expect(financialService.getOrdersReport(params as never)).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
it('rejects reconciliation pagination instead of ignoring it', async () => {
  await expect(financialService.getReconciliation({ limit: 20 } as never)).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
it('normalizes offsets in timestamps and bounds server pagination', () => {
  expect(prepareReportQuery({ date_from: '2026-11-01T04:00:00+04:00', date_to: '2026-11-07', limit: 99999, offset: 2.9 })).toMatchObject({ date_from: '2026-11-01T00:00:00.000Z', limit: 5000, offset: 2 });
});
it.each(['orders', 'reconciliation'])('validates the captured query despite caller mutation (%s)', async kind => {
  let resolve!: (value: unknown) => void; get.mockReturnValue(new Promise(done => { resolve = done; }));
  const params = { ...range };
  const pending = kind === 'orders' ? financialService.getOrdersReport(params) : financialService.getReconciliation(params);
  params.date_from = '2026-12-01'; resolve(kind === 'orders' ? ordersResponse(range) : reconciliationResponse(range));
  expect((await pending).period_start).toBe('2026-11-01T00:00:00Z');
});
it.each(['orders-success', 'orders-error', 'reconciliation-success', 'reconciliation-error'])('retires responses/errors after credential changes (%s)', async kind => {
  let resolve!: (value: unknown) => void, reject!: (error: Error) => void;
  get.mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
  const pending = kind.startsWith('orders') ? financialService.getOrdersReport() : financialService.getReconciliation();
  storeTokens({ access_token: 'b', refresh_token: 'rb' });
  if (kind.endsWith('error')) reject(new Error('old')); else resolve(kind.startsWith('orders') ? ordersResponse() : reconciliationResponse());
  await expect(pending).rejects.toBeInstanceOf(SessionChangedError);
});
