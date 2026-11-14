import {
  validateOrderQuote,
  validateOrderQuoteContext,
} from "@/lib/order-currency-quote";
import { orderCurrencyQuoteService as service } from "@/services/order-currency-quote.service";
import { api } from "@/lib/api";
import {
  clearStoredTokens,
  storeTokens,
  SessionChangedError,
} from "@/lib/auth-session";
import {
  orderId,
  orderReceipt,
  orderContext,
  quoteCommand,
} from "../../test-utils/order-currency-fixtures";
import { priceOrder } from "@/lib/order-pricing";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
beforeEach(() => {
  jest.clearAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "r" });
});
afterEach(() => clearStoredTokens());

it("validates a receipt against its exact order price and retained BCV rate", () => {
  expect(validateOrderQuote(orderReceipt, orderId)).toEqual(orderReceipt);
  expect(
    validateOrderQuoteContext(
      { ...orderContext, receipts: [orderReceipt] },
      orderId,
    ).receipts,
  ).toHaveLength(1);
});
it.each([
  { amount_usd: "0.51" },
  { amount_ves: "0.74" },
  { quotation_only: false },
  { payment_confirmed: true },
  { scope: "payment" },
  { order_id: quoteCommand.request_key },
  { request_key: null },
  { created_at: "2026-11-15T16:00:00Z" },
  { pricing: { ...orderReceipt.pricing, total: "0.51" } },
  { rate: { ...orderReceipt.rate, ves_per_usd: "2.00000000" } },
])("rejects mismatched receipt data %j", (change) => {
  expect(() =>
    validateOrderQuote({ ...orderReceipt, ...change }, orderId),
  ).toThrow();
});
it("keeps an explicit zero instead of falling back to another order amount", () => {
  const zero = {
    ...orderReceipt,
    pricing: { ...priceOrder([]), revision: 1 },
    amount_usd: "0.00",
    amount_ves: "0.00",
  };
  expect(validateOrderQuote(zero).amount_ves).toBe("0.00");
});
it.each([
  { has_more: true },
  { currency: null },
  { current_rate: { ...orderReceipt.rate, valid_on: "2026-11-13" } },
  { receipts: [orderReceipt, orderReceipt] },
  { pricing: null, receipts: [orderReceipt] },
])("rejects an incomplete or contradictory order context %j", (change) => {
  expect(() =>
    validateOrderQuoteContext({ ...orderContext, ...change }, orderId),
  ).toThrow();
});
it("allows a historical receipt while showing a newer current price revision", () => {
  const context = {
    ...orderContext,
    pricing: { ...orderContext.pricing!, revision: 2 },
    receipts: [orderReceipt],
  };
  expect(
    validateOrderQuoteContext(context, orderId).receipts[0].pricing.revision,
  ).toBe(1);
});
it("sends only the immutable intent fields and validates the echoed request key", async () => {
  jest.mocked(api.post).mockResolvedValue(orderReceipt);
  await service.create(orderId, { ...quoteCommand, amount_usd: "100" } as any);
  expect(api.post).toHaveBeenCalledWith(
    `/currency/orders/${orderId}/quotes`,
    quoteCommand,
  );
  jest
    .mocked(api.post)
    .mockResolvedValue({ ...orderReceipt, request_key: orderId });
  await expect(service.create(orderId, quoteCommand)).rejects.toThrow(
    /no corresponde/,
  );
});
it("rejects malformed identifiers and revisions before an HTTP write", async () => {
  await expect(service.create("bad", quoteCommand)).rejects.toThrow();
  await expect(
    service.create(orderId, { ...quoteCommand, expected_pricing_revision: 0 }),
  ).rejects.toThrow();
  expect(api.post).not.toHaveBeenCalled();
});
it("checks both the requested receipt and its parent order on recovery", async () => {
  jest.mocked(api.get).mockResolvedValue(orderReceipt);
  expect(await service.receipt(orderReceipt.id, orderId)).toEqual(orderReceipt);
  await expect(
    service.receipt(orderReceipt.id, quoteCommand.request_key),
  ).rejects.toThrow();
  jest.mocked(api.get).mockResolvedValue({ ...orderReceipt, id: orderId });
  await expect(service.receipt(orderReceipt.id, orderId)).rejects.toThrow(
    /otra referencia/,
  );
});
it("does not accept a delayed receipt after credentials change", async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  const result = service.create(orderId, quoteCommand).catch((error) => error);
  storeTokens({ access_token: "b", refresh_token: "other" });
  resolve(orderReceipt);
  expect(await result).toBeInstanceOf(SessionChangedError);
});
it("does not send an anonymous context request", async () => {
  clearStoredTokens();
  await expect(service.context(orderId)).rejects.toBeInstanceOf(
    SessionChangedError,
  );
  expect(api.get).not.toHaveBeenCalled();
});
