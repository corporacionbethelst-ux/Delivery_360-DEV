import "@testing-library/jest-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/operations/orders/page";
import { downloadCSV } from "@/lib/csv-export";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import { FeedbackHost } from "@/components/layout/FeedbackHost";
import { clearFeedback } from "@/lib/feedback";
const mockRouter = { push: jest.fn() };
let mockUser = { id: "admin-a", role: "SUPERADMIN" };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter, usePathname: () => "/manager/operations/orders" }));
jest.mock("sonner", () => ({ Toaster: () => null, toast: { success: jest.fn(), info: jest.fn(), dismiss: jest.fn() } }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser }),
}));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn(() => true) }));
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() },
}));
const order = {
  id: "order-1",
  external_id: "ORD-LOADING-001",
  status: "PENDIENTE",
  priority: "NORMAL",
  customer_name: "Cliente de carga",
  delivery_address: "Destino de prueba",
  created_at: "2026-11-15T12:00:00Z",
  items: [],
  total: 10,
  currency: "USD",
  assigned_rider_id: null,
  rider_id: null,
  assigned_rider: null,
  delivery: null,
};
const riders = [
  {
    id: "rider-1",
    user_id: "user-1",
    status: "ACTIVO",
    first_name: "Ana",
    last_name: "Prueba",
    is_online: false,
  },
];
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
beforeEach(() => {
  jest.resetAllMocks();
  clearFeedback();
  mockUser = { id: "admin-a", role: "SUPERADMIN" };
  clearStoredTokens();
  storeTokens({ access_token: "orders-a", refresh_token: "refresh-a" });
  jest.spyOn(console, "error").mockImplementation(() => {});
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      String(url).startsWith("/orders?")
        ? [order]
        : String(url).startsWith("/riders")
          ? riders
          : [],
    );
});
afterEach(() => {
  clearFeedback();
  jest.restoreAllMocks();
  clearStoredTokens();
});

function loadEnRouteOrder() {
  jest.mocked(api.get).mockImplementation(async (url) =>
    String(url).startsWith("/orders?") ? [{ ...order, status: "EN_RUTA" }] : [],
  );
}

it("waits for the centered confirmation and submits only once after duplicate clicks", async () => {
  loadEnRouteOrder();
  jest.mocked(api.patch).mockResolvedValue({ ...order, status: "FALLIDO" });
  render(<><Page /><FeedbackHost /></>);
  const action = await screen.findByRole("button", { name: "FALLIDO" });
  fireEvent.click(action);
  fireEvent.click(action);
  const confirmation = screen.getByRole("alertdialog");
  expect(api.patch).not.toHaveBeenCalled();
  fireEvent.click(within(confirmation).getByRole("button", { name: "Confirmar" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
  expect(api.patch).toHaveBeenCalledWith("/orders/order-1/status", {}, { params: { new_status: "FALLIDO" } });
});

it("collects delivery OTP in a dialog and sends it in JSON preserving leading zeros", async () => {
  loadEnRouteOrder();
  jest.mocked(api.patch).mockResolvedValue({ ...order, status: "ENTREGADO" });
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  expect(api.patch).not.toHaveBeenCalled();
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("OTP de entrega (si corresponde)"), { target: { value: "001234" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar entrega" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/orders/order-1/status", { otp_code: "001234" }, { params: { new_status: "ENTREGADO" } }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("explicitly emails the recipient code once without completing the order", async () => {
  loadEnRouteOrder();
  const request = deferred<unknown>();
  jest.mocked(api.post).mockReturnValue(request.promise as any);
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  const dialog = screen.getByRole("dialog");
  const send = within(dialog).getByRole("button", { name: "Enviar OTP por correo" });
  fireEvent.click(send);
  fireEvent.click(send);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith("/orders/order-1/delivery-otp/email");
  expect(within(dialog).getByRole("button", { name: "Confirmar entrega" })).toBeDisabled();
  await act(async () => request.resolve({ status: "accepted", channel: "EMAIL", message: "Correo aceptado; revisa tu bandeja." }));
  expect(within(dialog).getByRole("status")).toHaveTextContent("Correo aceptado");
  expect(api.patch).not.toHaveBeenCalled();
  expect(within(dialog).getByLabelText("OTP de entrega (si corresponde)")).toHaveValue("");
});

it("keeps transport failures visible without completing the order or inventing a code", async () => {
  loadEnRouteOrder();
  jest.mocked(api.post).mockRejectedValue({ response: { status: 503, data: { detail: "Correo no configurado" } } });
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Enviar OTP por correo" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Correo no configurado");
  expect(api.patch).not.toHaveBeenCalled();
  expect(within(dialog).queryByRole("status")).not.toBeInTheDocument();
});

it("does not offer staff recipient mail to an operator", async () => {
  mockUser = { ...mockUser, role: "OPERADOR" };
  loadEnRouteOrder();
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  expect(screen.queryByRole("button", { name: "Enviar OTP por correo" })).not.toBeInTheDocument();
});

it("does not report email success from a previous session", async () => {
  loadEnRouteOrder();
  const request = deferred<unknown>();
  jest.mocked(api.post).mockReturnValue(request.promise as any);
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  fireEvent.click(screen.getByRole("button", { name: "Enviar OTP por correo" }));
  await act(async () => { clearStoredTokens(); });
  await act(async () => request.resolve({ status: "accepted", channel: "EMAIL", message: "Resultado de cuenta anterior" }));
  expect(screen.queryByText("Resultado de cuenta anterior")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
});

it("rejects an unconfirmed email response without claiming success", async () => {
  loadEnRouteOrder();
  jest.mocked(api.post).mockResolvedValue({ status: "sent", channel: "EMAIL", message: "Éxito inventado" });
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  fireEvent.click(screen.getByRole("button", { name: "Enviar OTP por correo" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo confirmar la aceptación");
  expect(screen.queryByText("Éxito inventado")).not.toBeInTheDocument();
});

it("keeps OTP errors in the dialog and allows correction before retrying", async () => {
  loadEnRouteOrder();
  jest.mocked(api.patch).mockRejectedValueOnce({ response: { status: 400, data: { detail: "Código OTP requerido o incorrecto" } } }).mockResolvedValueOnce({ ...order, status: "ENTREGADO" });
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar entrega" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Código OTP requerido o incorrecto");
  expect(api.patch).toHaveBeenCalledTimes(1);
  fireEvent.change(within(dialog).getByLabelText("OTP de entrega (si corresponde)"), { target: { value: "001234" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar entrega" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.patch).toHaveBeenCalledTimes(2);
});

it("recovers a lost delivery response by reading status without a second mutation", async () => {
  loadEnRouteOrder();
  jest.mocked(api.patch).mockRejectedValue(new Error("Respuesta perdida"));
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "ENTREGADO" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirmar entrega" }));
  const read = await screen.findByRole("button", { name: "Consultar estado" });
  jest.mocked(api.get).mockImplementation(async (url) => String(url) === "/orders/order-1" ? { ...order, status: "ENTREGADO" } : []);
  fireEvent.click(read);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.patch).toHaveBeenCalledTimes(1);
  expect(api.get).toHaveBeenCalledWith("/orders/order-1");
});
it("renders real validated orders for superadmin", async () => {
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith("/orders?limit=100&offset=0");
});
it("keeps orders visible when the riders endpoint returns HTTP500", async () => {
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (String(url).startsWith("/riders"))
      throw {
        response: {
          status: 500,
          data: { detail: "Catálogo temporalmente no disponible" },
        },
      };
    return String(url).startsWith("/orders?") ? [order] : [];
  });
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  expect(
    await screen.findByText(/No se pudieron cargar los repartidores.*HTTP 500/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Exportar" })).toBeEnabled();
});
it("does not discard successful order HTTP200 when rider HTTP200 has duplicate user identities", async () => {
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      String(url).startsWith("/riders")
        ? [...riders, { ...riders[0], id: "rider-2" }]
        : String(url).startsWith("/orders?")
          ? [order]
          : [],
    );
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  expect(
    await screen.findByText(
      /No se pudieron cargar los repartidores.*contradictorias/,
    ),
  ).toBeInTheDocument();
});
it("does not wait for a pending auxiliary catalog before displaying orders", async () => {
  const pending = deferred<typeof riders>();
  jest
    .mocked(api.get)
    .mockImplementation((url) =>
      String(url).startsWith("/riders")
        ? pending.promise
        : Promise.resolve(String(url).startsWith("/orders?") ? [order] : []),
    );
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  await act(async () => pending.resolve(riders));
});
it("reports company vehicle failure without hiding orders or inventing a normal empty catalog", async () => {
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (String(url).startsWith("/vehicles")) throw new Error("Network Error");
    return String(url).startsWith("/orders?") ? [order] : riders;
  });
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  expect(
    await screen.findByText(/No se pudieron cargar los vehículos/),
  ).toBeInTheDocument();
});
it("shows the order endpoint error and retry succeeds without claiming an empty catalog", async () => {
  let failed = true;
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (String(url).startsWith("/orders?")) {
      if (failed)
        throw {
          response: { status: 500, data: { detail: "Error de consulta" } },
        };
      return [order];
    }
    return String(url).startsWith("/riders") ? riders : [];
  });
  render(<Page />);
  await screen.findByText(
    /No se pudieron cargar las órdenes.*HTTP 500.*Error de consulta/,
  );
  expect(
    screen.queryByText("No se encontraron órdenes."),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Exportar" })).toBeDisabled();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: /^Reintentar$/ }));
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
});
it("keeps contradictory assignment HTTP200 rows visible for review without permitting operations", async () => {
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      String(url).startsWith("/orders?")
        ? [{ ...order, assigned_rider_id: "one", rider_id: "another" }]
        : String(url).startsWith("/riders")
          ? riders
          : [],
    );
  render(<Page />);
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
  await screen.findByText(/orden requiere revisión de asignación/);
  expect(
    screen.queryByText(/No se pudieron cargar las órdenes/),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Asignar" }),
  ).not.toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Ver" }));
  await screen.findByRole("dialog");
  expect(screen.getByText("one")).toBeInTheDocument();
  expect(screen.getByText("another")).toBeInTheDocument();
  expect(mockRouter.push).not.toHaveBeenCalled();
});
it("retrying auxiliary catalogs restores them without losing the order", async () => {
  let failed = true;
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (String(url).startsWith("/riders")) {
      if (failed) throw new Error("Error de repartidores");
      return riders;
    }
    return String(url).startsWith("/orders?") ? [order] : [];
  });
  render(<Page />);
  await screen.findByText(/No se pudieron cargar los repartidores/);
  expect(screen.getByText("Cliente de carga")).toBeInTheDocument();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar catálogos" }));
  await waitFor(() =>
    expect(
      screen.queryByText(/No se pudieron cargar los repartidores/),
    ).not.toBeInTheDocument(),
  );
  expect(await screen.findByText("Cliente de carga")).toBeInTheDocument();
});
it("retires late orders after changing accounts", async () => {
  const pending = deferred<(typeof order)[]>();
  let first = true;
  jest.mocked(api.get).mockImplementation((url) => {
    if (String(url).startsWith("/orders?")) {
      if (first) {
        first = false;
        return pending.promise;
      }
      return Promise.resolve([
        { ...order, id: "new-order", customer_name: "Cliente de otra cuenta" },
      ]);
    }
    return Promise.resolve(String(url).startsWith("/riders") ? riders : []);
  });
  render(<Page />);
  act(() => {
    mockUser = { id: "admin-b", role: "SUPERADMIN" };
    storeTokens({ access_token: "orders-b", refresh_token: "refresh-b" });
  });
  expect(await screen.findByText("Cliente de otra cuenta")).toBeInTheDocument();
  await act(async () => pending.resolve([order]));
  expect(screen.queryByText("Cliente de carga")).not.toBeInTheDocument();
});
it("shows mixed good and conflicting delivery assignments while blocking only the conflicted order", async () => {
  const bad = {
    ...order,
    id: "bad",
    external_id: "ORD-BAD",
    customer_name: "Cliente por revisar",
    status: "EN_RUTA",
    assigned_rider_id: "rider-a",
    rider_id: "rider-a",
    assigned_rider: { id: "rider-a", full_name: "Ana" },
    delivery: {
      id: "delivery-bad",
      order_id: "bad",
      rider_id: "rider-b",
      status: "EN_ROUTE",
    },
  };
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      String(url).startsWith("/orders?")
        ? [order, bad]
        : String(url).startsWith("/riders")
          ? riders
          : [],
    );
  render(<Page />);
  const badCard = await screen.findByRole("article", { name: "Orden ORD-BAD" });
  const goodCard = screen.getByRole("article", {
    name: "Orden ORD-LOADING-001",
  });
  expect(
    within(goodCard).getByRole("button", { name: "Asignar" }),
  ).toBeInTheDocument();
  expect(within(badCard).getAllByRole("button")).toHaveLength(1);
  expect(
    within(badCard).getByText("Asignación por revisar"),
  ).toBeInTheDocument();
  expect(within(badCard).queryByText("Ana")).not.toBeInTheDocument();
  fireEvent.click(within(badCard).getByRole("button", { name: "Ver" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getAllByText("rider-a").length).toBeGreaterThan(0);
  expect(within(dialog).getByText("rider-b")).toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
});
it("exports original conflicting references explicitly without inventing a confirmed rider", async () => {
  const bad = {
    ...order,
    assigned_rider_id: "rider-a",
    rider_id: "rider-a",
    delivery: {
      id: "delivery-bad",
      order_id: order.id,
      rider_id: "rider-b",
      status: "INICIADA",
    },
  };
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      String(url).startsWith("/orders?")
        ? [bad]
        : String(url).startsWith("/riders")
          ? riders
          : [],
    );
  render(<Page />);
  await screen.findByText("Cliente de carga");
  fireEvent.click(screen.getByRole("button", { name: "Exportar" }));
  expect(downloadCSV).toHaveBeenCalledWith(
    [
      expect.objectContaining({
        ID: order.external_id,
        Rider: "Asignación por revisar",
        Repartidor_orden: "rider-a",
        Repartidor_entrega: "rider-b",
        Revision_asignacion: expect.stringContaining("no coinciden"),
      }),
    ],
    "reporte_ordenes",
  );
});
