import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OrderFailureDialog } from "@/components/orders/OrderFailureDialog";
import { deliveryService } from "@/services/delivery.service";
import { toast } from "@/lib/feedback";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import type { OperationalHttpOrder } from "@/lib/operational-catalog";
jest.mock("@/services/delivery.service", () => ({ deliveryService: { failDelivery: jest.fn() } }));
jest.mock("@/lib/feedback", () => ({ toast: { success: jest.fn() } }));
const order = { id: "order-1", external_id: "VE-123", status: "EN_RUTA", assigned_rider_id: "rider-1", assignment_review: null,
  delivery: { id: "delivery-1", order_id: "order-1", rider_id: "rider-1", status: "EN_ROUTE" } } as OperationalHttpOrder;
const fail = jest.mocked(deliveryService.failDelivery);
let onClose: jest.Mock;
let onRefresh: jest.Mock;
beforeEach(() => {
  jest.resetAllMocks(); storeTokens({ access_token: "failure-a", refresh_token: "refresh-a" });
  onClose = jest.fn(); onRefresh = jest.fn().mockResolvedValue(undefined);
});
afterEach(() => clearStoredTokens());
function show(value = order) { return render(<OrderFailureDialog order={value} onClose={onClose} onRefresh={onRefresh} />); }
function choose() { fireEvent.change(screen.getByLabelText("Motivo del intento fallido"), { target: { value: "REPARTIDOR_ERROR_PROPIO" } }); }
function confirm() { fireEvent.click(screen.getByRole("button", { name: "Confirmar fallo" })); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
it("requires an explicit cause and closing performs no write", () => {
  show();
  expect(screen.getByRole("dialog", { name: "Registrar intento fallido" })).toHaveTextContent("VE-123");
  expect(screen.getByLabelText("Motivo del intento fallido")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Confirmar fallo" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Volver" }));
  expect(onClose).toHaveBeenCalledTimes(1); expect(fail).not.toHaveBeenCalled();
});
it.each([
  { ...order, assignment_review: "Identidades contradictorias" }, { ...order, status: "ENTREGADO" },
  { ...order, delivery: { ...order.delivery!, status: "CANCELADA" } },
  { ...order, delivery: { ...order.delivery!, order_id: "other" } },
  { ...order, delivery: { ...order.delivery!, rider_id: "other" } },
])("rejects a stale or contradictory assignment", value => {
  show(value as OperationalHttpOrder);
  expect(screen.getByRole("alert")).toHaveTextContent("requiere revisión");
  expect(screen.getByRole("button", { name: "Confirmar fallo" })).toBeDisabled(); expect(fail).not.toHaveBeenCalled();
});
it("preserves the error and chosen cause and offers refresh without another write", async () => {
  fail.mockRejectedValue(new Error("La asignación cambió; revisa su detalle")); show(); choose(); confirm();
  expect(await screen.findByRole("alert")).toHaveTextContent("La asignación cambió");
  expect(screen.getByLabelText("Motivo del intento fallido")).toHaveValue("REPARTIDOR_ERROR_PROPIO");
  expect(onClose).not.toHaveBeenCalled(); expect(toast.success).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Consultar estado" }));
  await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  expect(fail).toHaveBeenCalledTimes(1); expect(onClose).toHaveBeenCalledTimes(1);
});
it("allows only one pending write and confirms after refreshing", async () => {
  const request = deferred<any>(); fail.mockReturnValue(request.promise); show(); choose(); confirm();
  fireEvent.submit(screen.getByRole("button", { name: "Verificando..." }).closest("form")!);
  expect(fail).toHaveBeenCalledTimes(1); expect(onRefresh).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Volver" })).toBeDisabled();
  await act(async () => request.resolve({ id: "delivery-1" }));
  expect(onRefresh).toHaveBeenCalledTimes(1); expect(toast.success).toHaveBeenCalledWith("Intento fallido registrado"); expect(onClose).toHaveBeenCalledTimes(1);
});
it("discards a delayed response after credentials change", async () => {
  const request = deferred<any>(); fail.mockReturnValue(request.promise); show(); choose(); confirm();
  storeTokens({ access_token: "failure-b", refresh_token: "refresh-b" });
  await act(async () => request.resolve({ id: "delivery-1" }));
  expect(onRefresh).not.toHaveBeenCalled(); expect(onClose).not.toHaveBeenCalled(); expect(toast.success).not.toHaveBeenCalled();
});
it("does not invoke callbacks after unmount", async () => {
  const request = deferred<any>(); fail.mockReturnValue(request.promise); const view = show(); choose(); confirm(); view.unmount();
  await act(async () => request.resolve({ id: "delivery-1" }));
  expect(onRefresh).not.toHaveBeenCalled(); expect(onClose).not.toHaveBeenCalled(); expect(toast.success).not.toHaveBeenCalled();
});
