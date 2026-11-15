import { render, screen, fireEvent } from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/financial/resumen/page";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/financial-exact.json";
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn() }),
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    user: { id: "a", role: "SUPERADMIN" },
    isAuthenticated: true,
  }),
}));
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  jest.mocked(api.get).mockResolvedValue(fixture);
});
afterEach(() => clearStoredTokens());
it("uses the same exact source snapshot in the summary and links to verified customer collections", async () => {
  render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  expect(
    screen.getByRole("heading", { name: "Resumen financiero exacto" }),
  ).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith("/financial/reports/exact?");
  expect(
    screen.getByRole("link", { name: /Consultar cobros y devoluciones/ }),
  ).toHaveAttribute("href", "/manager/financial/customer-cashbook");
  expect(screen.queryByText("Costos operativos")).not.toBeInTheDocument();
});
it("selects explicit Caracas dates for the quick period and validates the returned range", async () => {
  render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  fireEvent.click(screen.getByRole("button", { name: "Hoy" }));
  await screen.findByRole("alert");
  expect(jest.mocked(api.get).mock.calls[1][0]).toMatch(
    /^\/financial\/reports\/exact\?date_from=\d{4}-\d{2}-\d{2}&date_to=\d{4}-\d{2}-\d{2}$/,
  );
});
it("shows a proper error instead of fabricating zero on first load", async () => {
  jest.mocked(api.get).mockRejectedValue(new Error("No disponible"));
  render(<Page />);
  expect(await screen.findByRole("alert")).toHaveTextContent("No disponible");
  expect(
    screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
  ).not.toBeInTheDocument();
});

it("renders a negative ledger change left of zero without inventing negative bar widths", async () => {
  const { negativeExact } = await import("../../test-utils/financial-exact");
  jest.mocked(api.get).mockResolvedValue(negativeExact());
  const view = render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  const bar = view.container.querySelector<HTMLElement>(
    '[data-direction="negative"]',
  );
  expect(bar).not.toBeNull();
  expect(parseFloat(bar!.style.width)).toBeGreaterThan(0);
  expect(parseFloat(bar!.style.left)).toBeLessThan(50);
  expect(screen.getAllByText("−USD 0,01").length).toBeGreaterThan(0);
});
