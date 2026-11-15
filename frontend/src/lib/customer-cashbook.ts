import { orderQuoteId } from "@/lib/order-currency-quote";
import { collectionKey } from "@/lib/customer-collections";
export type CashCurrency = "USD" | "VES";
export type CashMethod = "EFECTIVO" | "TRANSFERENCIA" | "PAGO_MOVIL";
export interface CashFilters {
  date_from?: string;
  date_to?: string;
  method?: CashMethod;
  currency?: CashCurrency;
  source_key?: string;
}
export interface CashTotals {
  collection_count: number;
  refund_count: number;
  entry_count: number;
  collection_usd: string;
  refund_usd: string;
  net_usd: string;
}
export interface PhysicalTotals extends CashTotals {
  currency: CashCurrency;
  collection_original: string;
  refund_original: string;
  net_original: string;
}
export interface CashRow {
  key: string;
  kind: "COBRO" | "DEVOLUCION";
  verification_id: string;
  collection_id: string;
  refund_id: string | null;
  order_id: string;
  verified_at: string;
  verified_by: string;
  declared_at: string;
  declared_by: string;
  operation_date: string;
  method: CashMethod;
  source_key: string;
  reference_key: string;
  amount_usd: string;
  amount_original: string;
  original_currency: CashCurrency;
  collection_amount_usd: string;
  collection_amount_original: string;
  prior_refunded_usd: string | null;
  prior_refunded_original: string | null;
  bcv_rate: string | null;
  bcv_rate_id: string | null;
  bcv_valid_on: string | null;
}
export interface CashReport {
  version: 1;
  scope: "verified_customer_cashbook";
  base_currency: "USD";
  timezone: "America/Caracas";
  recognition_basis: "manual_verification_time";
  snapshot_basis: "single_statement_visibility";
  bank_verified: false;
  date_from: string;
  date_to: string;
  period_start: string;
  period_end_exclusive: string;
  generated_at: string;
  filters: {
    method: CashMethod | null;
    currency: CashCurrency | null;
    source_key: string | null;
  };
  summary: CashTotals;
  currencies: PhysicalTotals[];
  methods: (PhysicalTotals & { method: CashMethod })[];
  daily: (CashTotals & { date: string })[];
  rows: CashRow[];
  export_complete: true;
  maximum_rows: 5000;
  content_sha256: string;
}
const fail = (): never => {
  throw new Error(
    "El reporte contiene datos incoherentes. Actualiza la consulta antes de exportar.",
  );
};
const obj = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return fail();
  return v as Record<string, unknown>;
};
export function cashCents(value: unknown, signed = false): bigint {
  if (
    typeof value !== "string" ||
    !(
      signed ? /^-?(?:0|[1-9]\d{0,24})\.\d{2}$/ : /^(?:0|[1-9]\d{0,24})\.\d{2}$/
    ).test(value) ||
    value === "-0.00"
  )
    return fail();
  return BigInt(value.replace(".", ""));
}
export function cashText(
  value: string,
  currency: CashCurrency = "USD",
): string {
  cashCents(value, true);
  const [whole, cents] = value.replace("-", "").split(".");
  return `${value.startsWith("-") ? "−" : ""}${currency === "USD" ? "USD " : "Bs. "}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${cents}`;
}
function day(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString().slice(0, 10) !== value
  )
    return fail();
  return value;
}
function time(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{6}Z$/.test(
      value,
    ) ||
    !Number.isFinite(Date.parse(value))
  )
    return fail();
  day(value.slice(0, 10));
  return value;
}
const caracasFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Caracas",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
export function cashDay(value: string): string {
  const parts = caracasFormatter.formatToParts(new Date(value));
  return ["year", "month", "day"]
    .map((key) => parts.find((part) => part.type === key)!.value)
    .join("-");
}
const methods: CashMethod[] = ["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"];
export function cashFilters(input: CashFilters): CashFilters {
  const out: CashFilters = {};
  if (input.date_from) out.date_from = day(input.date_from);
  if (input.date_to) out.date_to = day(input.date_to);
  if (input.method) {
    if (!methods.includes(input.method)) return fail();
    out.method = input.method;
  }
  if (input.currency) {
    if (!["USD", "VES"].includes(input.currency)) return fail();
    out.currency = input.currency;
  }
  if (input.source_key) {
    out.source_key = collectionKey(input.source_key);
    if (out.source_key.length > 80) return fail();
  }
  return out;
}
function checkTotals(raw: unknown, rows: CashRow[], physical = false) {
  const value = obj(raw);
  let credits = BigInt(0),
    debits = BigInt(0),
    paid = BigInt(0),
    returned = BigInt(0),
    count = 0;
  for (const row of rows) {
    if (row.kind === "COBRO") {
      count++;
      credits += cashCents(row.amount_usd);
      paid += cashCents(row.amount_original);
    } else {
      debits += cashCents(row.amount_usd);
      returned += cashCents(row.amount_original);
    }
  }
  if (
    value.collection_count !== count ||
    value.refund_count !== rows.length - count ||
    value.entry_count !== rows.length ||
    cashCents(value.collection_usd) !== credits ||
    cashCents(value.refund_usd) !== debits ||
    cashCents(value.net_usd, true) !== credits - debits
  )
    return fail();
  if (
    physical &&
    (cashCents(value.collection_original) !== paid ||
      cashCents(value.refund_original) !== returned ||
      cashCents(value.net_original, true) !== paid - returned)
  )
    return fail();
}
export function validateCashReport(
  raw: unknown,
  requested: CashFilters = {},
): CashReport {
  const v = obj(raw),
    filters = obj(v.filters),
    input = cashFilters(requested);
  if (
    v.version !== 1 ||
    v.scope !== "verified_customer_cashbook" ||
    v.base_currency !== "USD" ||
    v.timezone !== "America/Caracas" ||
    v.recognition_basis !== "manual_verification_time" ||
    v.snapshot_basis !== "single_statement_visibility" ||
    v.bank_verified !== false ||
    v.export_complete !== true ||
    v.maximum_rows !== 5000 ||
    typeof v.content_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(v.content_sha256)
  )
    return fail();
  const start = day(v.date_from),
    end = day(v.date_to),
    generated = time(v.generated_at),
    lower = time(v.period_start),
    upper = time(v.period_end_exclusive),
    days = (Date.parse(end) - Date.parse(start)) / 86400000 + 1;
  if (
    days < 1 ||
    days > 31 ||
    end > cashDay(generated) ||
    lower !== `${start}T04:00:00.000000Z` ||
    Date.parse(upper) !== Date.parse(`${end}T04:00:00Z`) + 86400000 ||
    (input.date_from && start !== input.date_from) ||
    (input.date_to && end !== input.date_to)
  )
    return fail();
  for (const key of ["method", "currency", "source_key"] as const)
    if (filters[key] !== (input[key] ?? null)) return fail();
  if (!Array.isArray(v.rows) || v.rows.length > 5000) return fail();
  const seen = new Set<string>(),
    rowDays = new Map<string, string>();
  const rows = v.rows.map((raw) => {
    const r = obj(raw);
    for (const key of [
      "verification_id",
      "collection_id",
      "order_id",
      "verified_by",
      "declared_by",
    ])
      orderQuoteId(r[key]);
    const verified = time(r.verified_at),
      declared = time(r.declared_at);
    if (
      !["COBRO", "DEVOLUCION"].includes(r.kind as string) ||
      r.key !== `${r.kind}:${r.verification_id}` ||
      seen.has(r.key as string) ||
      r.verified_by === r.declared_by ||
      declared > verified ||
      verified < lower ||
      verified >= upper ||
      verified > generated ||
      day(r.operation_date) !== cashDay(declared) ||
      !methods.includes(r.method as CashMethod) ||
      !["USD", "VES"].includes(r.original_currency as string) ||
      (r.method === "PAGO_MOVIL" && r.original_currency !== "VES")
    )
      return fail();
    seen.add(r.key as string);
    rowDays.set(r.key as string, cashDay(verified));
    for (const key of ["source_key", "reference_key"] as const)
      if (
        typeof r[key] !== "string" ||
        collectionKey(r[key] as string) !== r[key] ||
        (r[key] as string).length > (key === "source_key" ? 80 : 120)
      )
        return fail();
    if (
      (input.method && r.method !== input.method) ||
      (input.currency && r.original_currency !== input.currency) ||
      (input.source_key && r.source_key !== input.source_key)
    )
      return fail();
    const usd = cashCents(r.amount_usd),
      paid = cashCents(r.amount_original),
      original = cashCents(r.collection_amount_usd),
      originalPaid = cashCents(r.collection_amount_original);
    if ([usd, paid, original, originalPaid].some((n) => n <= BigInt(0)))
      return fail();
    let rate = BigInt(100000000);
    if (r.original_currency === "VES") {
      orderQuoteId(r.bcv_rate_id);
      day(r.bcv_valid_on);
      if (
        typeof r.bcv_rate !== "string" ||
        !/^(?:0|[1-9]\d{0,8})\.\d{8}$/.test(r.bcv_rate) ||
        (rate = BigInt(r.bcv_rate.replace(".", ""))) <= BigInt(0)
      )
        return fail();
    } else if (
      r.bcv_rate !== null ||
      r.bcv_rate_id !== null ||
      r.bcv_valid_on !== null
    )
      return fail();
    const convert = (n: bigint) =>
      (n * rate + BigInt(50000000)) / BigInt(100000000);
    if (convert(original) !== originalPaid) return fail();
    if (r.kind === "COBRO") {
      if (
        r.refund_id !== null ||
        r.prior_refunded_usd !== null ||
        r.prior_refunded_original !== null ||
        usd !== original ||
        paid !== originalPaid
      )
        return fail();
    } else {
      orderQuoteId(r.refund_id);
      const prior = cashCents(r.prior_refunded_usd),
        priorPaid = cashCents(r.prior_refunded_original);
      if (
        prior + usd > original ||
        convert(prior) !== priorPaid ||
        convert(prior + usd) - priorPaid !== paid
      )
        return fail();
    }
    return r as unknown as CashRow;
  });
  checkTotals(v.summary, rows);
  if (
    !Array.isArray(v.currencies) ||
    v.currencies.length !== 2 ||
    !Array.isArray(v.methods) ||
    v.methods.length !== 5 ||
    !Array.isArray(v.daily) ||
    v.daily.length !== days
  )
    return fail();
  for (const [i, c] of ["USD", "VES"].entries()) {
    if (obj(v.currencies[i]).currency !== c) return fail();
    checkTotals(
      v.currencies[i],
      rows.filter((r) => r.original_currency === c),
      true,
    );
  }
  let index = 0;
  for (const c of ["USD", "VES"])
    for (const m of methods) {
      if (c === "USD" && m === "PAGO_MOVIL") continue;
      const total = obj(v.methods[index++]);
      if (total.currency !== c || total.method !== m) return fail();
      checkTotals(
        total,
        rows.filter((r) => r.original_currency === c && r.method === m),
        true,
      );
    }
  for (let i = 0; i < days; i++) {
    const expected = new Date(Date.parse(start) + i * 86400000)
        .toISOString()
        .slice(0, 10),
      daily = obj(v.daily[i]);
    if (daily.date !== expected) return fail();
    checkTotals(
      daily,
      rows.filter((r) => rowDays.get(r.key) === expected),
    );
  }
  return { ...v, rows } as unknown as CashReport;
}
export function cashbookCSV(value: CashReport): Record<string, unknown>[] {
  const metadata = {
    desde_caracas: value.date_from,
    hasta_caracas: value.date_to,
    generado_utc: value.generated_at,
    huella_sha256: value.content_sha256,
    filas_completas: value.rows.length,
    verificacion: "MANUAL",
    neto_usd: value.summary.net_usd,
  };
  return value.rows.length
    ? value.rows.map((row) => ({ ...metadata, ...row }))
    : [{ ...metadata, nota: "Sin movimientos verificados en el rango" }];
}

export function cashbookError(error: unknown): string {
  if (error && typeof error === "object") {
    const response = (
      error as { response?: { status?: number; data?: { detail?: unknown } } }
    ).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string" && detail.trim() && detail.length <= 1000)
      return detail;
    if (response?.status === 422)
      return "Revisa los filtros: usa fechas válidas de Caracas, hasta hoy y con un máximo de 31 días.";
    if (response?.status === 429)
      return "Se alcanzó el límite de consultas. Espera un minuto y vuelve a aplicar el rango.";
    if (response?.status && response.status >= 500)
      return "El reporte no está disponible temporalmente. Vuelve a aplicar la consulta.";
  }
  return error instanceof Error
    ? error.message
    : "No se pudo cargar el libro. Vuelve a aplicar la consulta.";
}
