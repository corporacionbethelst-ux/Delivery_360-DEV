import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { CustomerRefundsPanel } from "@/components/orders/CustomerRefundsPanel";
import { customerRefundsService as service } from "@/services/customer-refunds.service";
import {
  refund,
  refundContext,
  refundRequest,
  withRefund,
  approved,
  declared,
  returned,
  approval,
  execution,
  verification,
} from "../../test-utils/customer-refund-fixtures";
import { orderId } from "../../test-utils/order-currency-fixtures";
import { actorId, nextId } from "../../test-utils/currency-fixtures";
import { reviewerId } from "../../test-utils/customer-collection-fixtures";
let mockState: any = {
  user: { id: actorId, role: "SUPERADMIN" },
  sessionRevision: 1,
};
jest.mock("@/stores/authStore", () => ({
  useAuthStore: (select: any) => select(mockState),
}));
jest.mock("@/services/customer-refunds.service", () => ({
  customerRefundsService: {
    context: jest.fn(),
    receipt: jest.fn(),
    request: jest.fn(),
    event: jest.fn(),
    events: jest.fn(),
  },
}));
const descriptor = Object.getOwnPropertyDescriptor(window.crypto, "randomUUID");
beforeEach(() => {
  jest.resetAllMocks();
  mockState = { user: { id: actorId, role: "SUPERADMIN" }, sessionRevision: 1 };
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" + orderId,
  );
  Object.defineProperty(window.crypto, "randomUUID", {
    configurable: true,
    value: () => nextId,
  });
  jest.mocked(service.context).mockResolvedValue(refundContext);
  jest.mocked(service.request).mockResolvedValue(refund);
});
afterEach(() => {
  if (descriptor)
    Object.defineProperty(window.crypto, "randomUUID", descriptor);
  else delete (window.crypto as any).randomUUID;
});
const panel = () =>
  render(<CustomerRefundsPanel orderId={orderId} orderStatus="CANCELADO" />);
const open = async () => {
  await screen.findByText("Solicitar devolución parcial o total");
  fireEvent.change(screen.getByLabelText("Importe a devolver en USD"), {
    target: { value: "0.10" },
  });
  fireEvent.change(screen.getByLabelText("Motivo de devolución"), {
    target: { value: refundRequest.reason },
  });
  fireEvent.click(screen.getByLabelText(/Confirmo que solicito este importe/));
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar solicitud de devolución" }),
  );
  return screen.findByRole("dialog");
};
it("does not add requests on active orders or for client/rider roles", () => {
  const view = render(
    <CustomerRefundsPanel orderId={orderId} orderStatus="PENDIENTE" />,
  );
  expect(service.context).not.toHaveBeenCalled();
  mockState.user.role = "CLIENTE";
  view.rerender(
    <CustomerRefundsPanel orderId={orderId} orderStatus="CANCELADO" />,
  );
  expect(service.context).not.toHaveBeenCalled();
});
it("requires prior review and allows cancel without writes", async () => {
  panel();
  const modal = await open();
  expect(service.request).not.toHaveBeenCalled();
  fireEvent.click(within(modal).getByRole("button", { name: "Cancelar" }));
  expect(service.request).not.toHaveBeenCalled();
});
it("saves the reviewed request and preserves a recoverable link", async () => {
  panel();
  const modal = await open();
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(service.request).toHaveBeenCalledWith(orderId, refundRequest);
  expect(window.location.search).toContain("refund=" + refund.id);
});
it("retries exactly the same request after a lost response and closing review", async () => {
  jest
    .mocked(service.request)
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(refund);
  panel();
  const modal = await open();
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await within(modal).findByRole("button", {
    name: "Reintentar misma devolución",
  });
  fireEvent.click(within(modal).getByRole("button", { name: "Cerrar" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar devolución pendiente" }),
  );
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(jest.mocked(service.request).mock.calls[1]).toEqual(
    jest.mocked(service.request).mock.calls[0],
  );
});
it("refreshes after a definitive conflict and requires review again", async () => {
  jest.mocked(service.request).mockRejectedValue({
    response: { status: 412, data: { detail: "Las devoluciones cambiaron" } },
  });
  panel();
  const modal = await open();
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await waitFor(() => expect(service.context).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reintentar devolución pendiente" }),
  ).not.toBeInTheDocument();
});
it("lets another supervisor authorize without pretending that money was returned", async () => {
  mockState.user = { id: reviewerId, role: "GERENTE" };
  const row = { ...refund, allowed_actions: ["APROBAR", "RECHAZAR"] as const };
  jest
    .mocked(service.context)
    .mockResolvedValue(
      withRefund({ ...row, allowed_actions: [...row.allowed_actions] }),
    );
  jest
    .mocked(service.event)
    .mockResolvedValue({ refund: approved, applied_event: approval });
  panel();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Aprobar solicitud",
    }),
  );
  fireEvent.change(
    screen.getByLabelText("Motivo o comprobación de devolución"),
    { target: { value: approval.note } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar acción de devolución" }),
  );
  const modal = await screen.findByRole("dialog");
  expect(service.event).not.toHaveBeenCalled();
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(service.event).toHaveBeenCalledWith(
    orderId,
    refund.id,
    expect.objectContaining({
      kind: "APROBAR",
      verified_evidence: false,
      confirmed_execution: false,
    }),
  );
});
it("requires an actual matching execution and explicit confirmation", async () => {
  jest.mocked(service.context).mockResolvedValue(withRefund(approved));
  jest
    .mocked(service.event)
    .mockResolvedValue({ refund: declared, applied_event: execution });
  panel();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Registrar devolución realizada",
    }),
  );
  fireEvent.change(
    screen.getByLabelText("Motivo o comprobación de devolución"),
    { target: { value: execution.note } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar acción de devolución" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Confirma la comprobación",
  );
  expect(service.event).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/Confirmo que ya realicé/));
  for (const [label, value] of [
    ["Importe realmente devuelto", "0.10"],
    ["Alias de caja o cuenta de salida", "CAJA"],
    ["Referencia única de devolución", "SALIDA-95"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar acción de devolución" }),
  );
  const modal = await screen.findByRole("dialog");
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(service.event).toHaveBeenCalledWith(
    orderId,
    refund.id,
    expect.objectContaining({
      kind: "DECLARAR_EJECUCION",
      paid_amount: "0.10",
      paid_currency: "USD",
      confirmed_execution: true,
      source_key: "CAJA",
      reference_key: "SALIDA-95",
    }),
  );
});
it("requires independent evidence before confirming the refund", async () => {
  mockState.user = { id: reviewerId, role: "GERENTE" };
  jest.mocked(service.context).mockResolvedValue(withRefund(declared));
  jest
    .mocked(service.event)
    .mockResolvedValue({ refund: returned, applied_event: verification });
  panel();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Verificar devolución",
    }),
  );
  fireEvent.change(
    screen.getByLabelText("Motivo o comprobación de devolución"),
    { target: { value: verification.note } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar acción de devolución" }),
  );
  expect(service.event).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/He comprobado el efectivo/));
  fireEvent.click(
    screen.getByRole("button", { name: "Revisar acción de devolución" }),
  );
  const modal = await screen.findByRole("dialog");
  fireEvent.click(
    within(modal).getByRole("button", {
      name: "Confirmar y guardar devolución",
    }),
  );
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(service.event).toHaveBeenCalledWith(
    orderId,
    refund.id,
    expect.objectContaining({
      kind: "VERIFICAR_DEVOLUCION",
      verified_evidence: true,
      confirmed_execution: false,
    }),
  );
});
it("keeps auditors read-only even if a stale response contains actions", async () => {
  mockState.user.role = "AUDITOR";
  jest.mocked(service.context).mockResolvedValue(withRefund(declared));
  panel();
  await screen.findByText("Solicitudes conservadas · últimas 1");
  expect(
    screen.queryByRole("button", { name: "Verificar devolución" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Revisar solicitud de devolución" }),
  ).not.toBeInTheDocument();
});
it("recovers an old request by retained link outside the recent list", async () => {
  window.history.replaceState(
    null,
    "",
    "/manager/operations/orders/" + orderId + "?refund=" + refund.id,
  );
  jest.mocked(service.receipt).mockResolvedValue(returned);
  panel();
  await screen.findByRole("generic", { name: "Devolución conservada" });
  expect(service.receipt).toHaveBeenCalledWith(orderId, refund.id);
});
it("retires late private context when identity changes", async () => {
  let resolve!: (value: any) => void;
  jest
    .mocked(service.context)
    .mockReturnValueOnce(new Promise((yes) => (resolve = yes)))
    .mockResolvedValueOnce(refundContext);
  const view = panel();
  mockState = { user: { id: reviewerId, role: "GERENTE" }, sessionRevision: 2 };
  view.rerender(
    <CustomerRefundsPanel orderId={orderId} orderStatus="CANCELADO" />,
  );
  await screen.findByText("Solicitar devolución parcial o total");
  await act(async () => resolve(withRefund(refund)));
  expect(screen.queryByText(refund.reason)).not.toBeInTheDocument();
});
