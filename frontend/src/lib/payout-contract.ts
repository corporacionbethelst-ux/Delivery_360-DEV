import type {
  Payout,
  PayoutBalance,
  PayoutMethod,
  PayoutStatus,
  PayoutStatusHistory,
} from "@/services/payout.service";
import type { WithdrawalIntent } from "@/lib/withdrawal-intent";

const statuses = new Set<PayoutStatus>([
  "PENDIENTE",
  "APROBADO",
  "EN_PROCESO",
  "COMPLETADO",
  "RECHAZADO",
  "FALLIDO",
  "PROCESADO",
  "CANCELADO",
]);
const methods = new Set<PayoutMethod>([
  "TRANSFERENCIA",
  "EFECTIVO",
  "BILLETERA_DIGITAL",
]);
const invalid = (): never => {
  throw new Error(
    "La respuesta de retiro está incompleta o no coincide con la solicitud",
  );
};
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : invalid();
export const payoutId = (value: unknown): string =>
  typeof value === "string" && !!value.trim() && value === value.trim()
    ? value
    : invalid();
export const payoutKey = (value: unknown): string => {
  const key = payoutId(value);
  return key.length <= 100 ? key : invalid();
};
export const payoutMethod = (value: unknown): PayoutMethod =>
  methods.has(value as PayoutMethod) ? (value as PayoutMethod) : invalid();
const status = (value: unknown): PayoutStatus =>
  statuses.has(value as PayoutStatus) ? (value as PayoutStatus) : invalid();

/** Decimal precision is checked before conversion; booleans/blanks are never money. */
export function payoutCents(value: unknown, signed = false): number {
  if (typeof value !== "number" && typeof value !== "string") return invalid();
  if (
    !new RegExp(
      signed ? "^-?\\d{1,13}(?:\\.\\d{1,2})?$" : "^\\d{1,13}(?:\\.\\d{1,2})?$",
    ).test(String(value))
  )
    return invalid();
  const cents = Math.round(Number(value) * 100);
  return Number.isSafeInteger(cents) ? cents : invalid();
}
const optionalMoney = (value: unknown): number | null =>
  value == null ? null : payoutCents(value, true) / 100;
const optionalText = (value: unknown): string | null =>
  value == null ? null : typeof value === "string" ? value : invalid();
const date = (value: unknown): string | null => {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(
      value,
    ) ||
    !Number.isFinite(Date.parse(value))
  )
    return null;
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(day.getTime()) &&
    day.toISOString().slice(0, 10) === value.slice(0, 10)
    ? value
    : null;
};
export const payoutAmountLabel = (
  amount: number | null | undefined,
  currency?: string,
): string => {
  if (typeof amount !== "number" || !Number.isFinite(amount))
    return "Monto no informado";
  if (currency)
    return new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency,
    }).format(amount);
  return `${new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)} (moneda no informada)`;
};
export const payoutDateLabel = (value: string | null | undefined): string =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString("es-ES")
    : "Fecha no informada";

export function declaredCurrency(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value !== "string" || !/^[A-Z]{3}$/.test(value)) return invalid();
  return value;
}
function optionalCount(value: unknown): number | undefined {
  if (value == null) return undefined;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    return invalid();
  return value;
}
export function normalizePayout(value: unknown, expectedId?: string): Payout {
  const p = object(value),
    id = payoutId(p.id),
    riderId = payoutId(p.rider_id);
  if (expectedId !== undefined && id !== expectedId) return invalid();
  const cents = payoutCents(p.amount ?? p.total_amount);
  if (
    cents <= 0 ||
    cents > 9999999999 ||
    (p.amount != null &&
      p.total_amount != null &&
      payoutCents(p.total_amount) !== cents)
  )
    return invalid();
  const method = payoutMethod(p.method ?? p.payment_method);
  if (
    p.method != null &&
    p.payment_method != null &&
    p.method !== p.payment_method
  )
    return invalid();
  const bank = optionalText(p.bank_account_last4);
  if (bank !== null && !/^\d{4}$/.test(bank)) return invalid();
  const requested = date(p.requested_at) ?? date(p.created_at);
  const count = p.orders_count == null ? undefined : p.orders_count;
  if (
    count !== undefined &&
    (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0)
  )
    return invalid();
  return {
    currency: declaredCurrency(p.currency),
    id,
    rider_id: riderId,
    amount: cents / 100,
    total_amount: cents / 100,
    method,
    payment_method: method,
    status: status(p.status),
    requested_at: requested,
    created_at: date(p.created_at) ?? requested,
    updated_at: date(p.updated_at),
    processed_at: date(p.processed_at),
    bank_account_last4: bank,
    reference_code: optionalText(p.reference_code),
    rejection_reason: optionalText(p.rejection_reason),
    balance_before: optionalMoney(p.balance_before),
    balance_after: optionalMoney(p.balance_after),
    requested_by_user_id:
      p.requested_by_user_id == null ? null : payoutId(p.requested_by_user_id),
    processed_by_user_id:
      p.processed_by_user_id == null ? null : payoutId(p.processed_by_user_id),
    idempotency_key:
      p.idempotency_key == null ? null : payoutKey(p.idempotency_key),
    orders_count: count as number | undefined,
    period: optionalText(p.period),
    period_start: date(p.period_start),
    period_end: date(p.period_end),
  };
}
export function confirmWithdrawal(
  value: unknown,
  intent: WithdrawalIntent,
): Payout {
  const p = normalizePayout(value);
  if (
    p.currency !== "USD" ||
    p.idempotency_key !== intent.key ||
    p.requested_by_user_id !== intent.userId ||
    payoutCents(p.amount) !== intent.amountCents ||
    p.method !== "TRANSFERENCIA" ||
    (p.bank_account_last4 ?? "") !== intent.bankLast4
  )
    return invalid();
  return p;
}
export function normalizePayoutBalance(value: unknown): PayoutBalance {
  const b = object(value);
  if (b.degraded === true)
    throw new Error(
      "El saldo no está disponible temporalmente. Vuelve a consultarlo antes de crear un retiro.",
    );
  if (b.degraded !== undefined && b.degraded !== false) return invalid();
  return {
    available: payoutCents(b.available) / 100,
    pending: payoutCents(b.pending) / 100,
    processed: b.processed == null ? undefined : payoutCents(b.processed) / 100,
    total_earned:
      b.total_earned == null ? undefined : payoutCents(b.total_earned) / 100,
    currency: declaredCurrency(b.currency),
    unverified_financial_count: optionalCount(b.unverified_financial_count),
    unverified_payout_count: optionalCount(b.unverified_payout_count),
  };
}
export function normalizePayoutHistory(
  value: unknown,
  expectedId: string,
): PayoutStatusHistory[] {
  if (!Array.isArray(value)) return invalid();
  const ids = new Set<string>();
  return value.map((value) => {
    const r = object(value),
      id = payoutId(r.id);
    if (ids.has(id) || r.payout_id !== expectedId) return invalid();
    ids.add(id);
    return {
      id,
      payout_id: expectedId,
      currency: declaredCurrency(r.currency),
      old_status: r.old_status == null ? null : status(r.old_status),
      new_status: status(r.new_status),
      reason: optionalText(r.reason),
      changed_by_user_id:
        r.changed_by_user_id == null ? null : payoutId(r.changed_by_user_id),
      balance_before: optionalMoney(r.balance_before),
      balance_after: optionalMoney(r.balance_after),
      created_at: date(r.created_at),
    };
  });
}
