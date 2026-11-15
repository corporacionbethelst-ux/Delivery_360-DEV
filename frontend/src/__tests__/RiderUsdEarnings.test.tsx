import { act, render, screen, fireEvent } from "@testing-library/react";
import Page from "@/app/(dashboard)/rider/earnings/page";
import { api } from "@/lib/api";
import { downloadCSV } from "@/lib/csv-export";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/rider-exact.json";
let mockUser = { id: fixture.report.user_id, role: "REPARTIDOR" };
const mockRouter = { push: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: true }),
}));
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get),
  loaded = () =>
    screen.findByRole("region", { name: "Ganancias exactas confirmadas" });
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockUser = { id: fixture.report.user_id, role: "REPARTIDOR" };
  get.mockImplementation(async (url) =>
    url.includes("balance") ? fixture.balance : fixture.report,
  );
  jest.mocked(downloadCSV).mockReturnValue(true);
});
afterEach(() => clearStoredTokens());
it("shows exact USD earnings, reserves and unverified history without showing its amounts", async () => {
  render(<Page />);
  await loaded();
  expect(
    screen.getByText("1 movimientos anteriores requieren revisión de moneda."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("1 retiros anteriores conservan su moneda sin verificar."),
  ).toBeInTheDocument();
  expect(screen.queryByText(/999,00/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Solicitar Retiro" }),
  ).toBeEnabled();
  expect(screen.getAllByText("USD 25,30").length).toBeGreaterThan(0);
});
it("keeps recorded earnings visible but blocks withdrawals if available balance cannot be confirmed", async () => {
  get.mockImplementation(async (url) => {
    if (url.includes("balance")) throw new Error("Saldo no disponible");
    return fixture.report;
  });
  render(<Page />);
  await loaded();
  expect(
    screen.getByRole("heading", { name: "Saldo USD por confirmar" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Solicitar Retiro" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Exportar movimientos" }),
  ).toBeEnabled();
});
it("keeps unavailable history distinct from a genuinely empty ledger", async () => {
  get.mockImplementation(async (url) => {
    if (url.includes("/report")) throw new Error("Historial no disponible");
    return fixture.balance;
  });
  render(<Page />);
  expect(
    await screen.findByRole("heading", { name: "Ganancias por confirmar" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Aún no hay movimientos financieros para mostrar."),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Solicitar Retiro" }),
  ).toBeDisabled();
});
it.each(["COP", undefined])(
  "rejects available money without authoritative USD (%s)",
  async (currency) => {
    get.mockImplementation(async (url) =>
      url.includes("balance")
        ? { ...fixture.balance, currency }
        : fixture.report,
    );
    render(<Page />);
    await loaded();
    expect(
      screen.getByRole("heading", { name: "Saldo USD por confirmar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Solicitar Retiro" }),
    ).toBeDisabled();
  },
);
it("exports the whole verified response without another read", async () => {
  render(<Page />);
  await loaded();
  const reads = get.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "Exportar movimientos" }));
  expect(downloadCSV).toHaveBeenCalledWith(
    expect.arrayContaining([
      expect.objectContaining({
        filas_completas: 3,
        usuario: fixture.report.user_id,
      }),
    ]),
    "mis_movimientos_usd",
  );
  expect(get).toHaveBeenCalledTimes(reads);
});
it("retires a late result after an account change", async () => {
  let resolve!: (v: unknown) => void;
  get.mockImplementation(async (url) =>
    url.includes("balance")
      ? fixture.balance
      : new Promise((r) => {
          resolve = r;
        }),
  );
  const view = render(<Page />);
  mockUser = { id: fixture.report.rider_id, role: "REPARTIDOR" };
  get.mockRejectedValue(new Error("Otra cuenta"));
  await act(async () => {
    storeTokens({ access_token: "b", refresh_token: "rb" });
    view.rerender(<Page />);
  });
  await screen.findByRole("heading", { name: "Ganancias por confirmar" });
  await act(async () => resolve(fixture.report));
  expect(
    screen.queryByRole("region", { name: "Ganancias exactas confirmadas" }),
  ).not.toBeInTheDocument();
});
it.each(["SUPERADMIN", "GERENTE", "OPERADOR", "AUDITOR", "CLIENTE"])(
  "does not read private rider earnings as %s",
  (role) => {
    mockUser = { id: fixture.report.user_id, role };
    render(<Page />);
    expect(get).not.toHaveBeenCalled();
    expect(mockRouter.push).toHaveBeenCalledWith("/login");
  },
);
