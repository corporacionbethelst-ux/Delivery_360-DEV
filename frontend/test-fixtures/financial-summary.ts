import type { FinancialPeriod } from '../src/services/financial.service';

/** The wire contract produced by GET /financial/summary, with a fixed server date. */
export const summaryResponse = (period: FinancialPeriod | 'custom' = 'today', changes: Record<string, unknown> = {}) => ({
  period,
  period_start: period === 'custom' ? '2026-10-01T00:00:00' : `2026-11-${period === 'week' ? '02' : period === 'month' ? '01' : '06'}T00:00:00`,
  period_end: period === 'custom' ? '2026-10-24T23:59:59.999999' : '2026-11-06T18:00:00',
  total_revenue: 100, total_costs: 40, net_margin: 60, total_rider_payouts: 30,
  total_transactions: 8, avg_per_delivery: 25, gross_order_value: 200,
  completed_deliveries: 4, other_costs: 10, cash_payouts_processed: 20,
  rider_earnings_accrued: 35, rider_deductions: 5,
  ...changes,
});

export const zeroSummary = {
  total_revenue: 0, total_costs: 0, net_margin: 0, total_rider_payouts: 0,
  total_transactions: 0, avg_per_delivery: 0, gross_order_value: 0,
  completed_deliveries: 0, other_costs: 0, cash_payouts_processed: 0,
  rider_earnings_accrued: 0, rider_deductions: 0,
};
