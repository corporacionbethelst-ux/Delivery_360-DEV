import { exactVes, validateRate, type BcvRate } from "@/lib/currency";
import {
  validateOrderPricing,
  type ExactOrderPricing,
} from "@/lib/order-pricing";
import { ORDER_STATUSES } from "@/lib/operational-catalog";

export interface OrderQuoteInput {
  request_key: string;
  rate_id: string;
  expected_pricing_revision: number;
}
export interface OrderCurrencyQuote {
  id: string;
  request_key: string;
  order_id: string;
  order_external_id: string | null;
  pricing: ExactOrderPricing;
  amount_usd: string;
  amount_ves: string;
  rate: BcvRate;
  created_at: string;
  created_by: string;
  country: "VE";
  base_currency: "USD";
  quote_currency: "VES";
  scope: "order_quotation_only";
  quotation_only: true;
  payment_confirmed: false;
}
export interface OrderQuoteContext {
  order_id: string;
  order_external_id: string | null;
  currency: string | null;
  status: string;
  pricing: ExactOrderPricing | null;
  today: string;
  current_rate: BcvRate | null;
  receipts: OrderCurrencyQuote[];
  has_more: boolean;
  scope: "order_quotation_only";
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const invalid = (): never => {
  throw new Error(
    "El comprobante USD/VES no corresponde a esta orden o contiene datos incoherentes.",
  );
};
export function orderQuoteId(value: unknown): string {
  if (typeof value !== "string" || !uuid.test(value)) return invalid();
  return value;
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}
function external(value: unknown): string | null {
  if (value !== null && (typeof value !== "string" || value.length > 100))
    return invalid();
  return value as string | null;
}
function day(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString().slice(0, 10) !== value
  )
    return invalid();
  return value;
}
function caracasDay(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?Z$/.test(
      value,
    ) ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString().slice(0, 10) !== value.slice(0, 10)
  )
    return invalid();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Caracas",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  return ["year", "month", "day"]
    .map((key) => parts.find((part) => part.type === key)!.value)
    .join("-");
}
export function validateOrderQuote(
  value: unknown,
  expectedOrder?: string,
): OrderCurrencyQuote {
  const r = object(value),
    pricing = validateOrderPricing(r.pricing),
    rate = validateRate(r.rate);
  orderQuoteId(r.id);
  orderQuoteId(r.request_key);
  orderQuoteId(r.created_by);
  const order_id = orderQuoteId(r.order_id);
  if (
    (expectedOrder !== undefined && order_id !== expectedOrder) ||
    r.scope !== "order_quotation_only" ||
    r.country !== "VE" ||
    r.base_currency !== "USD" ||
    r.quote_currency !== "VES" ||
    r.quotation_only !== true ||
    r.payment_confirmed !== false ||
    r.amount_usd !== pricing.total ||
    exactVes(pricing.total, rate.ves_per_usd) !== r.amount_ves ||
    caracasDay(r.created_at) !== rate.valid_on ||
    Date.parse(rate.recorded_at) > Date.parse(r.created_at as string)
  )
    return invalid();
  external(r.order_external_id);
  return { ...r, pricing, rate } as unknown as OrderCurrencyQuote;
}
export function validateOrderQuoteContext(
  value: unknown,
  expectedOrder: string,
): OrderQuoteContext {
  const r = object(value);
  if (
    orderQuoteId(r.order_id) !== expectedOrder ||
    r.scope !== "order_quotation_only" ||
    !ORDER_STATUSES.includes(r.status as never) ||
    (r.currency !== null && r.currency !== "USD") ||
    !Array.isArray(r.receipts) ||
    r.receipts.length > 10 ||
    typeof r.has_more !== "boolean" ||
    (r.has_more && r.receipts.length !== 10)
  )
    return invalid();
  const today = day(r.today),
    pricing = r.pricing === null ? null : validateOrderPricing(r.pricing),
    rate = r.current_rate === null ? null : validateRate(r.current_rate);
  external(r.order_external_id);
  if ((pricing && r.currency !== "USD") || (rate && rate.valid_on !== today))
    return invalid();
  const receipts = r.receipts.map((row) =>
      validateOrderQuote(row, expectedOrder),
    ),
    ids = new Set<string>();
  for (let i = 0; i < receipts.length; i++) {
    const row = receipts[i];
    if (
      ids.has(row.id) ||
      !pricing ||
      row.pricing.revision > pricing.revision ||
      row.rate.valid_on > today ||
      (i > 0 &&
        Date.parse(receipts[i - 1].created_at) < Date.parse(row.created_at))
    )
      return invalid();
    ids.add(row.id);
  }
  return {
    ...r,
    today,
    pricing,
    current_rate: rate,
    receipts,
  } as unknown as OrderQuoteContext;
}
