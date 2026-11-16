/** HTTP-shaped fixtures for exact reads. Legacy writes retain their numeric contract. */
import {
  normalizeExactPayout,
  normalizeExactPayoutPage,
  prepareExactPayoutQuery,
} from "../src/lib/payout-exact";
export const payoutTime = "2026-11-16T12:00:00.000000Z";
const time = (v: any) =>
  v == null ? null : new Date(v).toISOString().replace("Z", "000Z");
const money = (v: any) =>
  v == null ? null : typeof v === "string" ? v : v.toFixed(2);
export function payoutRecord(r: any = {}) {
  const amount = money(r.amount ?? 10);
  return {
    id: "p",
    rider_id: "r",
    status: "PENDIENTE",
    method: "TRANSFERENCIA",
    payment_method: r.method ?? "TRANSFERENCIA",
    currency: null,
    currency_recorded: r.currency ?? null,
    currency_review: false,
    bank_account_last4: null,
    bank_destination_review: false,
    reference_code: null,
    rejection_reason: null,
    idempotency_key: null,
    requested_by_user_id: null,
    processed_by_user_id: null,
    money_review: [],
    orders_count: null,
    period: null,
    period_start: null,
    period_end: null,
    ...r,
    amount,
    total_amount: amount,
    balance_before: money(r.balance_before),
    balance_after: money(r.balance_after),
    requested_at: time(r.requested_at),
    created_at: time(r.requested_at),
    updated_at: time(r.updated_at),
    processed_at: time(r.processed_at),
  };
}
export function payoutEnvelope(
  payload: any,
  url = "/payouts/exact/page",
  options: { role?: string; user?: string; history?: any[] } = {},
) {
  if (
    !payload ||
    !Array.isArray(payload.items) ||
    !Object.prototype.hasOwnProperty.call(payload, "next_cursor")
  )
    return payload;
  const parsed = new URL(url, "https://test.invalid"),
    q = parsed.searchParams;
  const detail = !parsed.pathname.endsWith("/page");
  const role =
    options.role ?? (q.get("audience") === "OWNER" ? "REPARTIDOR" : "GERENTE");
  return {
    version: 1,
    scope: "registered_payout_records",
    units_basis: "recorded_currency_no_conversion",
    balance_basis: "registered_snapshots_not_available_balance",
    snapshot_basis: "single_statement_visibility",
    pagination_basis: "signed_position_live_records",
    available_balance_included: false,
    bank_verified: false,
    wallet_cents_included: false,
    viewer_user_id: options.user ?? "a",
    viewer_role: role,
    effective_rider_id: role === "REPARTIDOR" ? "r" : q.get("rider_id"),
    generated_at: payoutTime,
    content_sha256: "a".repeat(64),
    filters: {
      audience: q.get("audience"),
      rider_id: q.get("rider_id"),
      status: q.get("status"),
      payout_id: detail ? parsed.pathname.split("/").pop() : null,
    },
    limit: Number(q.get("limit") ?? (detail ? 1 : 50)),
    cursor: q.get("cursor"),
    next_cursor: payload.next_cursor,
    total: payload.items.length,
    items: payload.items.map(payoutRecord),
    history: options.history ?? [],
    history_included: detail,
    history_complete: detail,
    history_limit: detail ? 1000 : null,
  };
}
export function payoutModelPage(p: any) {
  return {
    ...p,
    items: p.items.map((r: any) => normalizeExactPayout(payoutRecord(r))),
    read_context: {
      generated_at: payoutTime,
      content_sha256: "a".repeat(64),
      viewer_user_id: "a",
      viewer_role: "GERENTE",
      effective_rider_id: null,
    },
  };
}
export function payoutModelDetail(r: any) {
  const url = "/payouts/exact/" + r.id + "?audience=STAFF";
  const p = normalizeExactPayoutPage(
    payoutEnvelope({ items: [r], next_cursor: null }, url),
    prepareExactPayoutQuery({ limit: 1, audience: "STAFF" }),
    r.id,
  );
  return {
    payout: p.items[0],
    history: p.history,
    read_context: p.read_context,
  };
}
