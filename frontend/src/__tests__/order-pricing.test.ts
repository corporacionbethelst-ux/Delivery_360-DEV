import {
  checkedOrder,
  moneyInput,
  priceOrder,
  validateOrderPricing,
  validateExactAggregate,
} from "@/lib/order-pricing";
import { resolveOrderCollectAmount } from "@/lib/order-amount";
import { orderService } from "@/services/order.service";
import { api } from "@/lib/api";
import {
  clearStoredTokens,
  storeTokens,
  SessionChangedError,
} from "@/lib/auth-session";

jest.mock("@/lib/api", () => ({ api: { post: jest.fn(), patch: jest.fn() } }));
const items = [{ product_name: "A", quantity: "3", unit_price: "0.10" }];
const price = { ...priceOrder(items, "0.20"), revision: 1 };
const response = {
  id: "one",
  status: "PENDIENTE",
  currency: "USD",
  subtotal: 0.3,
  delivery_fee: 0.2,
  total: 0.5,
  items: [],
  pricing: price,
};
const input = {
  delivery_address: "B",
  pickup_address: "A",
  items,
  delivery_fee: "0.20",
  total: "0.50",
};

beforeEach(() => {
  jest.clearAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "r" });
});
afterEach(() => clearStoredTokens());

it("calculates decimal prices with integer cents, half-up lines and no draft mutation", () => {
  expect(price.total).toBe("0.50");
  expect(price.items[0].subtotal).toBe("0.30");
  expect(items[0]).not.toHaveProperty("subtotal");
  expect(priceOrder([{ quantity: "0.5", unit_price: "0.01" }]).total).toBe(
    "0.01",
  );
  expect(priceOrder([{ quantity: "1.235", unit_price: "2.00" }]).total).toBe(
    "2.47",
  );
  expect(moneyInput("0,20")).toBe("0.20");
});

it.each([
  true,
  null,
  "",
  "NaN",
  "Infinity",
  "1e2",
  "0.001",
  "-1",
  "100000000",
  0.30000000000000004,
])("rejects malformed money %j", (value) => {
  expect(() => moneyInput(value)).toThrow();
});

it.each([
  [{ quantity: "0", unit_price: "1.00" }],
  [{ quantity: "0.0001", unit_price: "1.00" }],
  [{ quantity: "1", unit_price: "1.00", subtotal: "0.00" }],
  Array(201).fill({ subtotal: "0.00" }),
])("rejects invalid quantities and inconsistent or oversized lines", (rows) => {
  expect(() => priceOrder(rows)).toThrow();
});

it("preserves explicit exact zero despite an older positive fallback", () => {
  const zero = { ...priceOrder([], "0.00"), revision: 1 };
  expect(resolveOrderCollectAmount({ pricing: zero, total: 100 })).toBe(0);
  expect(validateOrderPricing(zero).total).toBe("0.00");
});

it.each([
  { total: "0.51" },
  { revision: 0 },
  { revision: 2147483648 },
  { currency: "VES" },
  { subtotal: 0.3 },
  { items: [{ quantity: "3", unit_price: "0.10", subtotal: "0.31" }] },
])("rejects a malformed exact response %j", (change) => {
  expect(() => validateOrderPricing({ ...price, ...change })).toThrow();
});

it("checks exact prices against compatibility totals and keeps historical responses readable", () => {
  expect(checkedOrder(response).pricing?.total).toBe("0.50");
  expect(() => checkedOrder({ ...response, total: 9 })).toThrow();
  expect(() => checkedOrder({ ...response, currency: null })).toThrow();
  expect(checkedOrder({ currency: null, total: 0.30000000000000004 })).toEqual({
    currency: null,
    total: 0.30000000000000004,
  });
});

it("validates exact report sums without converting large aggregates to Number", () => {
  const aggregate = {
    scope: "exact_usd_only",
    currency: "USD",
    order_count: 200000000,
    legacy_order_count: 1,
    subtotal: "999999999999999999.99",
    delivery_fee: "0.01",
    total: "1000000000000000000.00",
  };
  expect(validateExactAggregate(aggregate).total).toBe(aggregate.total);
  expect(() =>
    validateExactAggregate({ ...aggregate, total: "1000000000000000000.01" }),
  ).toThrow();
});

it("sends canonical strings and requires confirmed exact amounts on create", async () => {
  jest.mocked(api.post).mockResolvedValue(response);
  expect((await orderService.create(input)).pricing?.total).toBe("0.50");
  expect(api.post).toHaveBeenCalledWith(
    "/orders",
    expect.objectContaining({
      currency: "USD",
      delivery_fee: "0.20",
      total: "0.50",
      items: price.items,
    }),
  );
  jest.mocked(api.post).mockResolvedValue({ ...response, pricing: null });
  await expect(orderService.create(input)).rejects.toThrow(/exacto/);
});

it("rejects malformed submissions before any HTTP write", async () => {
  await expect(
    orderService.create({ ...input, delivery_fee: "0.001" }),
  ).rejects.toThrow();
  expect(api.post).not.toHaveBeenCalled();
});

it("passes the loaded revision and rejects a mismatched revision confirmation", async () => {
  jest
    .mocked(api.patch)
    .mockResolvedValue({ ...response, pricing: { ...price, revision: 2 } });
  await orderService.update("one", { ...input, expected_pricing_revision: 1 });
  expect(api.patch).toHaveBeenCalledWith(
    "/orders/one",
    expect.objectContaining({ expected_pricing_revision: 1 }),
  );
  jest
    .mocked(api.patch)
    .mockResolvedValue({ ...response, pricing: { ...price, revision: 9 } });
  await expect(
    orderService.update("one", { ...input, expected_pricing_revision: 1 }),
  ).rejects.toThrow(/revisión/);
});

it("does not accept delayed exact write results after logout", async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  const result = orderService.create(input).catch((error) => error);
  clearStoredTokens();
  resolve(response);
  expect(await result).toBeInstanceOf(SessionChangedError);
});
