import { record } from "@/lib/operational-catalog";
import { transactionId } from "@/lib/transaction-contract";
import { exactRecordTime } from "@/lib/transaction-exact";
import { cashCents } from "@/lib/customer-cashbook";
export type BonusRecord = {
  order_id: string;
  delivery_id: string | null;
  rider_id: string | null;
  source: "delivery_snapshot" | "order_without_delivery";
  status: string | null;
  amount: string | null;
  base: string | null;
  zone_multiplier: string | null;
  tier_multiplier: string | null;
  tier_level: string | null;
  bonus_type: string | null;
  snapshot_date: string | null;
  config_warning: string | null;
  currency: string | null;
  currency_recorded: string | null;
  currency_review: boolean;
  state_review: boolean;
  money_review: { field: string; reason: "IMPORTE_NO_VALIDO" }[];
};
export type BonusRecords = {
  version: 1;
  scope: "recorded_delivery_bonus_snapshots";
  snapshot_basis: "single_statement_visibility";
  units_basis: "stored_snapshot_only";
  actor: { user_id: string; role: string };
  order_ids: string[];
  records: BonusRecord[];
  generated_at: string;
  bank_verified: false;
  available_balance_included: false;
  ledger_credit_included: false;
  content_sha256: string;
};
function fail(): never {
  throw new Error(
    "No se pudo confirmar el bono conservado. Reintenta su lectura.",
  );
}
const fields = {
  amount: "locked_bonus_amount",
  base: "locked_bonus_base",
  zone_multiplier: "locked_bonus_zone_multiplier",
  tier_multiplier: "locked_bonus_tier_multiplier",
} as const;
const text = (v: unknown): string | null => {
  if (v !== null && typeof v !== "string") fail();
  return v as string | null;
};
export function bonusOrderIds(values: string[]): string[] {
  if (
    !values.length ||
    values.length > 10 ||
    new Set(values).size !== values.length
  )
    fail();
  return values.map(transactionId);
}
export function normalizeBonusRecords(
  value: unknown,
  orders: string[],
  actor: { user_id: string; role: string },
): BonusRecords {
  const r = record(value),
    a = record(r.actor);
  bonusOrderIds(orders);
  if (
    r.version !== 1 ||
    r.scope !== "recorded_delivery_bonus_snapshots" ||
    r.snapshot_basis !== "single_statement_visibility" ||
    r.units_basis !== "stored_snapshot_only" ||
    a.user_id !== actor.user_id ||
    a.role !== actor.role ||
    r.bank_verified !== false ||
    r.available_balance_included !== false ||
    r.ledger_credit_included !== false ||
    typeof r.content_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(r.content_sha256) ||
    !Array.isArray(r.order_ids) ||
    JSON.stringify(r.order_ids) !== JSON.stringify(orders) ||
    !Array.isArray(r.records) ||
    r.records.length !== orders.length
  )
    fail();
  exactRecordTime(r.generated_at);
  const records = r.records.map((value, index) => {
    const row = record(value);
    if (
      row.order_id !== orders[index] ||
      !["delivery_snapshot", "order_without_delivery"].includes(
        row.source as string,
      ) ||
      typeof row.state_review !== "boolean" ||
      !Array.isArray(row.money_review)
    )
      fail();
    const issues = row.money_review.map((v) => {
      const i = record(v);
      if (
        !Object.values(fields).includes(i.field as any) ||
        i.reason !== "IMPORTE_NO_VALIDO"
      )
        fail();
      return { field: i.field as string, reason: "IMPORTE_NO_VALIDO" as const };
    });
    if (new Set(issues.map((i) => i.field)).size !== issues.length) fail();
    for (const [field, origin] of Object.entries(fields)) {
      if (row[field] !== null) {
        if (
          cashCents(row[field]) >
          BigInt(
            field === "zone_multiplier" || field === "tier_multiplier"
              ? 9999
              : 9999999999,
          )
        )
          fail();
      }
      if (issues.some((i) => i.field === origin) && row[field] !== null) fail();
    }
    const unit = text(row.currency_recorded),
      currency = text(row.currency);
    if (
      unit === null
        ? currency !== null || row.currency_review !== false
        : /^[A-Z]{3}$/.test(unit)
          ? currency !== unit || row.currency_review !== false
          : currency !== null || row.currency_review !== true
    )
      fail();
    const delivery =
      row.delivery_id === null ? null : transactionId(row.delivery_id);
    if (
      row.source === "order_without_delivery"
        ? delivery !== null ||
          row.rider_id !== null ||
          unit !== null ||
          issues.length > 0 ||
          Object.keys(fields).some((k) => row[k] !== null) ||
          [
            row.status,
            row.tier_level,
            row.bonus_type,
            row.snapshot_date,
            row.config_warning,
          ].some((v) => v !== null)
        : delivery === null
    )
      fail();
    if (row.snapshot_date !== null) exactRecordTime(row.snapshot_date);
    return {
      ...row,
      delivery_id: delivery,
      rider_id: row.rider_id === null ? null : transactionId(row.rider_id),
      status: text(row.status),
      tier_level: text(row.tier_level),
      bonus_type: text(row.bonus_type),
      snapshot_date: text(row.snapshot_date),
      config_warning: text(row.config_warning),
      currency,
      currency_recorded: unit,
      money_review: issues,
    } as BonusRecord;
  });
  if (
    new Set(
      records.filter((r) => r.delivery_id !== null).map((r) => r.delivery_id),
    ).size !== records.filter((r) => r.delivery_id !== null).length
  )
    fail();
  return {
    ...r,
    actor: { ...a },
    order_ids: [...orders],
    records,
  } as BonusRecords;
}
