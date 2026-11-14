import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
  act,
} from "@testing-library/react";
import { OrderCurrencyQuotePanel } from "@/components/orders/OrderCurrencyQuotePanel";
import { orderCurrencyQuoteService as service } from "@/services/order-currency-quote.service";
import {
  orderId,
  orderContext,
  orderReceipt,
  quoteCommand,
} from "../../test-utils/order-currency-fixtures";
import { nextId } from "../../test-utils/currency-fixtures";
let mockState: any = {
  user: { id: "staff", role: "SUPERADMIN" },
  sessionRevision: 1,
};
jest.mock("@/stores/authStore", () => ({
  useAuthStore: (select: any) => select(mockState),
}));
jest.mock("@/services/order-currency-quote.service", () => ({
  orderCurrencyQuoteService: {
    context: jest.fn(),
    create: jest.fn(),
    receipt: jest.fn(),
  },
}));
const descriptor = Object.getOwnPropertyDescriptor(window.crypto, "randomUUID");
beforeEach(() => {
  jest.resetAllMocks();
  mockState = { user: { id: "staff", role: "SUPERADMIN" }, sessionRevision: 1 };
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" + orderId,
  );
  Object.defineProperty(window.crypto, "randomUUID", {
    configurable: true,
    value: () => nextId,
  });
  jest.mocked(service.context).mockResolvedValue(orderContext);
  jest.mocked(service.create).mockResolvedValue(orderReceipt);
  jest.mocked(service.receipt).mockResolvedValue(orderReceipt);
});
afterEach(() => {
  if (descriptor)
    Object.defineProperty(window.crypto, "randomUUID", descriptor);
  else delete (window.crypto as any).randomUUID;
});
const open = async () => {
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Revisar cotización de la orden",
    }),
  );
  return screen.findByRole("dialog");
};

it.each([{ pricing: null }, { current_rate: null }, { status: "CANCELADO" }])(
  "blocks creation without a confirmed eligible order and current reference %j",
  async (change) => {
    jest
      .mocked(service.context)
      .mockResolvedValue({ ...orderContext, ...change });
    render(<OrderCurrencyQuotePanel orderId={orderId} />);
    expect(
      await screen.findByRole("button", {
        name: "Revisar cotización de la orden",
      }),
    ).toBeDisabled();
    expect(service.create).not.toHaveBeenCalled();
  },
);
it("requires review and allows cancellation without writing", async () => {
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  const dialog = await open();
  expect(within(dialog).getByText("Bs. 0,75")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
  expect(service.create).not.toHaveBeenCalled();
});
it("saves the exact reviewed revision and preserves a recoverable receipt link", async () => {
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  const dialog = await open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Guardar cotización" }),
  );
  expect(
    await screen.findByRole("generic", { name: "Comprobante conservado" }),
  ).toBeInTheDocument();
  expect(service.create).toHaveBeenCalledWith(orderId, quoteCommand);
  expect(window.location.search).toContain(orderReceipt.id);
});
it("retains the original request after an ambiguous failure and can retry after closing review", async () => {
  jest
    .mocked(service.create)
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(orderReceipt);
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  const dialog = await open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Guardar cotización" }),
  );
  const retry = await within(dialog).findByRole("button", {
    name: "Reintentar comprobante",
  });
  expect(retry).toBeEnabled();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Cerrar revisión" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar comprobante pendiente" }),
  );
  await waitFor(() => expect(service.create).toHaveBeenCalledTimes(2));
  expect(jest.mocked(service.create).mock.calls[1]).toEqual(
    jest.mocked(service.create).mock.calls[0],
  );
  expect(await screen.findByText("Cotización guardada")).toBeInTheDocument();
});
it("refreshes after a definitive revision conflict and requires another review", async () => {
  jest
    .mocked(service.create)
    .mockRejectedValue({
      response: {
        status: 412,
        data: { detail: "El precio de la orden cambió" },
      },
    });
  jest
    .mocked(service.context)
    .mockResolvedValueOnce(orderContext)
    .mockResolvedValue({
      ...orderContext,
      pricing: { ...orderContext.pricing!, revision: 2 },
    });
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  const dialog = await open();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Guardar cotización" }),
  );
  await waitFor(() => expect(service.context).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("Cotización guardada")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reintentar comprobante pendiente" }),
  ).not.toBeInTheDocument();
});
it("recovers a retained receipt on full page reload even outside the recent list", async () => {
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" + orderId + "?bcv_quote=" + orderReceipt.id,
  );
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  expect(await screen.findByText("Cotización guardada")).toBeInTheDocument();
  expect(service.receipt).toHaveBeenCalledWith(orderReceipt.id, orderId);
});
it("does not publish a delayed private context after an account changes", async () => {
  let resolve!: (value: any) => void;
  jest
    .mocked(service.context)
    .mockReturnValueOnce(
      new Promise((yes) => {
        resolve = yes;
      }),
    )
    .mockResolvedValueOnce(orderContext);
  const view = render(<OrderCurrencyQuotePanel orderId={orderId} />);
  mockState = { user: { id: "other", role: "SUPERADMIN" }, sessionRevision: 2 };
  view.rerender(<OrderCurrencyQuotePanel orderId={orderId} />);
  await screen.findByRole("button", { name: "Revisar cotización de la orden" });
  await act(async () => resolve({ ...orderContext, receipts: [orderReceipt] }));
  expect(
    screen.queryByText(/Comprobantes conservados/),
  ).not.toBeInTheDocument();
});
it("shows the saved price revision without treating it as the updated order price", async () => {
  jest
    .mocked(service.context)
    .mockResolvedValue({
      ...orderContext,
      pricing: { ...orderContext.pricing!, revision: 2 },
      receipts: [orderReceipt],
    });
  render(<OrderCurrencyQuotePanel orderId={orderId} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /USD 0,50 → Bs. 0,75/ }),
  );
  expect(
    screen.getByText(/El precio actual de la orden cambió/),
  ).toBeInTheDocument();
  expect(service.create).not.toHaveBeenCalled();
});
it("keeps auditors read-only and hides the panel from client and rider roles", async () => {
  mockState.user.role = "AUDITOR";
  const view = render(<OrderCurrencyQuotePanel orderId={orderId} />);
  await screen.findByText(/Precio de la orden/);
  expect(
    screen.queryByRole("button", { name: "Revisar cotización de la orden" }),
  ).not.toBeInTheDocument();
  mockState.user.role = "REPARTIDOR";
  view.rerender(<OrderCurrencyQuotePanel orderId={orderId} />);
  expect(
    screen.queryByRole("region", { name: "Cotización BCV de la orden" }),
  ).not.toBeInTheDocument();
});
