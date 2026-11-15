import { fireEvent, render, screen } from "@testing-library/react";
import {
  AxiosError,
  AxiosHeaders,
  type InternalAxiosRequestConfig,
} from "axios";
import client from "@/lib/api";
import Page from "@/app/(dashboard)/manager/financial/resumen/page";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/financial-exact.json";
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn() }),
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    user: { id: "a", role: "GERENTE" },
    isAuthenticated: true,
  }),
}));
const original = client.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({
  config,
  data,
  status: 200,
  statusText: "OK",
  headers: new AxiosHeaders(),
});
beforeEach(() => {
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
});
afterEach(() => {
  clearStoredTokens();
  client.defaults.adapter = original;
});
it("requests the exact management endpoint without reading Float summary or reconciliation", async () => {
  const urls: string[] = [];
  client.defaults.adapter = async (config) => {
    urls.push(String(config.url));
    return reply(config, fixture);
  };
  render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  expect(urls).toEqual(["/financial/reports/exact?"]);
  expect(
    screen.getByRole("heading", { name: "Resumen financiero exacto" }),
  ).toBeInTheDocument();
});
it.each(["http-error", "contradictory"])(
  "keeps a failure distinct from confirmed totals through real HTTP (%s)",
  async (mode) => {
    let fail = false;
    client.defaults.adapter = async (config) => {
      if (fail && mode === "http-error")
        throw new AxiosError(
          "unavailable",
          AxiosError.ERR_BAD_RESPONSE,
          config,
          undefined,
          { ...reply(config, {}), status: 500 },
        );
      return reply(
        config,
        fail
          ? {
              ...fixture,
              payouts: { ...fixture.payouts, amount_usd: "999.99" },
            }
          : fixture,
      );
    };
    render(<Page />);
    await screen.findByRole("region", { name: "Reporte exacto confirmado" });
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "Aplicar consulta" }));
    await screen.findByRole("alert");
    expect(
      screen.queryByRole("region", { name: "Reporte exacto confirmado" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Exportar CSV completo" }),
    ).toBeDisabled();
  },
);
