import { record } from "@/lib/operational-catalog";
import { cashCents } from "@/lib/customer-cashbook";
import {
  auditId,
  AUDIT_PAGE_SIZE,
  boundedAuditPage,
} from "@/lib/rider-audit-contract";
import {
  exactRecordTime,
  type TransactionReadContext,
  type ExactTransaction,
} from "@/lib/transaction-exact";
import { DeliveryStatus } from "@/types/delivery";
const fail = (): never => {
  throw new Error("No se pudo confirmar la página exacta de auditoría.");
};
const text = (v: unknown): string | null =>
  v === null ? null : typeof v === "string" ? v : fail();
const time = (v: unknown) => (v === null ? null : exactRecordTime(v));
const orderStatuses = [
  "PENDIENTE",
  "ASIGNADO",
  "EN_RECOLECCION",
  "RECOLECTADO",
  "EN_RUTA",
  "ENTREGADO",
  "FALLIDO",
  "CANCELADO",
];
function base(value: unknown, riderId: string, delivery = false) {
  const r = record(value),
    id = auditId(r.id);
  if (
    auditId(r.rider_id) !== riderId ||
    (r.status !== null &&
      !(delivery ? Object.values(DeliveryStatus) : orderStatuses).includes(
        r.status as never,
      ))
  )
    return fail();
  return {
    id,
    rider_id: riderId,
    external_id: text(r.external_id),
    customer_name: text(r.customer_name),
    status: text(r.status),
    created_at: time(r.created_at),
    updated_at: time(r.updated_at),
  };
}
function unit(r: Record<string, unknown>) {
  const original = text(r.currency_recorded);
  if (original !== null && original.length > 3) return fail();
  const currency =
    original !== null && /^[A-Z]{3}$/.test(original) ? original : null;
  if (
    r.currency !== currency ||
    r.currency_review !== (original !== null && currency === null)
  )
    return fail();
  return {
    currency,
    currency_recorded: original,
    currency_review: r.currency_review as boolean,
  };
}
function normalizeOrder(value: unknown, riderId: string) {
  const r = record(value),
    b = base(r, riderId),
    u = unit(r);
  if (
    r.price_review !== null &&
    !["PRECIO_HISTORICO_NO_EXACTO", "PRECIO_POR_REVISAR"].includes(
      String(r.price_review),
    )
  )
    return fail();
  if (
    r.pricing_revision !== null &&
    (!Number.isSafeInteger(r.pricing_revision) ||
      Number(r.pricing_revision) > 2147483647)
  )
    return fail();
  if (r.amount === null) {
    if (r.price_review === null) return fail();
  } else {
    const cents = cashCents(r.amount);
    if (
      cents > BigInt("9999999999") ||
      r.price_review !== null ||
      u.currency !== "USD" ||
      !Number.isSafeInteger(r.pricing_revision) ||
      Number(r.pricing_revision) < 1
    )
      return fail();
  }
  return {
    ...b,
    ...u,
    amount: r.amount as string | null,
    price_review: r.price_review as string | null,
    pricing_revision: r.pricing_revision as number | null,
  };
}
function normalizeDelivery(value: unknown, riderId: string) {
  const r = record(value),
    b = base(r, riderId, true),
    u = unit(r),
    order_id = auditId(r.order_id);
  if (
    typeof r.fallback !== "boolean" ||
    r.currency_basis !== "not_recorded_on_delivery" ||
    u.currency_recorded !== null ||
    u.currency !== null ||
    u.currency_review ||
    !Array.isArray(r.money_review)
  )
    return fail();
  if (r.fallback ? b.id !== `order-${order_id}` : b.id.startsWith("order-"))
    return fail();
  if (r.money_review.length > 1) return fail();
  const money_review = r.money_review.map((v) => {
    const e = record(v);
    if (e.field !== "locked_bonus_amount" || e.reason !== "IMPORTE_NO_VALIDO")
      return fail();
    return { field: "locked_bonus_amount", reason: "IMPORTE_NO_VALIDO" };
  });
  if (r.locked_bonus_amount !== null) {
    const c = cashCents(r.locked_bonus_amount);
    if (c > BigInt("9999999999") || money_review.length || r.fallback)
      return fail();
  } else if (r.fallback && money_review.length) return fail();
  return {
    ...b,
    ...u,
    order_id,
    fallback: r.fallback as boolean,
    locked_bonus_amount: r.locked_bonus_amount as string | null,
    money_review,
  };
}
export type ExactAuditOrder = ReturnType<typeof normalizeOrder>;
export type ExactAuditDelivery = ReturnType<typeof normalizeDelivery>;
function envelope(
  value: unknown,
  riderId: string,
  kind: "orders" | "deliveries",
  offset: number,
) {
  const p = record(value);
  if (
    p.version !== 1 ||
    p.scope !== "rider_audit_registered_records" ||
    p.kind !== kind ||
    p.rider_id !== riderId ||
    p.limit !== 51 ||
    p.offset !== offset ||
    p.units_basis !== "recorded_currency_no_conversion" ||
    p.snapshot_basis !== "single_statement_visibility" ||
    p.amount_basis !==
      (kind === "orders"
        ? "exact_order_price_not_rider_earnings"
        : "locked_delivery_bonus_not_ledger") ||
    p.pagination_basis !== "offset_live_records_real_deliveries_only" ||
    p.available_balance_included !== false ||
    p.bank_verified !== false ||
    p.wallet_cents_included !== false ||
    !["GERENTE", "SUPERADMIN"].includes(String(p.viewer_role))
  )
    return fail();
  if (
    typeof p.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(p.content_sha256) ||
    !Array.isArray(p.items) ||
    p.items.length > 51 ||
    p.total !== p.items.length ||
    !Array.isArray(p.fallback) ||
    p.fallback.length > 50 ||
    p.fallback_limit !== 50 ||
    typeof p.fallback_has_more !== "boolean"
  )
    return fail();
  if (
    ((kind === "orders" || offset > 0) &&
      (p.fallback.length || p.fallback_has_more)) ||
    (p.fallback_has_more && p.fallback.length !== 50)
  )
    return fail();
  const read_context: TransactionReadContext = {
    generated_at: exactRecordTime(p.generated_at),
    content_sha256: p.content_sha256,
    viewer_user_id: auditId(p.viewer_user_id),
    viewer_role: String(p.viewer_role),
  };
  return { p, read_context };
}
export function normalizeExactAuditOrders(
  value: unknown,
  riderId: string,
  offset: number,
) {
  const { p, read_context } = envelope(value, riderId, "orders", offset);
  return {
    ...boundedAuditPage(p.items, offset, (r) => normalizeOrder(r, riderId)),
    read_context,
  };
}
export function normalizeExactAuditDeliveries(
  value: unknown,
  riderId: string,
  offset: number,
) {
  const { p, read_context } = envelope(value, riderId, "deliveries", offset);
  const rows = (p.items as unknown[]).map((r) => normalizeDelivery(r, riderId));
  if (
    rows.some((r) => r.fallback) ||
    new Set(rows.map((r) => r.order_id)).size !== rows.length
  )
    return fail();
  const fallback = (p.fallback as unknown[]).map((r) =>
    normalizeDelivery(r, riderId),
  );
  if (
    fallback.some(
      (r) => !r.fallback || rows.some((d) => d.order_id === r.order_id),
    ) ||
    new Set(fallback.map((r) => r.id)).size !== fallback.length
  )
    return fail();
  return {
    ...boundedAuditPage(rows, offset, (r) => r as ExactAuditDelivery),
    fallback,
    fallback_has_more: p.fallback_has_more as boolean,
    read_context,
  };
}
export function exactAuditTableCsv(
  kind: "orders" | "deliveries" | "transactions" | "support_orders",
  rows: (ExactAuditOrder | ExactAuditDelivery | ExactTransaction)[],
  read: TransactionReadContext,
  riderId: string,
  offset: number,
) {
  return rows.map((r) => ({
    clase_registro: kind,
    id: r.id,
    rider_id: riderId,
    order_id: "order_id" in r ? r.order_id : "",
    importe_registrado: "amount" in r ? r.amount : null,
    bono_conservado: "locked_bonus_amount" in r ? r.locked_bonus_amount : null,
    moneda: r.currency ?? "",
    moneda_original: r.currency_recorded ?? "",
    moneda_por_revisar: r.currency_review,
    precio_por_revisar: "price_review" in r ? r.price_review : "",
    importes_por_revisar:
      "money_review" in r ? JSON.stringify(r.money_review) : "",
    estado: r.status ?? "",
    creacion_utc: r.created_at ?? "",
    saldo_anterior_registrado: "balance_before" in r ? r.balance_before : null,
    saldo_posterior_registrado: "balance_after" in r ? r.balance_after : null,
    revision_precio: "pricing_revision" in r ? r.pricing_revision : null,
    corte_utc: read.generated_at,
    huella_sha256: read.content_sha256,
    consultado_por: read.viewer_user_id,
    rol_consulta: read.viewer_role,
    desplazamiento: offset,
    pagina: offset / AUDIT_PAGE_SIZE + 1,
    alcance:
      "Solo filas visibles de las páginas confirmadas; lecturas independientes",
    saldo_disponible_incluido: false,
    verificado_por_banco: false,
  }));
}
