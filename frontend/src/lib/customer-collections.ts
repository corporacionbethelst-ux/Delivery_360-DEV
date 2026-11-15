import { exactVes } from "@/lib/currency";
import {
  validateOrderPricing,
  type ExactOrderPricing,
} from "@/lib/order-pricing";
import {
  orderQuoteId,
  validateOrderQuote,
  type OrderCurrencyQuote,
} from "@/lib/order-currency-quote";
import { ORDER_STATUSES } from "@/lib/operational-catalog";

export type CollectionMethod = "EFECTIVO" | "TRANSFERENCIA" | "PAGO_MOVIL";
export interface CollectionInput {
  request_key: string;
  expected_pricing_revision: number;
  expected_collection_revision: number;
  amount_usd: string;
  paid_amount: string;
  paid_currency: "USD" | "VES";
  method: CollectionMethod;
  source_key: string;
  reference_key: string;
  received_on: string;
  quote_id: string | null;
  confirmed_received: true;
}
export interface CollectionReviewInput {
  request_key: string;
  expected_collection_revision: number;
  decision: "VERIFICADO" | "RECHAZADO";
  note: string;
  verified_evidence: boolean;
  acknowledge_refund_due: boolean;
}
export interface CollectionReview
  extends Omit<CollectionReviewInput, "expected_collection_revision"> {
  id: string;
  collection_id: string;
  reviewed_by: string;
  reviewed_at: string;
}
export interface CustomerCollection
  extends Omit<
    CollectionInput,
    | "expected_pricing_revision"
    | "expected_collection_revision"
    | "quote_id"
    | "confirmed_received"
  > {
  id: string;
  order_id: string;
  pricing: ExactOrderPricing;
  quote: OrderCurrencyQuote | null;
  declared_by: string;
  created_at: string;
  review: CollectionReview | null;
  status: "PENDIENTE" | "VERIFICADO_MANUALMENTE" | "RECHAZADO";
  scope: "manual_customer_collections";
  bank_verified: false;
}
export interface CollectionContext {
  order_id: string;
  pricing: ExactOrderPricing | null;
  order_status: string | null;
  currency: string | null;
  collection_revision: number;
  price_locked: boolean;
  today: string;
  summary: {
    currency: "USD";
    total_usd: string | null;
    pending_usd: string;
    verified_usd: string;
    due_usd: string | null;
    available_to_declare_usd: string | null;
    refund_due_usd: string;
    refund_due_scope?: "gross_verified_collections";
    state: string;
    declaration_count: number;
    review_count: number;
  };
  collections: CustomerCollection[];
  has_more: boolean;
  ves_quotes: OrderCurrencyQuote[];
  scope: "manual_customer_collections";
  bank_integration_available: false;
}
const invalid = (): never => {
  throw new Error(
    "El registro de cobros contiene datos incoherentes. Actualiza la orden.",
  );
};
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return invalid();
  return v as Record<string, unknown>;
};
export const collectionCents = (value: string) =>
  BigInt(value.replace(".", ""));
export function collectionMoney(value: unknown, digits = 8): string {
  if (
    typeof value !== "string" ||
    !new RegExp(`^(?:0|[1-9]\\d{0,${digits - 1}})\\.\\d{2}$`).test(value)
  )
    return invalid();
  return value;
}
export function collectionKey(v: string): string {
  const result = v.trim().replace(/ +/g, " ").toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9 ._/#:\-]*$/.test(result)) return invalid();
  return result;
}
const count = (v: unknown): number => {
  if (
    typeof v !== "number" ||
    !Number.isSafeInteger(v) ||
    v < 0 ||
    v > 2147483647
  )
    return invalid();
  return v;
};
const day = (v: unknown): string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(v) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v
  )
    return invalid();
  return v;
};
const timestamp = (v: unknown): string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v) ||
    !Number.isFinite(Date.parse(v))
  )
    return invalid();
  return v;
};
const caracas = (v: string) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Caracas",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(v));
  return ["year", "month", "day"]
    .map((k) => parts.find((p) => p.type === k)!.value)
    .join("-");
};
export function validateCollection(
  value: unknown,
  orderId: string,
): CustomerCollection {
  const r = object(value),
    pricing = validateOrderPricing(r.pricing),
    quote = r.quote === null ? null : validateOrderQuote(r.quote, orderId);
  for (const key of ["id", "request_key", "order_id", "declared_by"])
    orderQuoteId(r[key]);
  const usd = collectionMoney(r.amount_usd),
    paid = collectionMoney(r.paid_amount, 21),
    received = day(r.received_on),
    created = timestamp(r.created_at);
  if (
    r.order_id !== orderId ||
    r.scope !== "manual_customer_collections" ||
    r.bank_verified !== false ||
    collectionCents(usd) <= BigInt(0) ||
    collectionCents(usd) > collectionCents(pricing.total) ||
    collectionCents(paid) <= BigInt(0) ||
    !["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"].includes(r.method as string) ||
    !["USD", "VES"].includes(r.paid_currency as string) ||
    (r.method === "PAGO_MOVIL" && r.paid_currency !== "VES") ||
    caracas(created) !== received
  )
    return invalid();
  for (const [key, limit] of [
    ["source_key", 80],
    ["reference_key", 120],
  ] as const)
    if (
      typeof r[key] !== "string" ||
      (r[key] as string).length > limit ||
      collectionKey(r[key] as string) !== r[key]
    )
      return invalid();
  if (
    r.paid_currency === "USD"
      ? quote !== null || paid !== usd
      : !quote ||
        quote.pricing.revision !== pricing.revision ||
        JSON.stringify(quote.pricing) !== JSON.stringify(pricing) ||
        quote.rate.valid_on !== received ||
        exactVes(usd, quote.rate.ves_per_usd) !== paid ||
        Date.parse(quote.created_at) > Date.parse(created)
  )
    return invalid();
  let review: CollectionReview | null = null;
  if (r.review !== null) {
    const v = object(r.review);
    for (const key of ["id", "request_key", "collection_id", "reviewed_by"])
      orderQuoteId(v[key]);
    if (
      v.collection_id !== r.id ||
      v.reviewed_by === r.declared_by ||
      !["VERIFICADO", "RECHAZADO"].includes(v.decision as string) ||
      v.verified_evidence !== (v.decision === "VERIFICADO") ||
      typeof v.acknowledge_refund_due !== "boolean" ||
      typeof v.note !== "string" ||
      v.note.trim() !== v.note ||
      v.note.length < 10 ||
      v.note.length > 500 ||
      /[\x00-\x1f\x7f]/.test(v.note) ||
      Date.parse(timestamp(v.reviewed_at)) < Date.parse(created)
    )
      return invalid();
    review = v as unknown as CollectionReview;
  }
  const status = review
    ? review.decision === "VERIFICADO"
      ? "VERIFICADO_MANUALMENTE"
      : "RECHAZADO"
    : "PENDIENTE";
  if (r.status !== status) return invalid();
  return { ...r, pricing, quote, review } as unknown as CustomerCollection;
}
export function validateCollectionContext(
  value: unknown,
  orderId: string,
): CollectionContext {
  const r = object(value),
    s = object(r.summary),
    pricing = r.pricing === null ? null : validateOrderPricing(r.pricing);
  const today = day(r.today),
    revision = count(r.collection_revision),
    declarations = count(s.declaration_count),
    reviews = count(s.review_count);
  if (
    orderQuoteId(r.order_id) !== orderId ||
    r.scope !== "manual_customer_collections" ||
    r.bank_integration_available !== false ||
    typeof r.price_locked !== "boolean" ||
    typeof r.has_more !== "boolean" ||
    !Array.isArray(r.collections) ||
    r.collections.length > 20 ||
    !Array.isArray(r.ves_quotes) ||
    r.ves_quotes.length > 10 ||
    s.currency !== "USD" ||
    (s.refund_due_scope !== undefined &&
      s.refund_due_scope !== "gross_verified_collections") ||
    (r.order_status !== null &&
      !ORDER_STATUSES.includes(r.order_status as never)) ||
    (r.currency !== null && typeof r.currency !== "string") ||
    reviews > declarations ||
    revision !== declarations + reviews
  )
    return invalid();
  const pending = collectionCents(collectionMoney(s.pending_usd)),
    verified = collectionCents(collectionMoney(s.verified_usd)),
    refund = collectionCents(collectionMoney(s.refund_due_usd));
  const terminal = ["CANCELADO", "FALLIDO"].includes(r.order_status as string);
  const total =
    s.total_usd === null ? null : collectionCents(collectionMoney(s.total_usd));
  if (
    pricing
      ? r.currency !== "USD" ||
        s.total_usd !== pricing.total ||
        total === null ||
        pending + verified > total ||
        collectionCents(collectionMoney(s.due_usd)) !==
          (terminal ? BigInt(0) : total - verified) ||
        collectionCents(collectionMoney(s.available_to_declare_usd)) !==
          (terminal ? BigInt(0) : total - pending - verified)
      : total !== null ||
        s.due_usd !== null ||
        s.available_to_declare_usd !== null ||
        declarations !== 0
  )
    return invalid();
  if (
    refund !== (terminal ? verified : BigInt(0)) ||
    r.price_locked !== pending + verified > BigInt(0)
  )
    return invalid();
  const state = !pricing
    ? "REQUIERE_REVISION"
    : terminal && verified > BigInt(0)
      ? "DEVOLUCION_PENDIENTE"
      : total !== null && total > BigInt(0) && verified === total
        ? "COMPLETO"
        : verified > BigInt(0)
          ? "PARCIAL"
          : pending > BigInt(0)
            ? "EN_REVISION"
            : "SIN_COBROS";
  if (s.state !== state) return invalid();
  const collections = r.collections.map((v) => validateCollection(v, orderId)),
    ids = new Set<string>();
  if (
    collections.length > declarations ||
    (r.has_more && collections.length !== 20)
  )
    return invalid();
  for (const row of collections) {
    if (
      ids.has(row.id) ||
      !pricing ||
      row.pricing.revision > pricing.revision ||
      row.received_on > today
    )
      return invalid();
    ids.add(row.id);
  }
  const ves_quotes = r.ves_quotes.map((v) => validateOrderQuote(v, orderId));
  const quoteIds = new Set<string>();
  for (const quote of ves_quotes) {
    if (
      quoteIds.has(quote.id) ||
      !pricing ||
      quote.pricing.revision !== pricing.revision ||
      quote.rate.valid_on !== today
    )
      return invalid();
    quoteIds.add(quote.id);
  }
  return {
    ...r,
    pricing,
    collections,
    ves_quotes,
  } as unknown as CollectionContext;
}
