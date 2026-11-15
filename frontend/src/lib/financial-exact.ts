import { cashCents, cashDay, cashText } from "@/lib/customer-cashbook";
import { orderQuoteId } from "@/lib/order-currency-quote";
export { cashText as financialMoney };
export const sourceKinds = ["ORDEN", "MOVIMIENTO", "RETIRO"] as const;
export const orderStates = [
  "PENDIENTE",
  "ASIGNADO",
  "EN_RECOLECCION",
  "RECOLECTADO",
  "EN_RUTA",
  "ENTREGADO",
  "FALLIDO",
  "CANCELADO",
] as const;
export const payoutStates = [
  "PENDIENTE",
  "APROBADO",
  "EN_PROCESO",
  "COMPLETADO",
  "RECHAZADO",
  "FALLIDO",
] as const;
export const creditTypes = [
  "BONO",
  "BONO_RENDIMIENTO",
  "INGRESO",
  "PAGO_ENTREGA",
  "PAGO_INTENTO_FALLIDO",
] as const;
export const debitTypes = [
  "AJUSTE_MANUAL",
  "DESCUENTO",
  "PENALIZACION",
  "RETIRO",
] as const;
export const ledgerTypes = [...creditTypes, ...debitTypes, "AJUSTE"] as const;
export const exclusionReasons = [
  "FECHA_NO_REGISTRADA",
  "MONEDA_NO_VERIFICADA",
  "PRECIO_NO_EXACTO",
  "ESTADO_NO_PROCESADO",
  "TIPO_NO_ADMITIDO",
  "ESTADO_NO_ADMITIDO",
] as const;
export type SourceKind = (typeof sourceKinds)[number];
export type Exclusion = (typeof exclusionReasons)[number];
export const exclusionLabels: Record<Exclusion, string> = {
  FECHA_NO_REGISTRADA: "Sin fecha registrada",
  MONEDA_NO_VERIFICADA: "Moneda sin verificar",
  PRECIO_NO_EXACTO: "Precio anterior sin paquete exacto",
  ESTADO_NO_PROCESADO: "Movimiento sin procesar",
  TIPO_NO_ADMITIDO: "Tipo ajeno al libro contable",
  ESTADO_NO_ADMITIDO: "Estado sin identificar",
};
export interface ExactRange {
  date_from?: string;
  date_to?: string;
}
export interface ExactRow {
  key: string;
  kind: SourceKind;
  id: string;
  occurred_at: string | null;
  currency: string | null;
  status: string | null;
  transaction_type: string | null;
  pricing_version: number | null;
  pricing_revision: number | null;
  included: boolean;
  exclusion_reason: Exclusion | null;
  subtotal_usd: string | null;
  delivery_fee_usd: string | null;
  total_usd: string | null;
  amount_usd: string | null;
  delta_usd: string | null;
}
export interface OrderTotal {
  count: number;
  subtotal_usd: string;
  delivery_fee_usd: string;
  total_usd: string;
}
export interface LedgerTotal {
  count: number;
  credit_usd: string;
  debit_usd: string;
  adjustment_usd: string;
  net_change_usd: string;
}
export interface PayoutTotal {
  count: number;
  amount_usd: string;
}
export interface ExactReport {
  version: 2;
  scope: "exact_management_sources";
  currency: "USD";
  timezone: "America/Caracas";
  date_from: string;
  date_to: string;
  period_start: string;
  period_end_exclusive: string;
  generated_at: string;
  snapshot_basis: "single_statement_visibility";
  recognition_basis: "source_creation_time";
  payout_basis: "requests_created_in_period_current_status";
  undated_policy: "included_as_excluded";
  bank_verified: false;
  customer_cashbook_included: false;
  wallet_cents_included: false;
  maximum_rows: 5000;
  export_complete: true;
  row_count: number;
  excluded_count: number;
  sources: Record<
    SourceKind,
    { row_count: number; included_count: number; excluded_count: number }
  >;
  orders: OrderTotal & { by_status: (OrderTotal & { status: string })[] };
  ledger: LedgerTotal & {
    by_type: {
      transaction_type: string;
      count: number;
      amount_usd: string;
      delta_usd: string;
    }[];
  };
  payouts: PayoutTotal & { by_status: (PayoutTotal & { status: string })[] };
  exclusions: { reason: Exclusion; count: number }[];
  daily: {
    date: string;
    orders: OrderTotal;
    ledger: LedgerTotal;
    payouts: PayoutTotal;
  }[];
  rows: ExactRow[];
  content_sha256: string;
}
const fail = (): never => {
  throw new Error(
    "El reporte exacto está incompleto o contiene cifras incoherentes. Actualiza antes de exportar.",
  );
};
const obj = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return fail();
  return v as Record<string, unknown>;
};
const includes = (a: readonly string[], v: unknown) =>
  typeof v === "string" && a.includes(v);
export function exactDate(v: unknown): string {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(v) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v
  )
    return fail();
  return v;
}
function time(v: unknown): string {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{6}Z$/.test(v) ||
    !Number.isFinite(Date.parse(v))
  )
    return fail();
  exactDate(v.slice(0, 10));
  return v;
}
const midnight = new Intl.DateTimeFormat("en-GB", {
  timeZone: "America/Caracas",
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
function localMidnight(v: string, day: string) {
  return (
    cashDay(v) === day &&
    midnight.format(new Date(v)) === "00:00:00" &&
    v.endsWith(".000000Z")
  );
}
export function exactRange(input: ExactRange = {}): ExactRange {
  if (Object.keys(input).some((k) => !["date_from", "date_to"].includes(k)))
    return fail();
  const result: ExactRange = {};
  for (const k of ["date_from", "date_to"] as const)
    if (input[k]) result[k] = exactDate(input[k]);
  if (
    result.date_from &&
    result.date_to &&
    (result.date_from > result.date_to ||
      (Date.parse(result.date_to) - Date.parse(result.date_from)) / 86400000 >=
        31)
  )
    return fail();
  return result;
}
export function exclusionFor(
  row: Pick<
    ExactRow,
    | "occurred_at"
    | "currency"
    | "kind"
    | "pricing_version"
    | "status"
    | "transaction_type"
  >,
): Exclusion | null {
  if (row.occurred_at === null) return "FECHA_NO_REGISTRADA";
  if (row.currency !== "USD") return "MONEDA_NO_VERIFICADA";
  if (row.kind === "ORDEN") {
    if (row.pricing_version !== 1) return "PRECIO_NO_EXACTO";
    if (!includes(orderStates, row.status)) return "ESTADO_NO_ADMITIDO";
  } else if (row.kind === "MOVIMIENTO") {
    if (!includes(["PROCESADO", "PAGADO"], row.status))
      return "ESTADO_NO_PROCESADO";
    if (!includes(ledgerTypes, row.transaction_type)) return "TIPO_NO_ADMITIDO";
  } else if (!includes(payoutStates, row.status)) return "ESTADO_NO_ADMITIDO";
  return null;
}
const centsText = (n: bigint): string =>
  `${n < BigInt(0) ? "-" : ""}${(n < BigInt(0) ? -n : n) / BigInt(100)}.${((n < BigInt(0) ? -n : n) % BigInt(100)).toString().padStart(2, "0")}`;
function orderTotal(rows: ExactRow[]): OrderTotal {
  const sum = (k: "subtotal_usd" | "delivery_fee_usd" | "total_usd") =>
    centsText(rows.reduce((n, r) => n + cashCents(r[k]), BigInt(0)));
  return {
    count: rows.length,
    subtotal_usd: sum("subtotal_usd"),
    delivery_fee_usd: sum("delivery_fee_usd"),
    total_usd: sum("total_usd"),
  };
}
function ledgerTotal(rows: ExactRow[]): LedgerTotal {
  let c = BigInt(0),
    d = BigInt(0),
    a = BigInt(0);
  for (const r of rows) {
    const delta = cashCents(r.delta_usd, true);
    if (includes(creditTypes, r.transaction_type)) c += delta;
    else if (includes(debitTypes, r.transaction_type)) d -= delta;
    else a += delta;
  }
  return {
    count: rows.length,
    credit_usd: centsText(c),
    debit_usd: centsText(d),
    adjustment_usd: centsText(a),
    net_change_usd: centsText(c - d + a),
  };
}
function payoutTotal(rows: ExactRow[]): PayoutTotal {
  return {
    count: rows.length,
    amount_usd: centsText(
      rows.reduce((n, r) => n + cashCents(r.amount_usd), BigInt(0)),
    ),
  };
}
function same(actual: unknown, expected: unknown): void {
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length)
      return fail();
    expected.forEach((v, i) => same(actual[i], v));
  } else if (expected && typeof expected === "object") {
    const a = obj(actual);
    for (const [k, v] of Object.entries(expected)) same(a[k], v);
  } else if (actual !== expected) return fail();
}
export function validateExactReport(
  value: unknown,
  input: ExactRange = {},
): ExactReport {
  const v = obj(value),
    range = exactRange(input);
  same(v, {
    version: 2,
    scope: "exact_management_sources",
    currency: "USD",
    timezone: "America/Caracas",
    snapshot_basis: "single_statement_visibility",
    recognition_basis: "source_creation_time",
    payout_basis: "requests_created_in_period_current_status",
    undated_policy: "included_as_excluded",
    bank_verified: false,
    customer_cashbook_included: false,
    wallet_cents_included: false,
    maximum_rows: 5000,
    export_complete: true,
  });
  const first = exactDate(v.date_from),
    last = exactDate(v.date_to),
    start = time(v.period_start),
    end = time(v.period_end_exclusive),
    generated = time(v.generated_at),
    days = (Date.parse(last) - Date.parse(first)) / 86400000 + 1,
    next = new Date(Date.parse(last) + 86400000).toISOString().slice(0, 10);
  if (
    days < 1 ||
    days > 31 ||
    last > cashDay(generated) ||
    !localMidnight(start, first) ||
    !localMidnight(end, next) ||
    (range.date_from && range.date_from !== first) ||
    (range.date_to && range.date_to !== last)
  )
    return fail();
  if (
    typeof v.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.content_sha256) ||
    !Array.isArray(v.rows) ||
    v.rows.length > 5000
  )
    return fail();
  const seen = new Set<string>(),
    rowDays = new Map<string, string>();
  const rows = v.rows.map((raw) => {
    const r = obj(raw);
    orderQuoteId(r.id);
    if (
      !includes(sourceKinds, r.kind) ||
      r.key !== `${r.kind}:${r.id}` ||
      seen.has(r.key as string) ||
      typeof r.included !== "boolean"
    )
      return fail();
    seen.add(r.key as string);
    if (
      r.currency !== null &&
      (typeof r.currency !== "string" || !/^[A-Z]{3}$/.test(r.currency))
    )
      return fail();
    for (const k of ["status", "transaction_type"] as const)
      if (
        r[k] !== null &&
        (typeof r[k] !== "string" ||
          !(r[k] as string).length ||
          (r[k] as string).length > 60)
      )
        return fail();
    if (r.occurred_at !== null) {
      const t = time(r.occurred_at);
      if (t < start || t >= end || t > generated) return fail();
      rowDays.set(r.key as string, cashDay(t));
    }
    if (r.kind === "ORDEN") {
      if (
        r.transaction_type !== null ||
        r.amount_usd !== null ||
        r.delta_usd !== null
      )
        return fail();
      for (const k of ["pricing_version", "pricing_revision"] as const)
        if (
          r[k] !== null &&
          (!Number.isSafeInteger(r[k]) || (r[k] as number) < 0)
        )
          return fail();
    } else if (
      r.pricing_version !== null ||
      r.pricing_revision !== null ||
      r.subtotal_usd !== null ||
      r.delivery_fee_usd !== null ||
      r.total_usd !== null ||
      (r.kind === "RETIRO" &&
        (r.transaction_type !== null || r.delta_usd !== null))
    )
      return fail();
    const row = r as unknown as ExactRow,
      reason = exclusionFor(row);
    if (r.exclusion_reason !== reason || r.included !== (reason === null))
      return fail();
    if (reason) {
      if (
        [
          "subtotal_usd",
          "delivery_fee_usd",
          "total_usd",
          "amount_usd",
          "delta_usd",
        ].some((k) => r[k] !== null)
      )
        return fail();
    } else if (r.kind === "ORDEN") {
      if (
        !row.pricing_revision ||
        cashCents(r.subtotal_usd) + cashCents(r.delivery_fee_usd) !==
          cashCents(r.total_usd)
      )
        return fail();
      for (const k of ["subtotal_usd", "delivery_fee_usd", "total_usd"])
        if (cashCents(r[k]) > BigInt("9999999999")) return fail();
    } else {
      const n = cashCents(r.amount_usd, r.kind === "MOVIMIENTO"),
        abs = n < BigInt(0) ? -n : n;
      if (n === BigInt(0) || abs > BigInt("9999999999")) return fail();
      if (
        r.kind === "MOVIMIENTO" &&
        cashCents(r.delta_usd, true) !==
          (includes(creditTypes, r.transaction_type)
            ? abs
            : includes(debitTypes, r.transaction_type)
              ? -abs
              : n)
      )
        return fail();
    }
    return row;
  });
  const valid = rows.filter((r) => r.included),
    orders = valid.filter((r) => r.kind === "ORDEN"),
    ledger = valid.filter((r) => r.kind === "MOVIMIENTO"),
    payouts = valid.filter((r) => r.kind === "RETIRO");
  same(v.orders, {
    ...orderTotal(orders),
    by_status: orderStates.map((status) => ({
      status,
      ...orderTotal(orders.filter((r) => r.status === status)),
    })),
  });
  same(v.ledger, {
    ...ledgerTotal(ledger),
    by_type: ledgerTypes.map((transaction_type) => {
      const rs = ledger.filter((r) => r.transaction_type === transaction_type);
      return {
        transaction_type,
        count: rs.length,
        amount_usd: centsText(
          rs.reduce((n, r) => n + cashCents(r.amount_usd, true), BigInt(0)),
        ),
        delta_usd: centsText(
          rs.reduce((n, r) => n + cashCents(r.delta_usd, true), BigInt(0)),
        ),
      };
    }),
  });
  same(v.payouts, {
    ...payoutTotal(payouts),
    by_status: payoutStates.map((status) => ({
      status,
      ...payoutTotal(payouts.filter((r) => r.status === status)),
    })),
  });
  same(
    v.exclusions,
    exclusionReasons.map((reason) => ({
      reason,
      count: rows.filter((r) => r.exclusion_reason === reason).length,
    })),
  );
  for (const kind of sourceKinds)
    same(obj(v.sources)[kind], {
      row_count: rows.filter((r) => r.kind === kind).length,
      included_count: valid.filter((r) => r.kind === kind).length,
      excluded_count: rows.filter((r) => r.kind === kind && !r.included).length,
    });
  same(v.row_count, rows.length);
  same(v.excluded_count, rows.length - valid.length);
  if (!Array.isArray(v.daily) || v.daily.length !== days) return fail();
  for (let i = 0; i < days; i++) {
    const date = new Date(Date.parse(first) + i * 86400000)
        .toISOString()
        .slice(0, 10),
      onDay = (rs: ExactRow[]) => rs.filter((r) => rowDays.get(r.key) === date);
    same(v.daily[i], {
      date,
      orders: orderTotal(onDay(orders)),
      ledger: ledgerTotal(onDay(ledger)),
      payouts: payoutTotal(onDay(payouts)),
    });
  }
  return { ...v, rows } as unknown as ExactReport;
}
export function exactReportCSV(v: ExactReport): Record<string, unknown>[] {
  const metadata = {
    desde_caracas: v.date_from,
    hasta_caracas: v.date_to,
    generado_utc: v.generated_at,
    huella_sha256: v.content_sha256,
    filas_completas: v.row_count,
    filas_excluidas: v.excluded_count,
    criterio: "FECHA_CREACION_FUENTE",
    moneda_totales: "USD",
    valor_ordenes_usd: v.orders.total_usd,
    cambio_ledger_usd: v.ledger.net_change_usd,
    solicitudes_retiro_usd: v.payouts.amount_usd,
  };
  return v.rows.length
    ? v.rows.map((r) => ({
        ...metadata,
        ...r,
        exclusion: r.exclusion_reason
          ? exclusionLabels[r.exclusion_reason]
          : "",
      }))
    : [{ ...metadata, nota: "Sin registros en el rango confirmado" }];
}
