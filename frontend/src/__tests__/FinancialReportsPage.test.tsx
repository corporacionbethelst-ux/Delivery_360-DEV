import { act, fireEvent, render, screen } from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/financial/reports/page";
import { api } from "@/lib/api";
import { downloadCSV } from "@/lib/csv-export";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/financial-exact.json";
const mockRouter = { replace: jest.fn() };
let mockRole = "GERENTE",
  mockId = "a",
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    user: { id: mockId, role: mockRole },
    isAuthenticated: mockAuthenticated,
  }),
}));
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get);
const loaded = () =>
  screen.findByRole("region", { name: "Reporte exacto confirmado" });
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockId = "a";
  mockAuthenticated = true;
  mockRole = "GERENTE";
  get.mockResolvedValue(fixture);
  jest.mocked(downloadCSV).mockReturnValue(true);
});
afterEach(() => clearStoredTokens());
it("separates exact order value, ledger change and withdrawal requests with visible exclusions", async () => {
  render(<Page />);
  await loaded();
  expect(get).toHaveBeenCalledWith("/financial/reports/exact?");
  expect(
    screen.getByRole("heading", { name: "Reportes y exportación exactos" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Valor de órdenes")).toBeInTheDocument();
  expect(screen.getByText("Cambio contable de riders")).toBeInTheDocument();
  expect(
    screen.getByText("1 registros excluidos de los importes"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Los precios no equivalen a ingresos cobrados/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Una aprobación o un estado EN PROCESO no acredita/),
  ).toBeInTheDocument();
  expect(screen.queryByText("Margen neto")).not.toBeInTheDocument();
});
it("exports all three sources and exclusions from the loaded snapshot without a second HTTP request", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Mostrar fuente"), {
    target: { value: "ORDEN" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  );
  expect(downloadCSV).toHaveBeenCalledTimes(1);
  expect(jest.mocked(downloadCSV).mock.calls[0][0]).toHaveLength(
    fixture.row_count,
  );
  expect(get).toHaveBeenCalledTimes(1);
  expect(await screen.findByText(/CSV generado con/)).toBeInTheDocument();
});
it("clears stale data and disables CSV after editing dates, then applies the new range", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Desde", { exact: true }), {
    target: { value: "2026-11-13" },
  });
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
  get.mockResolvedValue({
    ...fixture,
    date_from: "2026-11-13",
    period_start: "2026-11-13T04:00:00.000000Z",
    daily: [
      {
        ...fixture.daily[0],
        date: "2026-11-13",
        orders: {
          count: 0,
          subtotal_usd: "0.00",
          delivery_fee_usd: "0.00",
          total_usd: "0.00",
        },
        ledger: {
          count: 0,
          credit_usd: "0.00",
          debit_usd: "0.00",
          adjustment_usd: "0.00",
          net_change_usd: "0.00",
        },
        payouts: { count: 0, amount_usd: "0.00" },
      },
      ...fixture.daily,
    ],
  });
  fireEvent.click(screen.getByRole("button", { name: "Aplicar consulta" }));
  await loaded();
  expect(get).toHaveBeenLastCalledWith(
    "/financial/reports/exact?date_from=2026-11-13&date_to=2026-11-14",
  );
});
it("distinguishes an initial HTTP failure from zero amounts and recovers deliberately", async () => {
  get.mockRejectedValue(new Error("Sin conexión"));
  render(<Page />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Sin conexión");
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
  get.mockResolvedValue(fixture);
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await loaded();
});
it("rejects inconsistent aggregate data rather than showing it", async () => {
  get.mockResolvedValue({
    ...fixture,
    ledger: { ...fixture.ledger, net_change_usd: "99.99" },
  });
  render(<Page />);
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
});
it("ignores late results after filters have changed", async () => {
  let resolve!: (v: unknown) => void;
  get.mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  render(<Page />);
  fireEvent.change(screen.getByLabelText("Hasta", { exact: true }), {
    target: { value: "2026-11-13" },
  });
  await act(async () => resolve(fixture));
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
});
it("retires private data when the credentials and user change", async () => {
  const view = render(<Page />);
  await loaded();
  mockId = "b";
  get.mockRejectedValue(new Error("Unavailable"));
  await act(async () => {
    storeTokens({ access_token: "b", refresh_token: "rb" });
    view.rerender(<Page />);
  });
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
});
it.each(["OPERADOR", "AUDITOR", "REPARTIDOR", "CLIENTE"])(
  "prevents private management requests by %s",
  async (role) => {
    mockRole = role;
    render(<Page />);
    expect(get).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("explains a complete-export limit rejected by the server", async () => {
  get.mockRejectedValue({
    response: {
      status: 409,
      data: { detail: "El rango supera 5000 registros; reduce las fechas" },
    },
  });
  render(<Page />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "reduce las fechas",
  );
  expect(downloadCSV).not.toHaveBeenCalled();
});

it("exports a confirmed empty snapshot with metadata and distinguishes it from an error", async () => {
  const { emptyExact } = await import("../../test-utils/financial-exact");
  get.mockResolvedValue(emptyExact());
  render(<Page />);
  await loaded();
  expect(
    screen.getByText("No hay registros para esta vista del rango confirmado."),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  );
  expect(jest.mocked(downloadCSV).mock.calls[0][0]).toEqual([
    expect.objectContaining({
      filas_completas: 0,
      nota: "Sin registros en el rango confirmado",
    }),
  ]);
});
it("does not restore an old result when a newer query finishes first", async () => {
  let resolve!: (v: unknown) => void;
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  render(<Page />);
  fireEvent.change(screen.getByLabelText("Desde", { exact: true }), {
    target: { value: fixture.date_from },
  });
  get.mockResolvedValue(fixture);
  fireEvent.click(screen.getByRole("button", { name: "Aplicar consulta" }));
  await loaded();
  await act(async () => resolve({ ...fixture, row_count: 999 }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Reporte exacto confirmado" }),
  ).toBeInTheDocument();
});
it("clears the report after the same account loses its management role", async () => {
  const view = render(<Page />);
  await loaded();
  mockRole = "OPERADOR";
  view.rerender(<Page />);
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
  expect(mockRouter.replace).toHaveBeenCalledWith("/login");
});
it("ignores a pending completion after unmounting", async () => {
  let resolve!: (v: unknown) => void;
  get.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = render(<Page />);
  view.unmount();
  await act(async () => resolve(fixture));
  expect(downloadCSV).not.toHaveBeenCalled();
});

it("does not request management data before authentication is confirmed", () => {
  mockAuthenticated = false;
  render(<Page />);
  expect(get).not.toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/login");
});
