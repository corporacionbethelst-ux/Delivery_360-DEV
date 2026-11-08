/** Validated, real delivery pages. Missing metadata never becomes an invented fact. */
import { isDeliveryTerminal } from "./delivery-status";

export const DELIVERY_STATES = [
  "PENDIENTE",
  "INICIADA",
  "EN_PICKUP",
  "EN_ROUTE",
  "EN_DESTINO",
  "COMPLETADA",
  "FALLIDA",
  "CANCELADA",
] as const;
export interface DeliveryQuery {
  offset: number;
  limit: number;
  status: string;
  assignment: "ALL" | "assigned" | "unassigned";
  rider: string;
}
export interface DeliveryCatalogRow {
  id: string;
  order: string;
  reference: string | null;
  customer: string | null;
  riderId: string | null;
  riderName: string | null;
  status: string | null;
  started: string | null;
  completed: string | null;
  minutes: number | null;
  sla: boolean | null;
}
export interface DeliverySnapshot {
  query: DeliveryQuery;
  rows: DeliveryCatalogRow[];
  total: number;
}
export const firstDeliveryQuery: DeliveryQuery = {
  offset: 0,
  limit: 20,
  status: "ALL",
  assignment: "ALL",
  rider: "",
};
const invalid = () => new Error("No se pudo comprobar la página de entregas");
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
};
const text = (value: unknown): string | null => {
  if (value == null) return null;
  if (typeof value !== "string" || value.length > 500) throw invalid();
  return value.trim() || null;
};
const id = (value: unknown): string => {
  const result = text(value);
  if (!result) throw invalid();
  return result;
};
const integer = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw invalid();
  return value;
};

export function prepareDeliveryQuery(value: DeliveryQuery): DeliveryQuery {
  const offset = integer(value.offset),
    limit = integer(value.limit),
    rider = value.rider.trim();
  if (
    ![20, 50, 100].includes(limit) ||
    offset % limit ||
    !["ALL", ...DELIVERY_STATES].includes(value.status) ||
    !["ALL", "assigned", "unassigned"].includes(value.assignment)
  )
    throw invalid();
  if (
    rider &&
    (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      rider,
    ) ||
      value.assignment === "unassigned")
  )
    throw invalid();
  return {
    offset,
    limit,
    status: value.status,
    assignment: value.assignment,
    rider,
  };
}
export function normalizeDeliveryPage(
  raw: unknown,
  input: DeliveryQuery,
): DeliverySnapshot {
  const query = prepareDeliveryQuery(input),
    body = record(raw),
    total = integer(body.total);
  if (
    body.limit !== query.limit ||
    body.offset !== query.offset ||
    !Array.isArray(body.items) ||
    body.items.length > query.limit
  )
    throw invalid();
  const rows = body.items.map((raw): DeliveryCatalogRow => {
    const row = record(raw),
      riderId = text(row.rider_id),
      status = text(row.status),
      rider = row.rider == null ? null : record(row.rider);
    if (
      (rider && id(rider.id) !== riderId) ||
      (query.status !== "ALL" && status !== query.status) ||
      (query.assignment === "unassigned" && riderId !== null) ||
      (query.assignment === "assigned" && riderId === null) ||
      (query.rider && riderId !== query.rider)
    )
      throw invalid();
    if (
      (row.total_time != null &&
        (typeof row.total_time !== "number" ||
          !Number.isFinite(row.total_time) ||
          row.total_time < 0)) ||
      (row.sla_compliant != null && typeof row.sla_compliant !== "boolean")
    )
      throw invalid();
    return {
      id: id(row.id),
      order: id(row.order_id),
      reference: text(row.external_id),
      customer: text(row.customer_name),
      riderId,
      riderName: rider
        ? [text(rider.first_name), text(rider.last_name)]
            .filter(Boolean)
            .join(" ") || null
        : null,
      status,
      started: text(row.started_at),
      completed: text(row.completed_at),
      minutes: (row.total_time as number | null) ?? null,
      sla: (row.sla_compliant as boolean | null) ?? null,
    };
  });
  if (
    new Set(rows.map((row) => row.id)).size !== rows.length ||
    (rows.length && query.offset + rows.length > total)
  )
    throw invalid();
  return { query, rows, total };
}
export function searchDeliveries(
  rows: readonly DeliveryCatalogRow[],
  search: string,
) {
  const fold = (value: string) =>
    value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  const term = fold(search.trim());
  return rows.filter(
    (row) =>
      !term ||
      [
        row.id,
        row.order,
        row.reference,
        row.customer,
        row.riderId,
        row.riderName,
        row.status,
      ].some((value) => value && fold(value).includes(term)),
  );
}
export function deliveryDuration(
  row: Pick<DeliveryCatalogRow, "minutes" | "started" | "completed" | "status">,
  now = Date.now(),
): string {
  if (row.minutes !== null) return `${row.minutes} min`;
  const instant = (value: string | null) => {
    if (!value) return NaN;
    const match =
      /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$/.exec(
        value,
      );
    if (!match) return NaN;
    const [year, month, day, hour, minute, second] = match
        .slice(1, 7)
        .map(Number),
      calendar = new Date(Date.UTC(year, month - 1, day));
    if (
      calendar.getUTCFullYear() !== year ||
      calendar.getUTCMonth() !== month - 1 ||
      calendar.getUTCDate() !== day ||
      hour > 23 ||
      minute > 59 ||
      second > 59
    )
      return NaN;
    return Date.parse(match[7] ? value : value + "Z");
  };
  const start = instant(row.started);
  if (!Number.isFinite(start) || !Number.isFinite(now))
    return "Duración no informada";
  const terminal = isDeliveryTerminal(row.status);
  if (
    !row.completed &&
    (terminal ||
      !["INICIADA", "EN_PICKUP", "EN_ROUTE", "EN_DESTINO"].includes(
        row.status ?? "",
      ))
  )
    return "Duración no informada";
  const end = row.completed ? instant(row.completed) : now;
  if (!Number.isFinite(end) || end < start) return "Duración no informada";
  return `${Math.floor((end - start) / 60000)} min${row.completed ? "" : " · en curso"}`;
}
