import { validateExactAggregate } from '@/lib/order-pricing';
import { summaryDate } from '@/lib/financial-summary-contract';
import type { FinancialOrdersReport, FinancialOrderReportRow, FinancialReconciliation, FinancialReportParams } from '@/services/financial.service';

export const REPORT_PREVIEW_LIMIT = 1000;
export const REPORT_EXPORT_LIMIT = 5000;
export type ReportRange = Pick<FinancialReportParams, 'date_from' | 'date_to'>;
const states = new Set(['PENDIENTE', 'ASIGNADO', 'EN_RECOLECCION', 'RECOLECTADO', 'EN_RUTA', 'ENTREGADO', 'FALLIDO', 'CANCELADO']);
const invalid = (): never => { throw new Error('El reporte financiero está incompleto o no corresponde a la consulta'); };
const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const text = (value: unknown): string | null => value == null ? null : typeof value === 'string' ? value : invalid();
const id = (value: unknown): string => typeof value === 'string' && value.trim() !== '' && value.trim() === value ? value : invalid();
const count = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid();
const cents = (value: number): number => Math.round(value * 100);
const money = (value: unknown, signed = false): number => {
  if ((typeof value !== 'number' && typeof value !== 'string') || !new RegExp(signed ? '^-?\\d+(?:\\.\\d{1,2})?$' : '^\\d+(?:\\.\\d{1,2})?$').test(String(value))) return invalid();
  const amount = Math.round(Number(value) * 100);
  return Number.isSafeInteger(amount) ? amount / 100 : invalid();
};
const date = (value: unknown): { iso: string; time: number } => { try { return summaryDate(value); } catch { return invalid(); } };
const optionalDate = (value: unknown) => value == null ? null : date(value).iso;
const currency = (value: unknown): string | null => value == null ? null : typeof value === 'string' && /^[A-Z]{3}$/.test(value) ? value : invalid();
const endTime = (value: string) => date(value).time + (value.length === 10 ? 86399999 : 0);

export function prepareReportQuery(params?: Readonly<FinancialReportParams>, paginated = true): FinancialReportParams {
  const query = { ...params };
  const allowed = paginated ? ['date_from', 'date_to', 'limit', 'offset'] : ['date_from', 'date_to'];
  if (Object.keys(query).some(key => !allowed.includes(key))) return invalid();
  for (const name of ['date_from', 'date_to'] as const) {
    if (query[name] !== undefined) {
      const parsed = date(query[name]);
      if (query[name]!.length !== 10) query[name] = new Date(parsed.time).toISOString();
    }
  }
  if (query.date_from && query.date_to && date(query.date_from).time > endTime(query.date_to)) return invalid();
  if (paginated) {
    query.limit = Number.isFinite(query.limit) ? Math.min(Math.max(Math.trunc(query.limit!), 1), REPORT_EXPORT_LIMIT) : REPORT_PREVIEW_LIMIT;
    query.offset = Number.isFinite(query.offset) && query.offset! >= 0 ? Math.trunc(query.offset!) : 0;
    if (!Number.isSafeInteger(query.offset)) return invalid();
  }
  return query;
}

function range(value: Record<string, unknown>, query: Readonly<ReportRange>) {
  // Both endpoints explicitly publish null for an unbounded side of the query.
  const start = value.period_start === null ? null : date(value.period_start);
  const end = value.period_end === null ? null : date(value.period_end);
  if (query.date_from ? !start || start.time !== date(query.date_from).time : start !== null) return invalid();
  if (query.date_to ? !end || end.time !== endTime(query.date_to) : end !== null) return invalid();
  if (start && end && start.time > end.time) return invalid();
  return { period_start: start?.iso ?? null, period_end: end?.iso ?? null };
}

export function normalizeOrdersReport(value: unknown, query: Readonly<FinancialReportParams>): FinancialOrdersReport {
  const data = object(value), bounds = range(data, query);
  if (data.degraded === true || !Array.isArray(data.rows)) return invalid();
  const total = count(data.total_orders), completed = count(data.completed_orders), customers = count(data.active_customers);
  const limit = query.limit ?? REPORT_PREVIEW_LIMIT, offset = query.offset ?? 0;
  if (data.rows.length !== Math.min(limit, Math.max(0, total - offset)) || completed > total || customers > total) return invalid();
  const statusCounts: Record<string, number> = Object.create(null);
  for (const [status, amount] of Object.entries(object(data.status_counts))) {
    if (!states.has(status)) return invalid();
    statusCounts[status] = count(amount);
  }
  if (Object.values(statusCounts).reduce((sum, n) => sum + n, 0) !== total || (statusCounts.ENTREGADO ?? 0) !== completed) return invalid();
  const ids = new Set<string>(), loadedCounts: Record<string, number> = Object.create(null);
  const rows: FinancialOrderReportRow[] = data.rows.map(value => {
    const row = object(value), rowId = id(row.id), status = id(row.status);
    if (ids.has(rowId) || !states.has(status)) return invalid();
    ids.add(rowId); loadedCounts[status] = (loadedCounts[status] ?? 0) + 1;
    const result: FinancialOrderReportRow = {
      id: rowId, status, external_id: text(row.external_id), priority: text(row.priority),
      created_at: optionalDate(row.created_at), ordered_at: optionalDate(row.ordered_at), delivered_at: optionalDate(row.delivered_at),
      customer_name: text(row.customer_name), customer_phone: text(row.customer_phone), customer_email: text(row.customer_email),
      pickup_address: text(row.pickup_address), delivery_address: text(row.delivery_address),
      subtotal: money(row.subtotal), delivery_fee: money(row.delivery_fee), total: money(row.total),
      payment_method: text(row.payment_method), payment_status: text(row.payment_status),
      rider_id: row.rider_id == null ? null : id(row.rider_id),
    };
    const basis = result.delivered_at ?? result.created_at ?? result.ordered_at;
    if ((query.date_from || query.date_to) && (!basis || query.date_from && date(basis).time < date(query.date_from).time || query.date_to && date(basis).time > endTime(query.date_to))) return invalid();
    return result;
  });
  const revenue = money(data.total_revenue), gross = money(data.gross_order_value);
  const sum = (field: 'delivery_fee' | 'total') => rows.reduce((acc, row) => acc + cents(row[field]), 0);
  if (!Number.isSafeInteger(sum('delivery_fee')) || !Number.isSafeInteger(sum('total')) ||
      sum('delivery_fee') > cents(revenue) || sum('total') > cents(gross) ||
      Object.entries(loadedCounts).some(([status, n]) => n > (statusCounts[status] ?? 0))) return invalid();
  if (offset === 0 && rows.length === total && (sum('delivery_fee') !== cents(revenue) || sum('total') !== cents(gross) ||
      Object.keys(statusCounts).some(status => (loadedCounts[status] ?? 0) !== statusCounts[status]))) return invalid();
  return { ...(data.exact_order_pricing === undefined ? {} : {exact_order_pricing: validateExactAggregate(data.exact_order_pricing)}), ...bounds, currency: currency(data.currency), total_orders: total, completed_orders: completed, active_customers: customers,
    total_revenue: revenue, gross_order_value: gross, status_counts: statusCounts, rows };
}

export function normalizeReconciliation(value: unknown, query: Readonly<ReportRange>): FinancialReconciliation {
  const data = object(value), bounds = range(data, query);
  if (data.degraded === true) return invalid();
  const result: FinancialReconciliation = {
    ...(data.exact_order_pricing === undefined ? {} : {exact_order_pricing: validateExactAggregate(data.exact_order_pricing)}),
    ...bounds, currency: currency(data.currency),
    gross_order_value: money(data.gross_order_value), delivery_revenue: money(data.delivery_revenue),
    completed_orders: count(data.completed_orders), ledger_transactions: count(data.ledger_transactions), payout_count: count(data.payout_count),
    rider_earnings: money(data.rider_earnings), rider_deductions: money(data.rider_deductions), adjustments: money(data.adjustments, true),
    net_rider_liability: money(data.net_rider_liability), pending_payouts: money(data.pending_payouts), processed_payouts: money(data.processed_payouts),
    rejected_payouts: money(data.rejected_payouts), available_liability: money(data.available_liability),
    total_costs: money(data.total_costs), net_margin_after_rider_costs: money(data.net_margin_after_rider_costs, true),
  };
  const liability = cents(result.rider_earnings) - cents(result.rider_deductions) + cents(result.adjustments);
  const costs = cents(result.pending_payouts) + cents(result.processed_payouts);
  if (!Number.isSafeInteger(liability) || !Number.isSafeInteger(costs) ||
      cents(result.net_rider_liability) !== Math.max(0, liability) || cents(result.total_costs) !== costs ||
      cents(result.available_liability) !== Math.max(0, cents(result.net_rider_liability) - costs) ||
      cents(result.net_margin_after_rider_costs) !== cents(result.delivery_revenue) - costs) return invalid();
  return result;
}

export function ordersReportCsv(report: FinancialOrdersReport) {
  return report.rows.map(row => ({
    id_orden: row.id, referencia_externa: row.external_id ?? '',
    fecha_creacion_utc: row.created_at ?? '', fecha_pedido_utc: row.ordered_at ?? '', fecha_entrega_utc: row.delivered_at ?? '',
    fecha_base_reporte_utc: row.delivered_at ?? row.created_at ?? row.ordered_at ?? '',
    cliente: row.customer_name ?? '', telefono: row.customer_phone ?? '', email: row.customer_email ?? '',
    direccion_recogida: row.pickup_address ?? '', direccion_entrega: row.delivery_address ?? '', estado: row.status,
    prioridad: row.priority ?? '', subtotal: row.subtotal, tarifa_entrega: row.delivery_fee, total: row.total,
    metodo_pago: row.payment_method ?? '', estado_pago: row.payment_status ?? '', rider_id: row.rider_id ?? '',
    moneda: report.currency ?? '', rango_desde_utc: report.period_start ?? '', rango_hasta_utc: report.period_end ?? '',
  }));
}
