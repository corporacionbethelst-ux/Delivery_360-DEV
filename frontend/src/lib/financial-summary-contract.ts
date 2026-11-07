import type { FinancialPeriod, FinancialSummary, FinancialSummaryParams } from '@/services/financial.service';

export const FINANCIAL_PERIODS = ['today', 'week', 'month'] as const;
export const periodLabel = (period: FinancialPeriod) => ({ today: 'Hoy', week: 'Semana', month: 'Mes' })[period];
const invalid = (): never => { throw new Error('El resumen financiero está incompleto o no corresponde a la consulta'); };
const money = (value: unknown, signed = false): number => {
  if ((typeof value !== 'number' && typeof value !== 'string') ||
      !new RegExp(signed ? '^-?\\d+(?:\\.\\d{1,2})?$' : '^\\d+(?:\\.\\d{1,2})?$').test(String(value))) return invalid();
  const cents = Math.round(Number(value) * 100);
  return Number.isSafeInteger(cents) ? cents / 100 : invalid();
};
const count = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid();
const optionalMoney = (value: unknown) => value == null ? null : money(value);
const optionalCount = (value: unknown) => value == null ? null : count(value);
const cents = (value: number) => Math.round(value * 100);

/** Backend timestamps without an offset describe UTC, not the browser's zone. */
export function summaryDate(value: unknown): { iso: string; time: number } {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) return invalid();
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value.slice(0, 10)) return invalid();
  const iso = value.length === 10 ? `${value}T00:00:00Z` : /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const time = Date.parse(iso);
  return Number.isFinite(time) ? { iso, time } : invalid();
}

export function prepareSummaryQuery(params?: Readonly<FinancialSummaryParams>): FinancialSummaryParams {
  const query = { ...params };
  if (query.period !== undefined && !FINANCIAL_PERIODS.includes(query.period)) return invalid();
  for (const name of ['start_date', 'end_date'] as const) {
    if (query[name] !== undefined) {
      const parsed = summaryDate(query[name]);
      // Normalize offsets before the legacy backend strips timezone information.
      if (query[name]!.length !== 10) query[name] = new Date(parsed.time).toISOString();
    }
  }
  if (query.start_date && query.end_date) {
    const end = summaryDate(query.end_date).time + (query.end_date.length === 10 ? 86399999 : 0);
    if (summaryDate(query.start_date).time > end) return invalid();
  }
  return query;
}

export function normalizeFinancialSummary(value: unknown, query: Readonly<FinancialSummaryParams>): FinancialSummary {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  const data = value as Record<string, unknown>;
  const period = query.start_date ? 'custom' : query.period ?? 'today';
  if (data.period !== period || data.degraded === true) return invalid();
  const start = data.period_start == null ? null : summaryDate(data.period_start);
  const end = data.period_end == null ? null : summaryDate(data.period_end);
  if (start && end && start.time > end.time) return invalid();
  if (query.start_date && (!start || start.time !== summaryDate(query.start_date).time)) return invalid();
  if (query.end_date) {
    const expected = summaryDate(query.end_date).time + (query.end_date.length === 10 ? 86399999 : 0);
    if (!end || end.time !== expected) return invalid();
  }
  if (!query.start_date && !query.end_date && start && end) {
    const expected = new Date(end.time);
    expected.setUTCHours(0, 0, 0, 0);
    if (period === 'week') expected.setUTCDate(expected.getUTCDate() - (expected.getUTCDay() + 6) % 7);
    if (period === 'month') expected.setUTCDate(1);
    if (start.time !== expected.getTime()) return invalid();
  }
  let currency: string | null = null;
  if (data.currency != null) {
    if (typeof data.currency !== 'string' || !/^[A-Z]{3}$/.test(data.currency)) return invalid();
    currency = data.currency;
  }
  const result: FinancialSummary = {
    period, period_start: start?.iso ?? null, period_end: end?.iso ?? null, currency,
    total_revenue: money(data.total_revenue), total_costs: money(data.total_costs),
    net_margin: money(data.net_margin, true), total_rider_payouts: money(data.total_rider_payouts),
    total_transactions: count(data.total_transactions), avg_per_delivery: money(data.avg_per_delivery),
    gross_order_value: optionalMoney(data.gross_order_value), completed_deliveries: optionalCount(data.completed_deliveries),
    other_costs: optionalMoney(data.other_costs), cash_payouts_processed: optionalMoney(data.cash_payouts_processed),
    rider_earnings_accrued: optionalMoney(data.rider_earnings_accrued), rider_deductions: optionalMoney(data.rider_deductions),
  };
  if (cents(result.net_margin) !== cents(result.total_revenue) - cents(result.total_costs) ||
      cents(result.total_rider_payouts) > cents(result.total_costs) ||
      result.other_costs != null && cents(result.other_costs) !== cents(result.total_costs) - cents(result.total_rider_payouts)) return invalid();
  if (result.rider_earnings_accrued != null && result.rider_deductions != null && result.cash_payouts_processed != null &&
      cents(result.total_rider_payouts) !== Math.max(0, cents(result.rider_earnings_accrued) - cents(result.rider_deductions), cents(result.cash_payouts_processed))) return invalid();
  return result;
}
