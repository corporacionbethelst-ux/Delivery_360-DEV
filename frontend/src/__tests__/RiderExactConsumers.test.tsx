import { act, render, screen } from "@testing-library/react";
import Dashboard from "@/app/(dashboard)/rider/page";
import Productivity from "@/app/(dashboard)/rider/productivity/page";
import { api } from "@/lib/api";
import { riderService } from "@/services/rider.service";
import { orderService } from "@/services/order.service";
import { deliveryService } from "@/services/delivery.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/rider-exact.json";
let mockRole = "REPARTIDOR",
  mockId = fixture.report.user_id;
const mockRouter = { push: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    user: {
      id: mockId,
      role: mockRole,
      first_name: "Prueba",
      last_name: "Rider",
    },
    isAuthenticated: true,
  }),
}));
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
jest.mock("@/services/rider.service", () => ({
  riderService: { getProfile: jest.fn() },
}));
jest.mock("@/services/order.service", () => ({
  orderService: { getAll: jest.fn() },
}));
jest.mock("@/services/delivery.service", () => ({
  deliveryService: { getAll: jest.fn() },
}));
jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  BarChart: ({ children }: any) => <div>{children}</div>,
  AreaChart: ({ children }: any) => <div>{children}</div>,
  PieChart: ({ children }: any) => <div>{children}</div>,
  Pie: () => null,
  Bar: () => null,
  Area: () => null,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockId = fixture.report.user_id;
  mockRole = "REPARTIDOR";
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      url.includes("balance") ? fixture.balance : fixture.report,
    );
  jest
    .mocked(riderService.getProfile)
    .mockResolvedValue({
      id: fixture.report.rider_id,
      is_online: false,
      level: 1,
      total_points: 0,
    } as any);
  jest
    .mocked(orderService.getAll)
    .mockResolvedValue([
      {
        id: "billing-only",
        status: "ENTREGADO",
        total: 999999,
        subtotal: 999999,
        delivery_fee: 0,
        currency: "USD",
        created_at: fixture.report.generated_at,
        delivered_at: fixture.report.generated_at,
      },
    ] as any);
  jest.mocked(deliveryService.getAll).mockResolvedValue({ items: [] } as any);
  jest.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  clearStoredTokens();
  jest.restoreAllMocks();
});
it("dashboard uses recorded day/week credit rather than delivered order value or lifetime fallback", async () => {
  render(<Dashboard />);
  expect(await screen.findByText("USD 25,30")).toBeInTheDocument();
  expect(screen.getByText("USD 0,00")).toBeInTheDocument();
  expect(screen.getByText("USD 15,20")).toBeInTheDocument();
  expect(screen.queryByText(/999\.999|999999/)).not.toBeInTheDocument();
  expect(jest.mocked(api.get).mock.calls.map((c) => c[0])).toEqual([
    "/financial/riders/me/report",
    "/payouts/balance/exact",
  ]);
});
it("dashboard never falls back to orders or a fictitious zero after a financial request fails", async () => {
  jest.mocked(api.get).mockRejectedValue(new Error("Sin conexión"));
  render(<Dashboard />);
  expect((await screen.findAllByText("Por confirmar")).length).toBe(3);
  expect(screen.queryByText(/999\.999|999999/)).not.toBeInTheDocument();
  expect(
    screen.getByText(/Las órdenes no se usan para inventar/),
  ).toBeInTheDocument();
});
it("productivity displays the exact recorded lifetime credit independently of order invoice amounts", async () => {
  render(<Productivity />);
  expect(await screen.findByText("USD 25,30")).toBeInTheDocument();
  expect(screen.getByText("Créditos USD registrados")).toBeInTheDocument();
  expect(jest.mocked(api.get).mock.calls.map((c) => c[0])).toEqual([
    "/financial/riders/me/report",
  ]);
  expect(screen.queryByText(/999\.999|999999/)).not.toBeInTheDocument();
});
it.each([Dashboard, Productivity])(
  "rejects financial data after an identity change",
  async (Page) => {
    let finish!: (v: unknown) => void;
    jest.mocked(api.get).mockReturnValue(
      new Promise((r) => {
        finish = r;
      }),
    );
    const view = render(<Page />);
    mockId = fixture.report.rider_id;
    jest.mocked(api.get).mockRejectedValue(new Error("Otra cuenta"));
    await act(async () => {
      storeTokens({ access_token: "b", refresh_token: "rb" });
      view.rerender(<Page />);
    });
    await act(async () => finish(fixture.report));
    expect(screen.queryByText("USD 25,30")).not.toBeInTheDocument();
  },
);
it.each([Dashboard, Productivity])(
  "does not read rider financial data for a manager",
  (Page) => {
    mockRole = "GERENTE";
    render(<Page />);
    expect(api.get).not.toHaveBeenCalled();
    expect(riderService.getProfile).not.toHaveBeenCalled();
    expect(mockRouter.push).toHaveBeenCalledWith("/login");
  },
);
