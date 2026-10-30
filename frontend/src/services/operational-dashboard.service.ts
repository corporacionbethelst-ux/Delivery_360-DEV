import { api } from "@/lib/api";

export type DashboardMode = "manager" | "operator";
export interface DashboardSummary {
  orders_created: number;
  completed_deliveries: number;
  cancelled_orders: number;
  pending_orders: number;
  in_progress_orders: number;
  active_deliveries: number;
  riders_online: number;
  available_riders: number;
  active_shifts: number;
  open_alerts: number;
  active_users: number;
  avg_delivery_minutes: number | null;
  valid_duration_count: number;
  sla_percent: number | null;
  sla_known_count: number;
  sla_unknown_count: number;
}
export interface DashboardSnapshot {
  summary: DashboardSummary;
  series: Array<{
    date: string;
    orders_created: number;
    completed_deliveries: number;
  }>;
  period_start: string;
  period_end: string;
  timezone: string;
  generated_at: string;
  pending_orders: Array<{
    id: string;
    number: string | null;
    status: string | null;
    address: string;
    priority: string | null;
  }>;
  riders_online: Array<{
    id: string;
    lat: number;
    lng: number;
    recorded_at: string;
  }>;
  queue_truncated: boolean;
  positions_truncated: boolean;
  source: "database_snapshot";
  financials_available: false;
}

const invalid = (): never => {
  throw new Error("Respuesta de métricas inválida");
};
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : invalid();
const text = (value: unknown): string =>
  typeof value === "string" ? value : invalid();
const optionalText = (value: unknown): string | null =>
  value === null ? null : text(value);
const number = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : invalid();
const count = (value: unknown): number =>
  Number.isSafeInteger(value) && number(value) >= 0
    ? (value as number)
    : invalid();
const optionalNumber = (value: unknown): number | null =>
  value === null ? null : number(value) >= 0 ? (value as number) : invalid();
const bool = (value: unknown): boolean =>
  typeof value === "boolean" ? value : invalid();
const timestamp = (value: unknown): string => {
  const result = text(value);
  return /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(result) &&
    Number.isFinite(Date.parse(result))
    ? result
    : invalid();
};
const day = (value: unknown): string => {
  const result = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result)) return invalid();
  const parsed = new Date(`${result}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().startsWith(result)
    ? result
    : invalid();
};
const array = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : invalid();

export function parseDashboardSnapshot(value: unknown): DashboardSnapshot {
  const row = object(value);
  const raw = object(row.summary);
  const summary: DashboardSummary = {
    orders_created: count(raw.orders_created),
    completed_deliveries: count(raw.completed_deliveries),
    cancelled_orders: count(raw.cancelled_orders),
    pending_orders: count(raw.pending_orders),
    in_progress_orders: count(raw.in_progress_orders),
    active_deliveries: count(raw.active_deliveries),
    riders_online: count(raw.riders_online),
    available_riders: count(raw.available_riders),
    active_shifts: count(raw.active_shifts),
    open_alerts: count(raw.open_alerts),
    active_users: count(raw.active_users),
    avg_delivery_minutes: optionalNumber(raw.avg_delivery_minutes),
    valid_duration_count: count(raw.valid_duration_count),
    sla_percent: optionalNumber(raw.sla_percent),
    sla_known_count: count(raw.sla_known_count),
    sla_unknown_count: count(raw.sla_unknown_count),
  };
  if (
    (summary.sla_percent !== null && summary.sla_percent > 100) ||
    summary.sla_known_count + summary.sla_unknown_count !==
      summary.completed_deliveries ||
    summary.valid_duration_count > summary.completed_deliveries
  )
    return invalid();
  const timezone = text(row.timezone);
  try {
    new Intl.DateTimeFormat("es", { timeZone: timezone });
  } catch {
    return invalid();
  }
  const start = timestamp(row.period_start),
    end = timestamp(row.period_end);
  if (
    Date.parse(end) < Date.parse(start) ||
    row.source !== "database_snapshot" ||
    row.financials_available !== false
  )
    return invalid();
  const series = array(row.series).map((value) => {
    const point = object(value);
    return {
      date: day(point.date),
      orders_created: count(point.orders_created),
      completed_deliveries: count(point.completed_deliveries),
    };
  });
  if (
    series.length < 1 ||
    series.length > 31 ||
    new Set(series.map((p) => p.date)).size !== series.length
  )
    return invalid();
  const pending = array(row.pending_orders).map((value) => {
    const item = object(value);
    return {
      id: text(item.id),
      number: optionalText(item.number),
      status: optionalText(item.status),
      address: text(item.address),
      priority: optionalText(item.priority),
    };
  });
  const riders = array(row.riders_online).map((value) => {
    const item = object(value),
      lat = number(item.lat),
      lng = number(item.lng);
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return invalid();
    return {
      id: text(item.id),
      lat,
      lng,
      recorded_at: timestamp(item.recorded_at),
    };
  });
  if (pending.length > 20 || riders.length > 50) return invalid();
  return {
    summary,
    series,
    timezone,
    period_start: start,
    period_end: end,
    generated_at: timestamp(row.generated_at),
    pending_orders: pending,
    riders_online: riders,
    queue_truncated: bool(row.queue_truncated),
    positions_truncated: bool(row.positions_truncated),
    source: "database_snapshot",
    financials_available: false,
  };
}

export async function getOperationalDashboard(
  mode: DashboardMode,
  days: number,
  signal?: AbortSignal,
): Promise<DashboardSnapshot> {
  if (
    !["manager", "operator"].includes(mode) ||
    !Number.isInteger(days) ||
    days < 1 ||
    days > 31
  )
    return invalid();
  return parseDashboardSnapshot(
    await api.get<unknown>(`/dashboard/${mode}?days=${days}`, { signal }),
  );
}
