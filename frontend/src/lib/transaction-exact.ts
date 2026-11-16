import { record } from "@/lib/operational-catalog";
import { cashCents } from "@/lib/customer-cashbook";
import {
  normalizeTransactionIdentity,
  transactionId,
  type PreparedTransactionQuery,
} from "@/lib/transaction-contract";
import { summaryDate } from "@/lib/financial-summary-contract";
const fail = (): never => {
  throw new Error(
    "No se pudo confirmar el registro decimal de transacciones. Vuelve a consultar.",
  );
};
const utcTime = (v: unknown): string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{6}Z$/.test(v) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v.slice(0, 10)
  )
    return fail();
  return v;
};
const filterTime = (v: string | undefined) =>
  v === undefined
    ? null
    : new Date(summaryDate(v).time).toISOString().replace("Z", "000Z");
const fields = ["amount", "balance_before", "balance_after"] as const;
export function normalizeExactTransaction(value: unknown, expectedId?: string) {
  const r = record(value),
    base = normalizeTransactionIdentity(r, expectedId);
  const rawCurrency = r.currency_recorded;
  if (
    rawCurrency !== null &&
    (typeof rawCurrency !== "string" || rawCurrency.length > 3)
  )
    return fail();
  const normal =
    typeof rawCurrency === "string" && /^[A-Z]{3}$/.test(rawCurrency)
      ? rawCurrency
      : null;
  if (
    base.currency !== normal ||
    r.currency_review !== (rawCurrency !== null && normal === null)
  )
    return fail();
  if (!Array.isArray(r.money_review)) return fail();
  const seen = new Set<string>();
  const review = r.money_review.map((value) => {
    const issue = record(value);
    if (
      !fields.includes(issue.field as never) ||
      seen.has(String(issue.field)) ||
      !["NO_REGISTRADO", "IMPORTE_NO_VALIDO"].includes(String(issue.reason)) ||
      (issue.reason === "NO_REGISTRADO" && issue.field !== "amount")
    )
      return fail();
    seen.add(String(issue.field));
    return {
      field: issue.field as (typeof fields)[number],
      reason: issue.reason as "NO_REGISTRADO" | "IMPORTE_NO_VALIDO",
    };
  });
  const amounts = {} as Record<(typeof fields)[number], string | null>;
  for (const name of fields) {
    const v = r[name];
    if (v === null) {
      if (name === "amount" && !seen.has(name)) return fail();
      amounts[name] = null;
    } else {
      cashCents(v, true);
      if (seen.has(name)) return fail();
      amounts[name] = v as string;
    }
  }
  for (const name of ["created_at", "updated_at", "processed_at"] as const)
    if (r[name] !== null) utcTime(r[name]);
  return {
    ...base,
    ...amounts,
    currency_recorded: rawCurrency as string | null,
    currency_review: r.currency_review as boolean,
    money_review: review,
  };
}
export type ExactTransaction = ReturnType<typeof normalizeExactTransaction>;
export interface TransactionReadContext {
  generated_at: string;
  content_sha256: string;
  viewer_user_id: string;
  viewer_role: string;
}
export function normalizeExactTransactionPage(
  value: unknown,
  query: PreparedTransactionQuery,
  expectedId?: string,
) {
  const p = record(value);
  if (
    p.version !== 1 ||
    p.scope !== "registered_financial_records" ||
    p.units_basis !== "recorded_currency_no_conversion" ||
    p.balance_basis !== "registered_snapshots_not_available_balance" ||
    p.snapshot_basis !== "single_statement_visibility" ||
    p.available_balance_included !== false ||
    p.bank_verified !== false ||
    p.wallet_cents_included !== false ||
    p.customer_cashbook_included !== false ||
    !["SUPERADMIN", "GERENTE"].includes(String(p.viewer_role))
  )
    return fail();
  const generated_at = utcTime(p.generated_at),
    viewer_user_id = transactionId(p.viewer_user_id);
  if (
    typeof p.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(p.content_sha256)
  )
    return fail();
  const expected = {
      transaction_id: expectedId ?? null,
      rider_id: query.rider_id ?? null,
      type: query.type ?? null,
      status: query.status ?? null,
      date_from: filterTime(query.date_from),
      date_to: filterTime(query.date_to),
    },
    filters = record(p.filters);
  for (const key of Object.keys(expected) as (keyof typeof expected)[])
    if (filters[key] !== expected[key]) return fail();
  if (
    p.limit !== query.limit ||
    p.offset !== query.offset ||
    !Array.isArray(p.items) ||
    p.items.length > query.limit ||
    p.total !== p.items.length ||
    (expectedId !== undefined && p.items.length !== 1)
  )
    return fail();
  const ids = new Set<string>();
  const items = p.items.map((raw) => {
    const r = normalizeExactTransaction(raw, expectedId);
    if (
      ids.has(r.id) ||
      (query.type && r.type !== query.type) ||
      (query.status && r.status !== query.status) ||
      (query.rider_id && r.rider_id !== query.rider_id) ||
      (expected.date_from &&
        (!r.created_at || r.created_at < expected.date_from)) ||
      (expected.date_to && (!r.created_at || r.created_at > expected.date_to))
    )
      return fail();
    ids.add(r.id);
    return r;
  });
  const read_context: TransactionReadContext = {
    generated_at,
    content_sha256: p.content_sha256,
    viewer_user_id,
    viewer_role: p.viewer_role as string,
  };
  return { items, read_context };
}
export function exactTransactionMoney(
  value: string | null,
  currency: string | null,
  review = false,
) {
  if (value === null)
    return review ? "Importe por revisar" : "Monto no informado";
  cashCents(value, true);
  const [whole, cents] = value.split(".");
  const number = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + cents;
  return currency ? `${number} ${currency}` : `${number} (moneda no informada)`;
}
export function exactTransactionCsv(
  rows: ExactTransaction[],
  context: { type: string; status: string; offset: number; search: string },
  read: TransactionReadContext | null,
) {
  if (read === null) return fail();
  return rows.map((r) => ({
    id: r.id,
    rider_id: r.rider_id ?? "",
    fecha_creacion_utc: r.created_at ?? "",
    fecha_actualizacion_utc: r.updated_at ?? "",
    fecha_proceso_utc: r.processed_at ?? "",
    tipo: r.type,
    estado: r.status ?? "",
    importe_registrado: r.amount,
    moneda: r.currency ?? "",
    moneda_original_informada: r.currency_recorded ?? "",
    moneda_por_revisar: r.currency_review,
    descripcion: r.description ?? "",
    referencia: r.reference_id ?? "",
    saldo_anterior: r.balance_before,
    saldo_posterior: r.balance_after,
    importes_por_revisar: JSON.stringify(r.money_review),
    origen_tipo: r.source_type ?? "",
    origen_id: r.source_id ?? "",
    clave_idempotencia_informada: r.idempotency_key ?? "",
    actor_creador_informado: r.created_by_user_id ?? "",
    corte_utc: read.generated_at,
    huella_sha256: read.content_sha256,
    consultado_por: read.viewer_user_id,
    saldo_disponible_incluido: false,
    verificado_por_banco: false,
    filtro_tipo: context.type,
    filtro_estado: context.status,
    desplazamiento_consulta: context.offset,
    busqueda_local: context.search,
    alcance:
      "Solo coincidencias de la página cargada; no es el historial completo",
  }));
}
