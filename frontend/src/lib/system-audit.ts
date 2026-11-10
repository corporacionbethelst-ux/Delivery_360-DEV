import type {
  AuditFilters,
  AuditLog,
  AuditLogResponse,
  AuditSummary,
} from "@/services/audit.service";
import { alertDate } from "@/lib/alert-date";

export const AUDIT_PAGE_SIZE = 50;
export const AUDIT_EXPORT_LIMIT = 5000;
export const AUDIT_ACTIONS = [
  "LOGIN",
  "LOGOUT",
  "CREATE",
  "READ",
  "UPDATE",
  "DELETE",
  "ASSIGN",
  "REASSIGN",
  "STATUS_CHANGE",
  "PAYMENT",
  "EXPORT",
  "IMPORT",
  "CONFIG_CHANGE",
  "ACCESS_DENIED",
] as const;
export const AUDIT_RESULTS = {
  SUCCESS: "Correcto",
  WARNING: "Advertencia",
  FAILURE: "Fallo",
};
export const AUDIT_CSV_HEADER =
  "id,created_at,status,action,user_email,user_role,resource_type,resource_id,ip_address,status_code,description";
export type AuditDraft = {
  search: string;
  action: string;
  status: string;
  resource_type: string;
  resource_id: string;
  user_id: string;
  date_from: string;
  date_to: string;
};
export const emptyAuditDraft: AuditDraft = {
  search: "",
  action: "ALL",
  status: "ALL",
  resource_type: "",
  resource_id: "",
  user_id: "",
  date_from: "",
  date_to: "",
};

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("La respuesta de auditoría no es válida.");
  return value as Record<string, unknown>;
}
function integer(
  value: unknown,
  min: number,
  max = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    Number.isSafeInteger(value) &&
    (value as number) >= min &&
    (value as number) <= max
  );
}
function calendarDay(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value + "T00:00:00Z")) &&
    new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value
  );
}
function dateFilter(value: string): string {
  if (calendarDay(value)) return value;
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    ) ||
    !calendarDay(value.slice(0, 10)) ||
    !Number.isFinite(Date.parse(value))
  )
    throw new Error("Fecha de auditoría no válida.");
  return new Date(value).toISOString();
}
function caracasMidnight(day: string): number {
  const midnight = Date.parse(day + "T00:00:00Z");
  let candidate = midnight;
  const formatter = new Intl.DateTimeFormat("en", {
    timeZone: "America/Caracas",
    timeZoneName: "longOffset",
  });
  for (let step = 0; step < 2; step++) {
    const zone = formatter
      .formatToParts(new Date(candidate))
      .find((part) => part.type === "timeZoneName")?.value;
    const match = zone?.match(/^GMT([+-])(\d{2}):(\d{2})$/);
    if (!match)
      throw new Error("No se pudo interpretar el horario de Caracas.");
    const offset =
      (Number(match[2]) * 60 + Number(match[3])) *
      (match[1] === "+" ? 1 : -1) *
      60000;
    candidate = midnight - offset;
  }
  return candidate;
}
export function auditQuery(
  filters: Readonly<AuditFilters> = {},
  exporting = false,
): string {
  const limit = filters.limit ?? (exporting ? 1000 : AUDIT_PAGE_SIZE),
    offset = filters.offset ?? 0;
  if (
    !integer(limit, 1, exporting ? AUDIT_EXPORT_LIMIT : 500) ||
    !integer(offset, 0)
  )
    throw new Error("Paginación de auditoría no válida.");
  const params = new URLSearchParams({ limit: String(limit) });
  if (!exporting) params.set("offset", String(offset));
  for (const field of [
    "action",
    "status",
    "user_id",
    "resource_type",
    "resource_id",
    "search",
  ] as const) {
    const raw = filters[field];
    if (raw === undefined) continue;
    if (typeof raw !== "string")
      throw new Error("Filtro de auditoría no válido.");
    const value = raw.trim();
    if (
      !value ||
      ((field === "action" || field === "status") && value === "ALL")
    )
      continue;
    if (
      field === "action" &&
      !AUDIT_ACTIONS.includes(value as (typeof AUDIT_ACTIONS)[number])
    )
      throw new Error("Acción de auditoría no válida.");
    if (field === "status" && !Object.hasOwn(AUDIT_RESULTS, value))
      throw new Error("Resultado de auditoría no válido.");
    if (
      field === "user_id" &&
      !/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(value)
    )
      throw new Error("Introduce un ID de usuario UUID válido.");
    params.set(field, value);
  }
  const start =
      filters.date_from === undefined
        ? undefined
        : dateFilter(filters.date_from),
    end =
      filters.date_to === undefined ? undefined : dateFilter(filters.date_to);
  if (
    start &&
    end &&
    Date.parse(start) >
      Date.parse(end.length === 10 ? end + "T23:59:59.999Z" : end)
  )
    throw new Error("La fecha inicial no puede ser posterior a la final.");
  if (start) params.set("date_from", start);
  if (end) params.set("date_to", end);
  return "?" + params;
}
export function auditDraftFilters(draft: AuditDraft): AuditFilters {
  const filters: AuditFilters = { limit: AUDIT_PAGE_SIZE, offset: 0 };
  for (const field of [
    "search",
    "action",
    "status",
    "resource_type",
    "resource_id",
    "user_id",
  ] as const) {
    const value = draft[field].trim();
    if (
      value &&
      !((field === "action" || field === "status") && value === "ALL")
    )
      Object.assign(filters, { [field]: value });
  }
  for (const field of ["date_from", "date_to"] as const) {
    const value = draft[field];
    if (!value) continue;
    if (!calendarDay(value)) throw new Error("Selecciona una fecha válida.");
    const nextDay = new Date(Date.parse(value + "T00:00:00Z") + 86400000)
      .toISOString()
      .slice(0, 10);
    filters[field] = new Date(
      field === "date_to"
        ? caracasMidnight(nextDay) - 1
        : caracasMidnight(value),
    ).toISOString();
  }
  if (draft.date_from && draft.date_to && draft.date_from > draft.date_to)
    throw new Error("La fecha inicial no puede ser posterior a la final.");
  auditQuery(filters);
  return filters;
}
export function validateAuditLog(value: unknown): AuditLog {
  const row = record(value);
  if (
    ["id", "action", "status"].some(
      (key) => typeof row[key] !== "string" || !(row[key] as string).trim(),
    ) ||
    typeof row.success !== "boolean"
  )
    throw new Error(
      "El evento de auditoría no tiene identidad y resultado válidos.",
    );
  for (const key of [
    "action_type",
    "user_id",
    "user_email",
    "user_role",
    "resource_type",
    "resource_id",
    "description",
    "details",
    "changes_summary",
    "ip_address",
    "user_agent",
    "request_method",
    "request_path",
    "error_message",
    "created_at",
  ]) {
    if (row[key] != null && typeof row[key] !== "string")
      throw new Error("El evento contiene campos de texto no válidos.");
  }
  if (row.status_code != null && !integer(row.status_code, 0, 999))
    throw new Error("El evento informa un código HTTP no válido.");
  if (
    row.contains_personal_data !== undefined &&
    typeof row.contains_personal_data !== "boolean"
  )
    throw new Error("El evento informa una clasificación no válida.");
  for (const key of ["old_values", "new_values"])
    if (row[key] != null) record(row[key]);
  return { ...row } as unknown as AuditLog;
}
export function validateAuditPage(
  value: unknown,
  filters: Readonly<AuditFilters>,
): AuditLogResponse {
  const page = record(value),
    limit = filters.limit ?? AUDIT_PAGE_SIZE,
    offset = filters.offset ?? 0;
  if (
    !Array.isArray(page.items) ||
    !integer(page.total, 0) ||
    page.limit !== limit ||
    page.offset !== offset ||
    page.items.length > limit ||
    page.items.length > Math.max(0, page.total - offset)
  )
    throw new Error(
      "La página recibida no corresponde a la consulta de auditoría.",
    );
  const items = page.items.map(validateAuditLog);
  if (
    new Set(items.map((row) => row.id)).size !== items.length ||
    items.some(
      (row) =>
        (filters.action?.trim() &&
          filters.action.trim() !== "ALL" &&
          row.action !== filters.action.trim()) ||
        (filters.status?.trim() &&
          filters.status.trim() !== "ALL" &&
          row.status !== filters.status.trim()),
    )
  )
    throw new Error(
      "La página contiene eventos duplicados o ajenos a los filtros confirmados.",
    );
  return { items, total: page.total, limit, offset };
}
export function validateAuditSummary(
  value: unknown,
  days: number,
): AuditSummary {
  const summary = record(value);
  if (
    summary.period_days !== days ||
    !integer(summary.total, 0) ||
    !alertDate(summary.period_start)
  )
    throw new Error("El resumen de auditoría no informa un período válido.");
  for (const field of ["by_action", "by_success"]) {
    const values = Object.values(record(summary[field]));
    if (
      values.some((count) => !integer(count, 0)) ||
      values.reduce<number>((sum, count) => sum + (count as number), 0) !==
        summary.total
    )
      throw new Error(
        "Los totales del resumen de auditoría no son coherentes.",
      );
  }
  return { ...summary } as unknown as AuditSummary;
}
export function validateAuditCsv(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.replace(/^\uFEFF/, "").split(/\r?\n/, 1)[0] !== AUDIT_CSV_HEADER
  )
    throw new Error("El servidor no devolvió el CSV de auditoría esperado.");
  return value;
}
export const auditTime = (value: unknown) =>
  alertDate(value)?.toLocaleString("es-VE", { timeZone: "America/Caracas" }) ??
  "Fecha no disponible";
export const auditEventTime = (row: AuditLog) =>
  auditTime(
    typeof row.new_values?.occurred_at_utc === "string" &&
      alertDate(row.new_values.occurred_at_utc)
      ? row.new_values.occurred_at_utc
      : row.created_at,
  );
export function auditScope(filters: Readonly<AuditFilters>): string {
  return (
    [
      filters.search && `búsqueda «${filters.search}»`,
      filters.action && filters.action !== "ALL" && `acción ${filters.action}`,
      filters.status &&
        filters.status !== "ALL" &&
        `resultado ${AUDIT_RESULTS[filters.status]}`,
      filters.resource_type && `recurso ${filters.resource_type}`,
      filters.resource_id && `ID recurso ${filters.resource_id}`,
      filters.user_id && `ID usuario ${filters.user_id}`,
      filters.date_from && `desde ${auditTime(filters.date_from)}`,
      filters.date_to && `hasta ${auditTime(filters.date_to)}`,
    ]
      .filter(Boolean)
      .join(" · ") || "Todas las acciones y resultados, sin filtros"
  );
}
