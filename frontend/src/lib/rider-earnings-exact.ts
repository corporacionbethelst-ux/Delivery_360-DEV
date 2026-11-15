import { cashCents, cashDay, cashText } from "@/lib/customer-cashbook";
import { orderQuoteId } from "@/lib/order-currency-quote";
import { creditTypes, debitTypes, ledgerTypes } from "@/lib/financial-exact";
export { cashText as riderMoney };
export interface RiderLedgerRow {
  key: string;
  id: string;
  rider_id: string;
  occurred_at: string | null;
  currency: string | null;
  status: string | null;
  transaction_type: string | null;
  included: boolean;
  exclusion_reason: string | null;
  amount_usd: string | null;
  delta_usd: string | null;
  description: string | null;
}
export interface EarningsTotal {
  count: number;
  credit_usd: string;
  debit_usd: string;
  adjustment_usd: string;
  net_change_usd: string;
  completed_delivery_count: number;
}
export interface RiderExactReport {
  version: 1;
  scope: "own_recorded_usd_earnings";
  user_id: string;
  rider_id: string;
  currency: "USD";
  timezone: "America/Caracas";
  generated_at: string;
  today: string;
  week_from: string;
  snapshot_basis: "single_statement_visibility";
  earnings_basis: "processed_ledger_credits";
  available_balance_included: false;
  order_values_included: false;
  wallet_cents_included: false;
  bank_verified: false;
  maximum_rows: 10000;
  export_complete: true;
  row_count: number;
  excluded_count: number;
  lifetime: EarningsTotal;
  day: EarningsTotal;
  week: EarningsTotal;
  daily: (EarningsTotal & { date: string })[];
  exclusions: { reason: string; count: number }[];
  rows: RiderLedgerRow[];
  content_sha256: string;
}
export interface RiderExactBalance {
  version: 1;
  scope: "own_canonical_usd_balance";
  user_id: string;
  rider_id: string;
  currency: "USD";
  generated_at: string;
  snapshot_basis: "rider_row_lock";
  ledger_integrity: "verified" | "no_evidence";
  bank_verified: false;
  available: string;
  pending: string;
  processed: string;
  total_earned: string;
  ledger_balance: string;
  reserved: string;
  unverified_financial_count: number;
  unverified_payout_count: number;
  minimum_withdrawal_usd: "10.00";
}
export const riderExclusions = {
  MONEDA_NO_VERIFICADA: "Moneda sin verificar",
  FECHA_NO_REGISTRADA: "Sin fecha registrada",
  ESTADO_NO_PROCESADO: "Movimiento sin procesar",
  TIPO_NO_ADMITIDO: "Tipo ajeno al libro USD",
  FECHA_FUTURA: "Fecha posterior al corte",
};
const fail = (): never => {
  throw new Error(
    "No se pudieron confirmar las cifras exactas de tu cuenta. Vuelve a consultar.",
  );
};
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return fail();
  return v as Record<string, unknown>;
};
const contains = (a: readonly string[], v: unknown) =>
  typeof v === "string" && a.includes(v);
const count = (v: unknown) => {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0) return fail();
  return v;
};
function time(v: unknown): string {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{6}Z$/.test(v) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v.slice(0, 10)
  )
    return fail();
  return v;
}
const textCents = (n: bigint) =>
  `${n < BigInt(0) ? "-" : ""}${(n < BigInt(0) ? -n : n) / BigInt(100)}.${((n < BigInt(0) ? -n : n) % BigInt(100)).toString().padStart(2, "0")}`;
function totals(rows: RiderLedgerRow[]): EarningsTotal {
  let c = BigInt(0),
    d = BigInt(0),
    a = BigInt(0),
    completed = 0;
  for (const r of rows) {
    const n = cashCents(r.delta_usd, true);
    if (contains(creditTypes, r.transaction_type)) c += n;
    else if (contains(debitTypes, r.transaction_type)) d -= n;
    else a += n;
    if (r.transaction_type === "PAGO_ENTREGA") completed++;
  }
  return {
    count: rows.length,
    credit_usd: textCents(c),
    debit_usd: textCents(d),
    adjustment_usd: textCents(a),
    net_change_usd: textCents(c - d + a),
    completed_delivery_count: completed,
  };
}
function same(actual: unknown, expected: unknown) {
  const a = object(actual);
  for (const [k, v] of Object.entries(object(expected)))
    if (a[k] !== v) return fail();
}
function identity(v: Record<string, unknown>, userId: string) {
  orderQuoteId(userId);
  orderQuoteId(v.user_id);
  orderQuoteId(v.rider_id);
  if (
    v.user_id !== userId ||
    v.currency !== "USD" ||
    v.version !== 1 ||
    v.bank_verified !== false
  )
    return fail();
  return time(v.generated_at);
}
export function validateRiderReport(
  raw: unknown,
  userId: string,
): RiderExactReport {
  const v = object(raw),
    generated = identity(v, userId),
    today = cashDay(generated),
    first = new Date(Date.parse(today) - 6 * 86400000)
      .toISOString()
      .slice(0, 10);
  same(v, {
    scope: "own_recorded_usd_earnings",
    timezone: "America/Caracas",
    today,
    week_from: first,
    snapshot_basis: "single_statement_visibility",
    earnings_basis: "processed_ledger_credits",
    available_balance_included: false,
    order_values_included: false,
    wallet_cents_included: false,
    maximum_rows: 10000,
    export_complete: true,
  });
  if (
    typeof v.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.content_sha256) ||
    !Array.isArray(v.rows) ||
    v.rows.length > 10000
  )
    return fail();
  const ids = new Set<string>(),
    days = new Map<string, string>();
  const rows = v.rows.map((raw) => {
    const r = object(raw);
    orderQuoteId(r.id);
    if (
      r.rider_id !== v.rider_id ||
      r.key !== `MOVIMIENTO:${r.id}` ||
      ids.has(r.id as string)
    )
      return fail();
    ids.add(r.id as string);
    for (const k of ["status", "transaction_type", "description"])
      if (r[k] !== null && typeof r[k] !== "string") return fail();
    if (
      r.currency !== null &&
      (typeof r.currency !== "string" || !/^[A-Z]{3}$/.test(r.currency))
    )
      return fail();
    const stamp = r.occurred_at === null ? null : time(r.occurred_at);
    let reason: string | null = null;
    if (stamp && stamp > generated) reason = "FECHA_FUTURA";
    else if (!stamp) reason = "FECHA_NO_REGISTRADA";
    else if (r.currency !== "USD") reason = "MONEDA_NO_VERIFICADA";
    else if (!contains(["PROCESADO", "PAGADO"], r.status))
      reason = "ESTADO_NO_PROCESADO";
    else if (!contains(ledgerTypes, r.transaction_type))
      reason = "TIPO_NO_ADMITIDO";
    if (r.exclusion_reason !== reason || r.included !== (reason === null))
      return fail();
    if (reason) {
      if (r.amount_usd !== null || r.delta_usd !== null) return fail();
    } else {
      const n = cashCents(r.amount_usd, true),
        abs = n < BigInt(0) ? -n : n,
        delta = contains(creditTypes, r.transaction_type)
          ? abs
          : contains(debitTypes, r.transaction_type)
            ? -abs
            : n;
      if (
        !n ||
        abs > BigInt("9999999999") ||
        cashCents(r.delta_usd, true) !== delta
      )
        return fail();
      days.set(r.id as string, cashDay(stamp!));
    }
    return r as unknown as RiderLedgerRow;
  });
  const valid = rows.filter((r) => r.included),
    week = valid.filter(
      (r) => days.get(r.id)! >= first && days.get(r.id)! <= today,
    ),
    day = week.filter((r) => days.get(r.id) === today);
  if (
    v.row_count !== rows.length ||
    v.excluded_count !== rows.length - valid.length
  )
    return fail();
  same(v.lifetime, totals(valid));
  same(v.week, totals(week));
  same(v.day, totals(day));
  if (
    !Array.isArray(v.daily) ||
    v.daily.length !== 7 ||
    !Array.isArray(v.exclusions) ||
    v.exclusions.length !== 5
  )
    return fail();
  for (let i = 0; i < 7; i++) {
    const date = new Date(Date.parse(first) + i * 86400000)
      .toISOString()
      .slice(0, 10);
    same(v.daily[i], {
      date,
      ...totals(week.filter((r) => days.get(r.id) === date)),
    });
  }
  Object.keys(riderExclusions).forEach((reason, i) =>
    same((v.exclusions as unknown[])[i], {
      reason,
      count: rows.filter((r) => r.exclusion_reason === reason).length,
    }),
  );
  return { ...v, rows } as unknown as RiderExactReport;
}
export function validateRiderBalance(
  raw: unknown,
  userId: string,
): RiderExactBalance {
  const v = object(raw);
  identity(v, userId);
  same(v, {
    scope: "own_canonical_usd_balance",
    snapshot_basis: "rider_row_lock",
    minimum_withdrawal_usd: "10.00",
  });
  if (!contains(["verified", "no_evidence"], v.ledger_integrity)) return fail();
  const available = cashCents(v.available),
    pending = cashCents(v.pending),
    processed = cashCents(v.processed),
    reserved = cashCents(v.reserved),
    ledger = cashCents(v.ledger_balance, true),
    earned = cashCents(v.total_earned);
  const expected = ledger - reserved;
  if (
    available !== (expected > BigInt(0) ? expected : BigInt(0)) ||
    reserved > pending + processed ||
    (v.ledger_integrity === "no_evidence" &&
      (ledger !== BigInt(0) || earned !== BigInt(0)))
  )
    return fail();
  count(v.unverified_financial_count);
  count(v.unverified_payout_count);
  return v as unknown as RiderExactBalance;
}
export function riderEarningsCSV(
  v: RiderExactReport,
): Record<string, unknown>[] {
  const metadata = {
    usuario: v.user_id,
    repartidor: v.rider_id,
    corte_utc: v.generated_at,
    huella_sha256: v.content_sha256,
    filas_completas: v.row_count,
    filas_excluidas: v.excluded_count,
    moneda_totales: "USD",
    creditos_historicos_usd: v.lifetime.credit_usd,
    neto_contable_usd: v.lifetime.net_change_usd,
  };
  return v.rows.length
    ? v.rows.map((r) => ({ ...metadata, ...r }))
    : [{ ...metadata, nota: "Sin movimientos registrados" }];
}
