// Synthetic values only: production exact amounts always arrive as decimal strings.
export function auditExactFixtureMoney(changes: Record<string, unknown> = {}) {
  const credit = Number(changes.total_earned ?? 25),
    pending = Number(changes.pending_payouts ?? 5);
  return {
    credit_usd: credit.toFixed(2),
    debit_usd: "0.00",
    adjustment_usd: "0.00",
    net_change_usd: credit.toFixed(2),
    pending_usd: pending.toFixed(2),
    ledger_rows: 1,
    ledger_included: 1,
    payout_rows: 1,
    payout_included: 1,
    ledger_exclusions: [
      "FECHA_NO_REGISTRADA",
      "MONEDA_NO_VERIFICADA",
      "FECHA_FUTURA",
      "ESTADO_NO_PROCESADO",
      "TIPO_NO_ADMITIDO",
    ].map((reason) => ({ reason, count: 0 })),
    payout_exclusions: [
      "FECHA_NO_REGISTRADA",
      "MONEDA_NO_VERIFICADA",
      "FECHA_FUTURA",
      "ESTADO_NO_PENDIENTE",
    ].map((reason) => ({ reason, count: 0 })),
  };
}
export function exactAuditEnvelope(
  items: unknown[],
  params = new URLSearchParams("limit=51&offset=0"),
) {
  return {
    version: 1,
    scope: "operational_rider_audit_usd",
    currency: "USD",
    viewer_user_id: "a",
    viewer_role: "GERENTE",
    generated_at: "2026-11-15T16:00:00.123456Z",
    snapshot_basis: "single_statement_visibility",
    ledger_basis: "processed_registered_movements",
    payout_basis: "current_pending_requests",
    available_balance_included: false,
    bank_verified: false,
    wallet_cents_included: false,
    content_sha256: "a".repeat(64),
    filters: {
      status: params.get("status_filter"),
      online: params.has("is_online")
        ? params.get("is_online") === "true"
        : null,
      rider_id: params.get("rider_id"),
    },
    limit: Number(params.get("limit") ?? 51),
    offset: Number(params.get("offset") ?? 0),
    total: items.length,
    items,
  };
}
import { transactionResponse, exactTransactionReply } from "./transactions";
export const auditSummaryResponse = (
  id = "rider-1",
  changes: Record<string, unknown> = {},
) => ({
  money: auditExactFixtureMoney(changes),
  rider_id: id,
  user_id: `user-${id}`,
  full_name: "José Rider",
  email: "rider@example.test",
  status: "ACTIVO",
  is_online: false,
  orders_assigned: 9,
  orders_delivered: 3,
  orders_active: 4,
  deliveries_total: 8,
  deliveries_completed: 3,
  deliveries_failed: 1,
  deliveries_in_progress: 2,
  sla_compliant: 4,
  sla_compliance_rate: 50,
  total_earned: 25,
  pending_payouts: 5,
  available_to_payout: 20,
  last_lat: 0,
  last_lng: 0,
  last_location_at: "2026-11-07T12:00:00",
  ...changes,
});
export const auditOrderResponse = (
  id = "order-1",
  rider = "rider-1",
  changes: Record<string, unknown> = {},
) => ({
  id,
  external_id: "EXT-1",
  assigned_rider_id: rider,
  rider_id: rider,
  status: "ASIGNADO",
  customer_name: "Ana",
  total: 0,
  created_at: "2026-11-07T12:00:00",
  ...changes,
});
export const auditDeliveryResponse = (
  id = "delivery-1",
  rider = "rider-1",
  changes: Record<string, unknown> = {},
) => ({
  id,
  order_id: `order-for-${id}`,
  rider_id: rider,
  status: "COMPLETADA",
  customer_name: "Ana",
  locked_bonus_amount: 0,
  updated_at: "2026-11-07T12:00:00",
  ...changes,
});
export const auditTransactionResponse = (id = "tx-1", rider = "rider-1") =>
  transactionResponse(id, { rider_id: rider });
export const auditSummaryPage = (
  items = [auditSummaryResponse()],
  offset = 0,
) => ({ items, limit: 100, offset, total: items.length });
export const auditDeliveryPage = (
  items = [auditDeliveryResponse()],
  offset = 0,
  total = items.length,
) => ({ items, limit: 51, offset, total });
export function auditHttpResponse(
  url: string,
  total = 73,
  riderId = "rider-1",
): unknown {
  const parsed = new URL(url, "https://test.invalid"),
    offset = Number(parsed.searchParams.get("offset") ?? 0);
  const legacy = auditFixtureLegacyUrl(url);
  if (legacy !== url)
    return auditRecordsReply(auditHttpResponse(legacy, total, riderId), url);
  const indexes = Array.from(
    { length: Math.max(0, Math.min(51, total - offset)) },
    (_, i) => i + offset,
  );
  if (parsed.pathname === "/riders/audit/summary/exact")
    return exactAuditEnvelope(
      [auditSummaryResponse(riderId)],
      parsed.searchParams,
    );
  if (parsed.pathname === "/riders/audit/summary")
    return auditSummaryPage([auditSummaryResponse(riderId)]);
  if (parsed.pathname === "/orders")
    return indexes.map((i) => auditOrderResponse(`o-${i}`, riderId));
  if (parsed.pathname === "/deliveries")
    return auditDeliveryPage(
      indexes.map((i) => auditDeliveryResponse(`d-${i}`, riderId)),
      offset,
      total,
    );
  if (parsed.pathname === "/financial/transactions")
    return indexes.map((i) => auditTransactionResponse(`tx-${i}`, riderId));
  throw new Error(`Unexpected HTTP path: ${parsed.pathname}`);
}

// Synthetic legacy-shaped test inputs are adapted here; production never converts floats.
export function auditFixtureLegacyUrl(url: string) {
  const p = new URL(url, "https://test.invalid"),
    q = p.searchParams;
  if (p.pathname === "/riders/audit/records/exact/v2")
    return `/${q.get("kind")}?rider_id=${q.get("rider_id")}&limit=${q.get("limit")}&offset=${q.get("offset")}${q.get("kind") === "deliveries" ? "&include_total=true" : ""}`;
  if (p.pathname === "/financial/transactions/exact/page")
    return `/financial/transactions?${q}`;
  return url;
}
export function auditRecordsReply(value: unknown, url: string) {
  const p = new URL(url, "https://test.invalid"),
    q = p.searchParams;
  if (value && typeof value === "object" && "scope" in value) return value;
  if (p.pathname === "/financial/transactions/exact/page")
    return exactTransactionReply(value, url);
  if (p.pathname !== "/riders/audit/records/exact/v2") return value;
  const kind = q.get("kind"),
    offset = Number(q.get("offset") ?? 0),
    delivery = kind === "deliveries";
  if (delivery && (!value || typeof value !== "object" || !("items" in value)))
    return value;
  const input = delivery ? (value as { items: unknown[] }).items : value;
  if (!Array.isArray(input)) return value;
  const money = (v: unknown) =>
    v == null ? null : typeof v === "string" ? v : Number(v).toFixed(2);
  const time = (v: unknown) =>
    v == null
      ? null
      : new Date(typeof v === "string" && v.length === 19 ? v + "Z" : String(v))
          .toISOString()
          .replace("Z", "000Z");
  const rows = input.map((v) => {
    const r = v as Record<string, unknown>,
      fallback = delivery && String(r.id).startsWith("order-");
    const currency = delivery
      ? (r.locked_bonus_currency ?? null)
      : (r.currency ?? null);
    const raw = {
      ...r,
      rider_id: r.rider_id ?? r.assigned_rider_id,
      external_id: r.external_id ?? null,
      customer_name: r.customer_name ?? null,
      status: r.status ?? null,
      created_at: time(r.created_at),
      updated_at: time(r.updated_at),
      currency,
      currency_recorded: currency,
      currency_review: false,
    };
    return delivery
      ? {
          ...raw,
          locked_bonus_amount: money(r.locked_bonus_amount),
          money_review: [],
          currency_basis: "locked_bonus_snapshot",
          fallback,
        }
      : {
          ...raw,
          amount: money(r.total ?? r.total_amount),
          pricing_revision: 1,
          price_review:
            r.total == null && r.total_amount == null
              ? "PRECIO_HISTORICO_NO_EXACTO"
              : null,
          currency:
            r.total != null || r.total_amount != null ? "USD" : currency,
          currency_recorded:
            r.total != null || r.total_amount != null ? "USD" : currency,
        };
  });
  const items = rows.filter((r) => !("fallback" in r) || !r.fallback),
    fallback = rows.filter((r) => "fallback" in r && r.fallback);
  return {
    version: 2,
    scope: "rider_audit_registered_records",
    kind,
    units_basis: "recorded_currency_no_conversion",
    snapshot_basis: "single_statement_visibility",
    amount_basis: delivery
      ? "locked_delivery_bonus_not_ledger"
      : "exact_order_price_not_rider_earnings",
    pagination_basis: "offset_live_records_real_deliveries_only",
    available_balance_included: false,
    bank_verified: false,
    wallet_cents_included: false,
    viewer_user_id: "a",
    viewer_role: "GERENTE",
    rider_id: q.get("rider_id"),
    limit: Number(q.get("limit") ?? 51),
    offset,
    generated_at: "2026-11-16T12:00:00.000000Z",
    content_sha256: "a".repeat(64),
    total: items.length,
    items,
    fallback,
    fallback_limit: 50,
    fallback_has_more: false,
  };
}
