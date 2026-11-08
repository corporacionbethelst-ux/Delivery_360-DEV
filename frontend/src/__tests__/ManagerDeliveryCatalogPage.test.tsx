import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/operations/deliveries/page";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import {
  deliveryHttp,
  deliveryPage,
  deliveryRow,
  riderId,
} from "../../test-fixtures/delivery-catalog";
const mockRouter = { replace: jest.fn() };
let mockUser: { id: string; role: string } | null = {
    id: "a",
    role: "GERENTE",
  },
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => {
  jest.resetAllMocks();
  mockUser = { id: "a", role: "GERENTE" };
  mockAuthenticated = true;
  storeTokens({ access_token: "a", refresh_token: "ra" });
  get.mockImplementation(async (url) => deliveryHttp(url));
});
afterEach(() => clearStoredTokens());
const confirmed = () =>
  screen.findByRole("region", { name: "Consulta de entregas confirmada" });
const apply = () =>
  fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
it("shows only real IDs, reference absence, zero duration and false SLA", async () => {
  get.mockResolvedValueOnce(deliveryPage({}, 1));
  render(<Page />);
  await confirmed();
  const row = screen.getByRole("row", { name: "Entrega delivery-1" });
  expect(within(row).getByText("Referencia no informada")).toBeInTheDocument();
  expect(within(row).getByText("0 min")).toBeInTheDocument();
  expect(within(row).getByText("Fuera de SLA")).toBeInTheDocument();
  expect(within(row).getByText("ID orden: order-1")).toBeInTheDocument();
  expect(screen.queryByText(/ORD-order/)).not.toBeInTheDocument();
});
it("uses unknown labels without changing missing status into PENDIENTE", async () => {
  get.mockResolvedValueOnce(
    deliveryPage({}, 1, {
      items: [
        deliveryRow(1, {
          rider_id: null,
          rider: null,
          status: null,
          total_time: null,
          started_at: null,
          sla_compliant: null,
          customer_name: null,
        }),
      ],
    }),
  );
  render(<Page />);
  await confirmed();
  for (const text of [
    "Sin asignar",
    "Cliente no informado",
    "Estado no informado",
    "Duración no informada",
    "SLA no informado",
  ])
    expect(
      within(screen.getByRole("row", { name: "Entrega delivery-1" })).getByText(
        text,
      ),
    ).toBeInTheDocument();
});
it("paginates from confirmed metadata and keeps search explicitly local", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("Buscar solo en esta página"), {
    target: { value: "delivery-20" },
  });
  expect(screen.getAllByRole("row")).toHaveLength(2);
  expect(get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByText(/Página 2:/);
  expect(
    screen.getByText(/Sin coincidencias en esta página/),
  ).toBeInTheDocument();
  expect(get).toHaveBeenLastCalledWith("/deliveries/page?limit=20&offset=20");
  fireEvent.change(screen.getByLabelText("Buscar solo en esta página"), {
    target: { value: "" },
  });
  expect(
    screen.getByRole("row", { name: "Entrega delivery-21" }),
  ).toBeInTheDocument();
});
it("applies Sin asignar without typing a search and identifies the server query", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("Asignación en el servidor"), {
    target: { value: "unassigned" },
  });
  expect(get).toHaveBeenCalledTimes(1);
  apply();
  await screen.findByText(/Consulta confirmada:.*Sin asignar/);
  expect(get).toHaveBeenLastCalledWith(
    "/deliveries/page?limit=20&offset=0&unassigned=true",
  );
  expect(screen.getByLabelText("ID repartidor (opcional)")).toBeDisabled();
  expect(
    screen
      .getAllByRole("row")
      .slice(1)
      .every((row) => within(row).getByText("Sin asignar")),
  ).toBe(true);
});
it("submits status, rider and page size together", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("Estado en el servidor"), {
    target: { value: "FALLIDA" },
  });
  fireEvent.change(screen.getByLabelText("ID repartidor (opcional)"), {
    target: { value: riderId },
  });
  fireEvent.change(screen.getByLabelText("Filas por página"), {
    target: { value: "50" },
  });
  apply();
  await screen.findByText(/Consulta confirmada: estado Fallida/);
  expect(get).toHaveBeenLastCalledWith(
    `/deliveries/page?limit=50&offset=0&status=FALLIDA&rider_id=${riderId}`,
  );
  expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
});
it("rejects a malformed rider before making a request and recovers with reset", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("ID repartidor (opcional)"), {
    target: { value: "bad" },
  });
  apply();
  expect(screen.getByRole("alert")).toHaveTextContent("UUID");
  expect(get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Restablecer filtros" }));
  await confirmed();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("ID repartidor (opcional)")).toHaveValue("");
});
it("preserves the confirmed page on failed filter and retries the exact attempt", async () => {
  render(<Page />);
  await confirmed();
  get.mockRejectedValueOnce(new Error("offline"));
  fireEvent.change(screen.getByLabelText("Estado en el servidor"), {
    target: { value: "COMPLETADA" },
  });
  apply();
  await screen.findByRole("alert");
  expect(
    screen.getByRole("row", { name: "Entrega delivery-1" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Consulta de entregas confirmada" }),
  ).toHaveTextContent("estado Todos los estados");
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByText(/Consulta confirmada: estado Completada/);
  expect(get).toHaveBeenLastCalledWith(
    "/deliveries/page?limit=20&offset=0&status=COMPLETADA",
  );
});
it("does not confuse a cold error with a successful empty result", async () => {
  get.mockRejectedValueOnce(new Error("offline"));
  render(<Page />);
  await screen.findByRole("alert");
  expect(screen.queryByText(/No hay entregas/)).not.toBeInTheDocument();
  get.mockResolvedValueOnce(deliveryPage({}, 0, { total: 0 }));
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByText("No hay entregas en esta página de la consulta.");
  expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
});
it("allows explicit recovery when data shrinks beyond the requested page", async () => {
  render(<Page />);
  await confirmed();
  get.mockResolvedValueOnce(deliveryPage({ offset: 20 }, 0, { total: 2 }));
  fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByText(/Página 2: 0 registros/);
  fireEvent.click(screen.getByRole("button", { name: "Volver al inicio" }));
  await screen.findByText(/Página 1:/);
  expect(get).toHaveBeenLastCalledWith("/deliveries/page?limit=20&offset=0");
});
it("retains data when adjacent pages overlap and supports explicit first-page restart", async () => {
  render(<Page />);
  await confirmed();
  get.mockResolvedValueOnce(
    deliveryPage({ offset: 20 }, 1, { items: [deliveryRow(1)] }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByRole("alert");
  expect(
    screen.getByRole("region", { name: "Consulta de entregas confirmada" }),
  ).toHaveTextContent("Página 1");
});
it("discards rapid filter responses that arrive out of order", async () => {
  render(<Page />);
  await confirmed();
  let resolve!: (v: unknown) => void;
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  fireEvent.change(screen.getByLabelText("Estado en el servidor"), {
    target: { value: "COMPLETADA" },
  });
  apply();
  fireEvent.change(screen.getByLabelText("Estado en el servidor"), {
    target: { value: "FALLIDA" },
  });
  apply();
  await screen.findByText(/Consulta confirmada: estado Fallida/);
  await act(async () => {
    resolve(
      deliveryPage({}, 1, {
        items: [deliveryRow(1, { status: "COMPLETADA" })],
      }),
    );
  });
  expect(
    screen.getByRole("region", { name: "Consulta de entregas confirmada" }),
  ).toHaveTextContent("estado Fallida");
});
it("refreshes the confirmed query instead of a modified draft", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("Estado en el servidor"), {
    target: { value: "FALLIDA" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Actualizar consulta" }));
  await confirmed();
  expect(get).toHaveBeenLastCalledWith("/deliveries/page?limit=20&offset=0");
});
it("encodes the actual order link and keeps all source IDs", async () => {
  get.mockResolvedValueOnce(
    deliveryPage({}, 1, {
      items: [deliveryRow(1, { order_id: "order/a?x=1" })],
    }),
  );
  render(<Page />);
  await confirmed();
  expect(
    screen.getByRole("link", { name: "Ver orden de entrega delivery-1" }),
  ).toHaveAttribute("href", "/manager/operations/orders/order%2Fa%3Fx%3D1");
});
it("clears private rows, filters and search on account change before a new response", async () => {
  render(<Page />);
  await confirmed();
  fireEvent.change(screen.getByLabelText("Buscar solo en esta página"), {
    target: { value: "José" },
  });
  let resolve!: (v: unknown) => void;
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  act(() => {
    mockUser = { id: "b", role: "GERENTE" };
    storeTokens({ access_token: "b", refresh_token: "rb" });
  });
  expect(
    screen.queryByRole("row", { name: "Entrega delivery-1" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Buscar solo en esta página"),
  ).not.toBeInTheDocument();
  await act(async () =>
    resolve(deliveryPage({}, 1, { items: [deliveryRow(2)] })),
  );
  await screen.findByRole("row", { name: "Entrega delivery-2" });
  expect(screen.getByLabelText("Buscar solo en esta página")).toHaveValue("");
});
it("retires the old response after logout without additional reads", async () => {
  let resolve!: (v: unknown) => void;
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  render(<Page />);
  act(() => {
    mockAuthenticated = false;
    mockUser = null;
    clearStoredTokens();
  });
  await act(async () => resolve(deliveryPage()));
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(get).toHaveBeenCalledTimes(1);
  expect(mockRouter.replace).toHaveBeenCalledWith("/login");
});
it.each(["OPERADOR", "REPARTIDOR", "AUDITOR", "CLIENTE", "UNKNOWN"])(
  "never mounts private reads for %s",
  (role) => {
    mockUser = { id: "a", role };
    render(<Page />);
    expect(get).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("admits SUPERADMIN but never mounts the logged out catalog", async () => {
  mockUser = { id: "a", role: "SUPERADMIN" };
  const view = render(<Page />);
  await confirmed();
  act(() => {
    mockAuthenticated = false;
    view.rerender(<Page />);
  });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
it("preserves unknown server states and missing rider names without substituting pending", async () => {
  get.mockResolvedValueOnce(
    deliveryPage({}, 1, {
      items: [
        deliveryRow(1, {
          status: "FUTURE_STATE",
          external_id: "REAL-REFERENCE",
          rider: { id: riderId, first_name: null, last_name: null },
        }),
      ],
    }),
  );
  render(<Page />);
  await confirmed();
  const row = screen.getByRole("row", { name: "Entrega delivery-1" });
  expect(within(row).getByText("FUTURE_STATE")).toBeInTheDocument();
  expect(within(row).getByText("REAL-REFERENCE")).toBeInTheDocument();
  expect(within(row).getByText("Nombre no informado")).toBeInTheDocument();
});
