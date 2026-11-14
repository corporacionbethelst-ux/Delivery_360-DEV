import "@testing-library/jest-dom";
import { act, render, screen } from "@testing-library/react";
import Page from "@/app/(dashboard)/rider/earnings/page";
import { financialService } from "@/services/financial.service";
import { payoutService } from "@/services/payout.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

let mockUser = { id: "a", role: "REPARTIDOR" };
const mockRouter = { push: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: true }),
}));
jest.mock("@/services/financial.service", () => ({
  financialService: {
    getMyEarnings: jest.fn(),
    getMyEarningsBreakdown: jest.fn(),
  },
}));
jest.mock("@/services/payout.service", () => ({
  payoutService: { getAvailableBalance: jest.fn() },
}));
jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  BarChart: ({ children }: any) => <div>{children}</div>,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  Cell: () => null,
}));
const summary = {
  rider_id: "r",
  rider_name: "Rider",
  currency: "USD",
  total_earned: 25,
  pending_payout: 15,
  completed_deliveries: 1,
};
const balance = {
  currency: "USD",
  available: 15,
  pending: 10,
  processed: 0,
  total_earned: 25,
  unverified_financial_count: 2,
  unverified_payout_count: 1,
};
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockUser = { id: "a", role: "REPARTIDOR" };
  jest.mocked(financialService.getMyEarnings).mockResolvedValue(summary);
  jest.mocked(payoutService.getAvailableBalance).mockResolvedValue(balance);
  jest
    .mocked(financialService.getMyEarningsBreakdown)
    .mockResolvedValue({ rider_id: "r", items: [] });
  jest.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  clearStoredTokens();
  jest.restoreAllMocks();
});
it("shows the declared USD account and separates historical amounts that require review", async () => {
  jest
    .mocked(financialService.getMyEarningsBreakdown)
    .mockResolvedValue({
      rider_id: "r",
      items: [
        {
          id: "old",
          rider_id: "r",
          amount: 1000,
          balance_after: 1000,
          type: "INGRESO",
          transaction_type: "INGRESO",
          status: "PROCESADO",
          currency: null,
          description: "Histórico",
        },
      ],
    });
  render(<Page />);
  expect(
    await screen.findByRole("heading", { name: "Mis Ganancias" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("2 movimientos anteriores requieren revisión de moneda."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("1 retiros anteriores conservan su moneda sin verificar."),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/moneda no informada/).length).toBeGreaterThan(0);
  expect(
    screen.getByRole("button", { name: "Solicitar Retiro" }),
  ).toBeEnabled();
});
it("does not invent an available balance when the authoritative balance request fails", async () => {
  jest
    .mocked(payoutService.getAvailableBalance)
    .mockRejectedValue(new Error("Saldo no disponible"));
  render(<Page />);
  expect(
    await screen.findByRole("heading", { name: "Saldo USD por confirmar" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Solicitar Retiro" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Total Ganado")).not.toBeInTheDocument();
});
it.each(["COP", undefined])(
  "blocks a withdrawal when the balance does not declare USD (%s)",
  async (currency) => {
    jest
      .mocked(payoutService.getAvailableBalance)
      .mockResolvedValue({ ...balance, currency });
    render(<Page />);
    expect(
      await screen.findByRole("heading", { name: "Saldo USD por confirmar" }),
    ).toBeInTheDocument();
  },
);
it("does not display an unavailable history as an empty ledger", async () => {
  jest
    .mocked(financialService.getMyEarningsBreakdown)
    .mockRejectedValue(new Error("Unavailable"));
  render(<Page />);
  expect(
    await screen.findByText(/El historial no está disponible/),
  ).toBeInTheDocument();
});
it("discards earnings that arrive after the account changes", async () => {
  let resolve!: (value: typeof summary) => void;
  const old = new Promise<typeof summary>((done) => {
    resolve = done;
  });
  jest
    .mocked(financialService.getMyEarnings)
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce({ ...summary, total_earned: 7, pending_payout: 7 });
  jest
    .mocked(payoutService.getAvailableBalance)
    .mockResolvedValueOnce({ ...balance, total_earned: 1000 })
    .mockResolvedValueOnce({ ...balance, total_earned: 7, available: 7 });
  const view = render(<Page />);
  mockUser = { id: "b", role: "REPARTIDOR" };
  view.rerender(<Page />);
  await screen.findByRole("heading", { name: "Mis Ganancias" });
  await act(async () => resolve({ ...summary, total_earned: 1000 }));
  expect(
    screen.getByRole("button", { name: "Solicitar Retiro" }),
  ).toBeDisabled();
  expect(screen.queryByText(/1.000,00/)).not.toBeInTheDocument();
});
