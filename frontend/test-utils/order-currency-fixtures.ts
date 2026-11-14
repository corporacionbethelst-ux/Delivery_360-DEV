import { rate, quoteId, actorId, nextId } from "./currency-fixtures";
import { priceOrder } from "@/lib/order-pricing";
import type {
  OrderCurrencyQuote,
  OrderQuoteContext,
} from "@/lib/order-currency-quote";
export const orderId = "55555555-5555-4555-8555-555555555555";
export const pricing = {
  ...priceOrder(
    [{ product_name: "Decimal", quantity: "3", unit_price: "0.10" }],
    "0.20",
  ),
  revision: 1,
};
export const orderReceipt: OrderCurrencyQuote = {
  id: quoteId,
  request_key: nextId,
  order_id: orderId,
  order_external_id: "ORDER93",
  pricing,
  amount_usd: "0.50",
  amount_ves: "0.75",
  rate,
  created_at: "2026-11-14T16:01:00Z",
  created_by: actorId,
  country: "VE",
  base_currency: "USD",
  quote_currency: "VES",
  scope: "order_quotation_only",
  quotation_only: true,
  payment_confirmed: false,
};
export const orderContext: OrderQuoteContext = {
  order_id: orderId,
  order_external_id: "ORDER93",
  currency: "USD",
  status: "PENDIENTE",
  pricing,
  today: "2026-11-14",
  current_rate: rate,
  receipts: [],
  has_more: false,
  scope: "order_quotation_only",
};
export const quoteCommand = {
  request_key: nextId,
  rate_id: rate.id,
  expected_pricing_revision: 1,
};
