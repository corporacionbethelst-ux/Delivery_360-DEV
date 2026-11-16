import { record } from "@/lib/operational-catalog";
import { cashCents } from "@/lib/customer-cashbook";
import {
  exactRecordTime,
  exactTransactionMoney,
  type TransactionReadContext,
} from "@/lib/transaction-exact";
import { transactionId } from "@/lib/transaction-contract";
import {
  payoutMethod,
  payoutStatusValue,
  payoutCents,
} from "@/lib/payout-contract";
import type { Payout, PayoutPageFilters } from "@/services/payout.service";
const fail = (): never => {
  throw new Error(
    "No se pudo confirmar el registro exacto de retiros. Vuelve a consultar.",
  );
};
const text = (v: unknown): string | null =>
  v === null ? null : typeof v === "string" ? v : fail();
const id = (v: unknown) => transactionId(v);
const optionalId = (v: unknown) => (v === null ? null : id(v));
const moneyFields = ["amount", "balance_before", "balance_after"] as const;
const cursor = (v: unknown): v is string =>
  typeof v === "string" &&
  v.length <= 2048 &&
  /^[A-Za-z0-9_-]+\.[a-f0-9]{64}$/.test(v);
export const payoutExactMoney = (
  value: string | null | undefined,
  currency?: string | null,
  review = false,
) => exactTransactionMoney(value ?? null, currency ?? null, review);
export function prepareExactPayoutQuery(
  value?: Readonly<PayoutPageFilters & { audience?: "STAFF" | "OWNER" }>,
) {
  const q = { ...value };
  if (
    Object.keys(q).some(
      (k) => !["rider_id", "status", "limit", "cursor", "audience"].includes(k),
    )
  )
    return fail();
  const status =
    q.status === undefined || q.status === "ALL" || q.status === "all"
      ? null
      : q.status;
  if (
    status !== null &&
    ![
      "PENDIENTE",
      "APROBADO",
      "EN_PROCESO",
      "COMPLETADO",
      "RECHAZADO",
      "FALLIDO",
    ].includes(status)
  )
    return fail();
  if (q.cursor != null && !cursor(q.cursor)) return fail();
  if (
    q.audience !== undefined &&
    q.audience !== "STAFF" &&
    q.audience !== "OWNER"
  )
    return fail();
  return {
    audience: q.audience ?? null,
    limit: Number.isFinite(q.limit)
      ? Math.min(Math.max(Math.trunc(q.limit!), 1), 200)
      : 50,
    status,
    cursor: q.cursor ?? null,
    rider_id: q.rider_id === undefined ? null : id(q.rider_id.trim()),
  };
}
function monetary(r: Record<string, unknown>, history = false) {
  const currency_recorded = text(r.currency_recorded);
  if (currency_recorded !== null && currency_recorded.length > 3) return fail();
  const currency =
    currency_recorded !== null && /^[A-Z]{3}$/.test(currency_recorded)
      ? currency_recorded
      : null;
  if (
    r.currency !== currency ||
    r.currency_review !== (currency_recorded !== null && currency === null) ||
    !Array.isArray(r.money_review)
  )
    return fail();
  const seen = new Set<string>();
  const money_review = r.money_review.map((v) => {
    const e = record(v);
    if (
      !moneyFields.includes(e.field as never) ||
      (history && e.field === "amount") ||
      seen.has(String(e.field)) ||
      !["NO_REGISTRADO", "IMPORTE_NO_VALIDO"].includes(String(e.reason)) ||
      (e.reason === "NO_REGISTRADO" && e.field !== "amount")
    )
      return fail();
    seen.add(String(e.field));
    return {
      field: e.field as (typeof moneyFields)[number],
      reason: e.reason as "NO_REGISTRADO" | "IMPORTE_NO_VALIDO",
    };
  });
  const values = {} as Record<(typeof moneyFields)[number], string | null>;
  for (const name of history
    ? (["balance_before", "balance_after"] as const)
    : moneyFields) {
    const value = r[name];
    if (value === null) {
      if (name === "amount" && !seen.has(name)) return fail();
      values[name] = null;
    } else {
      const cents = cashCents(value, true);
      if (
        seen.has(name) ||
        (name === "amount" &&
          (cents <= BigInt(0) || cents > BigInt("9999999999")))
      )
        return fail();
      values[name] = value as string;
    }
  }
  return {
    ...values,
    currency,
    currency_recorded,
    currency_review: r.currency_review as boolean,
    money_review,
  };
}
export function normalizeExactPayout(value: unknown, expectedId?: string) {
  const r = record(value),
    pid = id(r.id);
  if (expectedId !== undefined && pid !== expectedId) return fail();
  const m = monetary(r);
  if (r.total_amount !== m.amount) return fail();
  const method = r.method === null ? null : payoutMethod(r.method);
  if (r.payment_method !== method) return fail();
  const status = r.status === null ? null : payoutStatusValue(r.status);
  const bank = text(r.bank_account_last4);
  if (
    (bank !== null && !/^\d{4}$/.test(bank)) ||
    typeof r.bank_destination_review !== "boolean" ||
    (r.bank_destination_review && bank !== null)
  )
    return fail();
  const dates = {} as Record<
    | "requested_at"
    | "created_at"
    | "processed_at"
    | "updated_at"
    | "period_start"
    | "period_end",
    string | null
  >;
  for (const name of [
    "requested_at",
    "created_at",
    "processed_at",
    "updated_at",
    "period_start",
    "period_end",
  ] as const)
    dates[name] = r[name] === null ? null : exactRecordTime(r[name]);
  if (
    dates.created_at !== dates.requested_at ||
    r.orders_count !== null ||
    r.period !== null
  )
    return fail();
  return {
    ...m,
    ...dates,
    id: pid,
    rider_id: id(r.rider_id),
    status,
    method,
    payment_method: method,
    total_amount: m.amount,
    bank_account_last4: bank,
    bank_destination_review: r.bank_destination_review as boolean,
    reference_code: text(r.reference_code),
    rejection_reason: text(r.rejection_reason),
    idempotency_key: text(r.idempotency_key),
    requested_by_user_id: optionalId(r.requested_by_user_id),
    processed_by_user_id: optionalId(r.processed_by_user_id),
    orders_count: null,
    period: null,
  };
}
export type ExactPayout = ReturnType<typeof normalizeExactPayout>;
function normalizeHistory(value: unknown, payoutId: string) {
  if (!Array.isArray(value) || value.length > 1000) return fail();
  const ids = new Set<string>();
  return value.map((raw) => {
    const r = record(raw),
      eid = id(r.id);
    if (ids.has(eid) || r.payout_id !== payoutId) return fail();
    ids.add(eid);
    const m = monetary(r, true);
    return {
      balance_before: m.balance_before,
      balance_after: m.balance_after,
      currency: m.currency,
      currency_recorded: m.currency_recorded,
      currency_review: m.currency_review,
      money_review: m.money_review,
      id: eid,
      payout_id: payoutId,
      old_status: text(r.old_status),
      new_status: text(r.new_status),
      reason: text(r.reason),
      changed_by_user_id: optionalId(r.changed_by_user_id),
      created_at: r.created_at === null ? null : exactRecordTime(r.created_at),
    };
  });
}
export type ExactPayoutHistory = ReturnType<typeof normalizeHistory>[number];
export interface PayoutReadContext extends TransactionReadContext {
  effective_rider_id: string | null;
}
export function normalizeExactPayoutPage(
  value: unknown,
  query: ReturnType<typeof prepareExactPayoutQuery>,
  payoutId?: string,
) {
  const p = record(value),
    detail = payoutId !== undefined;
  if (
    p.version !== 1 ||
    p.scope !== "registered_payout_records" ||
    p.units_basis !== "recorded_currency_no_conversion" ||
    p.balance_basis !== "registered_snapshots_not_available_balance" ||
    p.snapshot_basis !== "single_statement_visibility" ||
    p.pagination_basis !== "signed_position_live_records" ||
    p.available_balance_included !== false ||
    p.bank_verified !== false ||
    p.wallet_cents_included !== false ||
    !["SUPERADMIN", "GERENTE", "REPARTIDOR"].includes(String(p.viewer_role))
  )
    return fail();
  const read_context: PayoutReadContext = {
    generated_at: exactRecordTime(p.generated_at),
    content_sha256:
      typeof p.content_sha256 === "string" &&
      /^[a-f0-9]{64}$/.test(p.content_sha256)
        ? p.content_sha256
        : fail(),
    viewer_user_id: id(p.viewer_user_id),
    viewer_role: p.viewer_role as string,
    effective_rider_id: optionalId(p.effective_rider_id),
  };
  if (
    (read_context.viewer_role === "REPARTIDOR" &&
      read_context.effective_rider_id === null) ||
    (read_context.viewer_role !== "REPARTIDOR" &&
      read_context.effective_rider_id !== query.rider_id)
  )
    return fail();
  if (
    (query.audience === "OWNER" && read_context.viewer_role !== "REPARTIDOR") ||
    (query.audience === "STAFF" &&
      !["GERENTE", "SUPERADMIN"].includes(read_context.viewer_role))
  )
    return fail();
  const filters = record(p.filters);
  if (
    filters.audience !== query.audience ||
    filters.rider_id !== query.rider_id ||
    filters.status !== query.status ||
    filters.payout_id !== (payoutId ?? null) ||
    p.limit !== query.limit ||
    p.cursor !== query.cursor ||
    !Array.isArray(p.items) ||
    p.items.length > query.limit ||
    p.total !== p.items.length ||
    (detail && p.items.length !== 1)
  )
    return fail();
  const seen = new Set<string>();
  const items = p.items.map((raw) => {
    const r = normalizeExactPayout(raw, payoutId);
    if (
      seen.has(r.id) ||
      (query.status && r.status !== query.status) ||
      (read_context.effective_rider_id !== null &&
        r.rider_id !== read_context.effective_rider_id) ||
      (query.rider_id !== null && r.rider_id !== query.rider_id)
    )
      return fail();
    seen.add(r.id);
    return r;
  });
  if (
    p.next_cursor !== null &&
    (!cursor(p.next_cursor) ||
      p.next_cursor === query.cursor ||
      items.length !== query.limit ||
      detail)
  )
    return fail();
  if (
    p.history_included !== detail ||
    p.history_complete !== detail ||
    p.history_limit !== (detail ? 1000 : null)
  )
    return fail();
  const history = normalizeHistory(p.history, payoutId ?? "");
  if (!detail && history.length) return fail();
  return {
    items,
    next_cursor: p.next_cursor as string | null,
    read_context,
    history,
  };
}
export function canReviewPayout(p: ExactPayout) {
  return (
    p.amount !== null &&
    p.method !== null &&
    !p.currency_review &&
    !p.bank_destination_review &&
    p.money_review.length === 0
  );
}
/** Boundary for unchanged numeric mutation confirmations; never used as a read model. */
export function confirmExactPayoutDecision(
  confirmed: Payout,
  prior: ExactPayout,
  action: "approve" | "reject",
) {
  if (
    !canReviewPayout(prior) ||
    confirmed.id !== prior.id ||
    confirmed.rider_id !== prior.rider_id ||
    (confirmed.currency ?? null) !== prior.currency ||
    confirmed.method !== prior.method ||
    (confirmed.bank_account_last4 ?? null) !== prior.bank_account_last4 ||
    BigInt(payoutCents(confirmed.amount)) !== cashCents(prior.amount) ||
    (action === "reject"
      ? confirmed.status !== "RECHAZADO"
      : confirmed.status !== "EN_PROCESO")
  )
    return fail();
  return confirmed.status;
}
export function completedPayoutUsd(rows: ExactPayout[]) {
  let cents = BigInt(0),
    excluded = 0;
  for (const r of rows)
    if (r.status === "COMPLETADO") {
      if (r.currency === "USD" && r.amount !== null)
        cents += cashCents(r.amount);
      else excluded++;
    }
  return {
    amount:
      (cents / BigInt(100)).toString() +
      "." +
      (cents % BigInt(100)).toString().padStart(2, "0"),
    excluded,
  };
}
export function exactPayoutCsv(
  rows: ExactPayout[],
  context: {
    status: string;
    offset: number;
    search: string;
    cursor: string | null;
  },
  read: PayoutReadContext | null,
) {
  if (read === null) return fail();
  return rows.map((r) => ({
    id: r.id,
    rider_id: r.rider_id,
    importe_registrado: r.amount,
    moneda: r.currency ?? "",
    moneda_original_informada: r.currency_recorded ?? "",
    moneda_por_revisar: r.currency_review,
    importes_por_revisar: JSON.stringify(r.money_review),
    destino_por_revisar: r.bank_destination_review,
    estado: r.status ?? "",
    metodo: r.method ?? "",
    fecha_solicitud_utc: r.requested_at ?? "",
    fecha_proceso_utc: r.processed_at ?? "",
    saldo_anterior_registrado: r.balance_before,
    saldo_posterior_registrado: r.balance_after,
    referencia: r.reference_code ?? "",
    motivo_rechazo: r.rejection_reason ?? "",
    actor_solicitud: r.requested_by_user_id ?? "",
    actor_proceso: r.processed_by_user_id ?? "",
    clave_idempotencia: r.idempotency_key ?? "",
    corte_utc: read.generated_at,
    huella_sha256: read.content_sha256,
    consultado_por: read.viewer_user_id,
    saldo_disponible_incluido: false,
    verificado_por_banco: false,
    filtro_estado: context.status,
    pagina_local: context.offset / 50 + 1,
    cursor_consulta: context.cursor ?? "",
    busqueda_local: context.search,
    alcance:
      "Solo coincidencias de la página cargada; no es el historial completo",
  }));
}
