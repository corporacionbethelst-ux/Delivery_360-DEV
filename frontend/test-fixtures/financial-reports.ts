import type { ReportRange } from '../src/lib/financial-report-contract';

export const reportRow = (id = 'order-1', changes: Record<string, unknown> = {}) => ({
  id, external_id: 'EXT-1', status: 'ENTREGADO', priority: 'NORMAL',
  created_at: '2026-11-06T12:00:00', ordered_at: '2026-11-06T11:00:00', delivered_at: '2026-11-06T13:00:00',
  customer_name: 'José, Pérez', customer_phone: '+584121234567', customer_email: 'jose@example.test',
  pickup_address: 'Origen', delivery_address: 'Destino', subtotal: 90, delivery_fee: 10, total: 100,
  payment_method: null, payment_status: 'PAGADO', rider_id: 'rider-1', ...changes,
});
const bounds = (range: ReportRange = {}) => ({
  period_start: range.date_from ? `${range.date_from}T00:00:00` : null,
  period_end: range.date_to ? `${range.date_to}T23:59:59.999999` : null,
});
export const ordersResponse = (range: ReportRange = {}, changes: Record<string, unknown> = {}) => ({
  ...bounds(range), total_orders: 1, completed_orders: 1, active_customers: 1,
  total_revenue: 10, gross_order_value: 100, status_counts: { ENTREGADO: 1 }, rows: [reportRow()], ...changes,
});
export const reconciliationResponse = (range: ReportRange = {}, changes: Record<string, unknown> = {}) => ({
  ...bounds(range), gross_order_value: 100, delivery_revenue: 10, completed_orders: 1,
  ledger_transactions: 3, payout_count: 2, rider_earnings: 20, rider_deductions: 5, adjustments: -2,
  net_rider_liability: 13, pending_payouts: 2, processed_payouts: 3, rejected_payouts: 0,
  available_liability: 8, total_costs: 5, net_margin_after_rider_costs: 5, currency: 'COP', ...changes,
});
export const emptyOrders = { total_orders: 0, completed_orders: 0, active_customers: 0, total_revenue: 0, gross_order_value: 0, status_counts: {}, rows: [] };
export const emptyReconciliation = { gross_order_value: 0, delivery_revenue: 0, completed_orders: 0, ledger_transactions: 0, payout_count: 0, rider_earnings: 0, rider_deductions: 0, adjustments: 0, net_rider_liability: 0, pending_payouts: 0, processed_payouts: 0, rejected_payouts: 0, available_liability: 0, total_costs: 0, net_margin_after_rider_costs: 0 };
