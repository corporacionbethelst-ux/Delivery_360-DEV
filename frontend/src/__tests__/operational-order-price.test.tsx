import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  operationalOrderPrice,
  assertDeliveryPriceLink,
} from "@/lib/operational-order-price";
import {
  OrderPriceAmount,
  OrderPriceSummary,
  LinkedDeliveryOrderPrice,
} from "@/components/orders/OperationalOrderPrice";
import { priceOrder } from "@/lib/order-pricing";
import { orderService } from "@/services/order.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

jest.mock("@/services/order.service", () => ({
  orderService: { getById: jest.fn() },
}));
const exact = () => ({
  id: "order-a",
  currency: "USD",
  total: 999,
  delivery_fee: 888,
  pricing: {
    ...priceOrder(
      [{ product_name: "Artículo exacto", quantity: "3", unit_price: "0.10" }],
      "0.01",
    ),
    revision: 7,
  },
  delivery: { id: "delivery-a", order_id: "order-a" },
});
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
});
afterEach(() => clearStoredTokens());

it("uses canonical decimal text and ignores every legacy amount alias", () => {
  expect(operationalOrderPrice(exact())).toMatchObject({
    state: "exact",
    pricing: { total: "0.31", revision: 7 },
  });
  render(<OrderPriceSummary order={exact()} items />);
  expect(screen.getByText("USD 0,31")).toBeInTheDocument();
  expect(screen.getByText("USD 0,01")).toBeInTheDocument();
  expect(screen.getByText("USD 0,10")).toBeInTheDocument();
  expect(screen.getAllByText("USD 0,30")).toHaveLength(2);
  expect(screen.getByText("Artículo exacto")).toBeInTheDocument();
  expect(screen.queryByText(/999|888/)).not.toBeInTheDocument();
  expect(
    screen.getByText(/cobros, el saldo pendiente y el bono/),
  ).toBeInTheDocument();
});
it.each([
  {},
  { total: 99, currency: "USD" },
  { pricing: null, total_amount: "9.00" },
  { items: [{ quantity: 3, unit_price: 5 }], subtotal: 15, delivery_fee: 2 },
])("does not reconstruct an absent exact price: %j", (order) => {
  expect(operationalOrderPrice(order)).toEqual({ state: "unavailable" });
  render(<OrderPriceSummary order={order} />);
  expect(
    screen.getByText(/Precio versionado no disponible/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/USD|Bs\./)).not.toBeInTheDocument();
});
it("keeps a confirmed zero and the largest supported cents", () => {
  const order = exact();
  order.pricing = { ...priceOrder([], "0.00", "0.00"), revision: 1 };
  const view = render(<OrderPriceAmount order={order} />);
  expect(screen.getByText("USD 0,00")).toBeInTheDocument();
  order.pricing = { ...priceOrder([], "0.00", "99999999.99"), revision: 2 };
  view.rerender(<OrderPriceAmount order={order} />);
  expect(screen.getByText("USD 99.999.999,99")).toBeInTheDocument();
});
it.each([
  { currency: null },
  { currency: "VES" },
  { currency: "usd" },
  { pricing: { ...exact().pricing, total: 0.31 } },
  { pricing: { ...exact().pricing, total: "0.310" } },
  { pricing: { ...exact().pricing, total: "3.1e-1" } },
  { pricing: { ...exact().pricing, total: "-0.00" } },
  { pricing: { ...exact().pricing, total: "0.32" } },
  { pricing: { ...exact().pricing, revision: 0 } },
  { pricing: { ...exact().pricing, version: 2 } },
  {
    pricing: {
      ...exact().pricing,
      items: [{ quantity: 3, unit_price: "0.10", subtotal: "0.30" }],
    },
  },
  {
    pricing: {
      ...exact().pricing,
      items: [{ quantity: "3", unit_price: "0.10", subtotal: "0.31" }],
    },
  },
])(
  "rejects corrupt or contradictory price evidence without falling back: %j",
  (change) => {
    const order = { ...exact(), ...change };
    expect(operationalOrderPrice(order)).toEqual({ state: "review" });
    render(<OrderPriceSummary order={order} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Precio por revisar");
    expect(screen.queryByText(/USD|999|888/)).not.toBeInTheDocument();
  },
);
it("preserves subtotal-only item evidence without inventing quantity or unit price", () => {
  const order = {
    ...exact(),
    pricing: {
      ...priceOrder(
        [{ product_name: "Importe conservado", subtotal: "0.10" }],
        "0.00",
      ),
      revision: 3,
    },
  };
  render(<OrderPriceSummary order={order} items />);
  const row = screen.getByRole("row", { name: /Importe conservado/ });
  expect(within(row).getByText("No registrada")).toBeInTheDocument();
  expect(within(row).getByText("No informado")).toBeInTheDocument();
  expect(within(row).getByText("USD 0,10")).toBeInTheDocument();
});
it.each([
  null,
  {},
  { ...exact(), id: "other" },
  { ...exact(), delivery: null },
  { ...exact(), delivery: { id: "other", order_id: "order-a" } },
  { ...exact(), delivery: { id: "delivery-a", order_id: "other" } },
])("rejects an unconfirmed delivery/order link: %j", (value) => {
  expect(() => assertDeliveryPriceLink(value, "order-a", "delivery-a")).toThrow(
    /vínculo/,
  );
});
it("loads the identified order independently and retries only that read", async () => {
  jest
    .mocked(orderService.getById)
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValueOnce(exact() as never);
  render(
    <LinkedDeliveryOrderPrice orderId="order-a" deliveryId="delivery-a" />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "No se pudo confirmar",
  );
  expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar precio" }));
  expect(await screen.findByText("USD 0,31")).toBeInTheDocument();
  expect(orderService.getById).toHaveBeenNthCalledWith(1, "order-a");
  expect(orderService.getById).toHaveBeenNthCalledWith(2, "order-a");
});
it("does not expose the wrong order's price", async () => {
  jest
    .mocked(orderService.getById)
    .mockResolvedValueOnce({ ...exact(), id: "other" } as never);
  render(
    <LinkedDeliveryOrderPrice orderId="order-a" deliveryId="delivery-a" />,
  );
  await screen.findByRole("alert");
  expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
});
it("keeps a previous confirmed revision explicitly marked after a failed refresh", async () => {
  jest
    .mocked(orderService.getById)
    .mockResolvedValueOnce(exact() as never)
    .mockRejectedValueOnce(new Error("503"));
  render(
    <LinkedDeliveryOrderPrice orderId="order-a" deliveryId="delivery-a" />,
  );
  await screen.findByText("USD 0,31");
  fireEvent.click(screen.getByRole("button", { name: "Actualizar precio" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "última lectura confirmada",
  );
  expect(screen.getByText("USD 0,31")).toBeInTheDocument();
});
it("clears the confirmed price and ignores a late response after link changes", async () => {
  let resolve!: (value: any) => void;
  jest
    .mocked(orderService.getById)
    .mockResolvedValueOnce(exact() as never)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce({
      ...exact(),
      id: "order-b",
      pricing: null,
      delivery: { id: "delivery-b", order_id: "order-b" },
    } as never);
  const view = render(
    <LinkedDeliveryOrderPrice orderId="order-a" deliveryId="delivery-a" />,
  );
  await screen.findByText("USD 0,31");
  fireEvent.click(screen.getByRole("button", { name: "Actualizar precio" }));
  view.rerender(
    <LinkedDeliveryOrderPrice orderId="order-b" deliveryId="delivery-b" />,
  );
  await screen.findByText(/Precio versionado no disponible/);
  await act(async () => {
    resolve(exact());
  });
  expect(screen.queryByText("USD 0,31")).not.toBeInTheDocument();
});
