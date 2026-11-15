import {
  render,
  screen,
  fireEvent,
  within,
  waitFor,
  act,
} from "@testing-library/react";
import { CustomerCollectionsPanel } from "@/components/orders/CustomerCollectionsPanel";
import { customerCollectionsService as service } from "@/services/customer-collections.service";
import {
  collection,
  collectionContext,
  pendingContext,
  reviewerId,
  reviewed,
} from "../../test-utils/customer-collection-fixtures";
import { orderId } from "../../test-utils/order-currency-fixtures";
import { actorId, nextId } from "../../test-utils/currency-fixtures";
let mockState: any = {
  user: { id: actorId, role: "OPERADOR" },
  sessionRevision: 1,
};
jest.mock("@/stores/authStore", () => ({
  useAuthStore: (select: any) => select(mockState),
}));
jest.mock("@/services/customer-collections.service", () => ({
  customerCollectionsService: {
    context: jest.fn(),
    declare: jest.fn(),
    review: jest.fn(),
    receipt: jest.fn(),
  },
}));
const descriptor = Object.getOwnPropertyDescriptor(window.crypto, "randomUUID");
beforeEach(() => {
  jest.resetAllMocks();
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" + orderId,
  );
  mockState = { user: { id: actorId, role: "OPERADOR" }, sessionRevision: 1 };
  Object.defineProperty(window.crypto, "randomUUID", {
    configurable: true,
    value: () => nextId,
  });
  jest.mocked(service.context).mockResolvedValue(collectionContext);
  jest.mocked(service.declare).mockResolvedValue(collection);
  jest.mocked(service.review).mockResolvedValue(reviewed);
});
afterEach(() => {
  if (descriptor)
    Object.defineProperty(window.crypto, "randomUUID", descriptor);
  else delete (window.crypto as any).randomUUID;
});
const openDeclaration = async () => {
  await screen.findByText("Declarar un abono recibido");
  for (const [label, value] of [
    ["Abono a la orden en USD", "0.20"],
    ["Importe realmente recibido", "0.20"],
    ["Alias interno de caja o cuenta", "CAJA"],
    ["Referencia completa o recibo único", "RECIBO-94"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText(/Confirmo que el importe/));
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar declaración de cobro" }),
  );
  return screen.findByRole("dialog");
};
it("requires explicit review and supports cancel without writing", async () => {
  render(<CustomerCollectionsPanel orderId={orderId} />);
  const modal = await openDeclaration();
  expect(service.declare).not.toHaveBeenCalled();
  fireEvent.click(within(modal).getByRole("button", { name: "Cancelar" }));
  expect(service.declare).not.toHaveBeenCalled();
});
it("saves a pending declaration with the reviewed amount and reference", async () => {
  render(<CustomerCollectionsPanel orderId={orderId} />);
  const modal = await openDeclaration();
  fireEvent.click(
    within(modal).getByRole("button", { name: "Confirmar y guardar" }),
  );
  await waitFor(() => expect(service.declare).toHaveBeenCalledTimes(1));
  expect(jest.mocked(service.declare).mock.calls[0][1]).toMatchObject({
    amount_usd: "0.20",
    paid_amount: "0.20",
    source_key: "CAJA",
    reference_key: "RECIBO-94",
    confirmed_received: true,
    request_key: nextId,
  });
  await screen.findByText(/Pendiente de revisión · USD/);
});
it("retains the same request after an ambiguous response and closing the dialog", async () => {
  jest
    .mocked(service.declare)
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(collection);
  render(<CustomerCollectionsPanel orderId={orderId} />);
  const modal = await openDeclaration();
  fireEvent.click(
    within(modal).getByRole("button", { name: "Confirmar y guardar" }),
  );
  await within(modal).findByRole("button", {
    name: "Reintentar misma solicitud",
  });
  fireEvent.click(within(modal).getByRole("button", { name: "Cerrar" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar solicitud de cobro" }),
  );
  await screen.findByText(/Pendiente de revisión · USD/);
  expect(jest.mocked(service.declare).mock.calls[1]).toEqual(
    jest.mocked(service.declare).mock.calls[0],
  );
});
it("refreshes and requires a new review after a definitive freshness conflict", async () => {
  jest.mocked(service.declare).mockRejectedValue({
    response: { status: 412, data: { detail: "Los cobros cambiaron" } },
  });
  render(<CustomerCollectionsPanel orderId={orderId} />);
  const modal = await openDeclaration();
  fireEvent.click(
    within(modal).getByRole("button", { name: "Confirmar y guardar" }),
  );
  await waitFor(() => expect(service.context).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reintentar solicitud de cobro" }),
  ).not.toBeInTheDocument();
});
it("prevents self review and allows another supervisor with evidence and note", async () => {
  mockState.user = { id: reviewerId, role: "GERENTE" };
  jest.mocked(service.context).mockResolvedValue(pendingContext);
  render(<CustomerCollectionsPanel orderId={orderId} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Revisar este cobro" }),
  );
  fireEvent.change(screen.getByLabelText("Comprobación o motivo"), {
    target: { value: "Ingreso comprobado con el recibo" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Revisar decisión" }));
  expect(service.review).not.toHaveBeenCalled();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Confirma la evidencia",
  );
  fireEvent.click(screen.getByLabelText(/He comprobado el efectivo/));
  fireEvent.click(screen.getByRole("button", { name: "Revisar decisión" }));
  const modal = await screen.findByRole("dialog");
  fireEvent.click(
    within(modal).getByRole("button", { name: "Confirmar y guardar" }),
  );
  await screen.findByText(/Verificado manualmente · USD/);
  expect(service.review).toHaveBeenCalledWith(
    orderId,
    collection.id,
    expect.objectContaining({
      decision: "VERIFICADO",
      verified_evidence: true,
      note: "Ingreso comprobado con el recibo",
    }),
  );
});
it("hides review of own declarations and all write controls for auditors", async () => {
  mockState.user.role = "GERENTE";
  jest.mocked(service.context).mockResolvedValue(pendingContext);
  const view = render(<CustomerCollectionsPanel orderId={orderId} />);
  await screen.findByText("Pendiente de revisión");
  expect(
    screen.queryByRole("button", { name: "Revisar este cobro" }),
  ).not.toBeInTheDocument();
  mockState = { user: { id: reviewerId, role: "AUDITOR" }, sessionRevision: 2 };
  view.rerender(<CustomerCollectionsPanel orderId={orderId} />);
  await screen.findByText("Pendiente de revisión");
  expect(
    screen.queryByRole("button", { name: "Revisar declaración de cobro" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Revisar este cobro" }),
  ).not.toBeInTheDocument();
});
it("retires delayed private history when the account changes", async () => {
  let resolve!: (value: any) => void;
  jest
    .mocked(service.context)
    .mockReturnValueOnce(new Promise((yes) => (resolve = yes)))
    .mockResolvedValueOnce(collectionContext);
  const view = render(<CustomerCollectionsPanel orderId={orderId} />);
  mockState = { user: { id: reviewerId, role: "GERENTE" }, sessionRevision: 2 };
  view.rerender(<CustomerCollectionsPanel orderId={orderId} />);
  await screen.findByText("Declarar un abono recibido");
  await act(async () => resolve(pendingContext));
  expect(screen.queryByText("RECIBO-94")).not.toBeInTheDocument();
});
it("blocks declarations on terminal orders and indicates refund liability", async () => {
  jest.mocked(service.context).mockResolvedValue({
    ...pendingContext,
    order_status: "CANCELADO",
    summary: { ...pendingContext.summary, refund_due_usd: "0.20" },
  });
  render(<CustomerCollectionsPanel orderId={orderId} />);
  await screen.findByText(/pendientes de devolución/);
  expect(
    screen.queryByRole("button", { name: "Revisar declaración de cobro" }),
  ).not.toBeInTheDocument();
});

it("recovers a retained declaration by link even outside the recent list", async () => {
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" +
      orderId +
      "?customer_collection=" +
      collection.id,
  );
  jest.mocked(service.receipt).mockResolvedValue(collection);
  render(<CustomerCollectionsPanel orderId={orderId} />);
  await screen.findByRole("generic", { name: "Registro de cobro conservado" });
  expect(service.receipt).toHaveBeenCalledWith(orderId, collection.id);
});
