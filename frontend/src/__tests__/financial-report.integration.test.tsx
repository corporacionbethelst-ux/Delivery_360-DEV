import { act, fireEvent, render, screen } from "@testing-library/react";
import axios, {
  AxiosError,
  AxiosHeaders,
  type InternalAxiosRequestConfig,
} from "axios";
import client from "@/lib/api";
import Page from "@/app/(dashboard)/manager/financial/reports/page";
import { downloadCSV } from "@/lib/csv-export";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/financial-exact.json";
const mockRouter = { replace: jest.fn() };
let mockUser = { id: "a", role: "GERENTE" };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: true }),
}));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn(() => true) }));
const original = client.defaults.adapter,
  originalRefresh = axios.defaults.adapter;
const response = (config: InternalAxiosRequestConfig, data: unknown) => ({
  config,
  data,
  status: 200,
  statusText: "OK",
  headers: new AxiosHeaders(),
});
beforeEach(() => {
  jest.clearAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockUser = { id: "a", role: "GERENTE" };
  client.defaults.adapter = async (config) => response(config, fixture);
});
afterEach(() => {
  clearStoredTokens();
  client.defaults.adapter = original;
  axios.defaults.adapter = originalRefresh;
});
it("exports one complete snapshot through Axios/API/service using one authenticated GET", async () => {
  const requests: string[] = [];
  client.defaults.adapter = async (config) => {
    expect(config.method).toBe("get");
    expect(config.headers.get("Authorization")).toBe("Bearer a");
    requests.push(String(config.url));
    return response(config, fixture);
  };
  render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  fireEvent.click(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  );
  await screen.findByText(/CSV generado con/);
  expect(requests).toEqual(["/financial/reports/exact?"]);
  expect(jest.mocked(downloadCSV).mock.calls[0][0]).toHaveLength(
    fixture.row_count,
  );
});
it("retires an HTTP result if the account changes in the response interceptor", async () => {
  let switched = false;
  const interceptor = client.interceptors.response.use((result) => {
    if (!switched) {
      switched = true;
      mockUser = { id: "b", role: "GERENTE" };
      storeTokens({ access_token: "b", refresh_token: "rb" });
    }
    return result;
  });
  try {
    render(<Page />);
    await screen.findByRole("region", { name: "Reporte exacto confirmado" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(client.defaults.adapter).toBeDefined();
    expect(downloadCSV).not.toHaveBeenCalled();
  } finally {
    client.interceptors.response.eject(interceptor);
  }
});
it("accepts a verified same-account token refresh while requesting exact sources", async () => {
  const tokens: string[] = [];
  client.defaults.adapter = async (config) => {
    tokens.push(String(config.headers.get("Authorization")));
    if (config.headers.get("Authorization") === "Bearer a")
      throw new AxiosError(
        "expired",
        AxiosError.ERR_BAD_REQUEST,
        config,
        undefined,
        { ...response(config, {}), status: 401 },
      );
    return response(config, fixture);
  };
  axios.defaults.adapter = async (config) =>
    response(config, {
      access_token: "rotated-a",
      refresh_token: "rotated-ra",
    });
  render(<Page />);
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
  expect(tokens).toEqual(["Bearer a", "Bearer rotated-a"]);
  expect(localStorage.getItem("access_token")).toBe("rotated-a");
});
it("blocks CSV after a real HTTP failure and recovers with an explicit retry", async () => {
  let fail = true;
  client.defaults.adapter = async (config) => {
    if (fail)
      throw new AxiosError(
        "unavailable",
        AxiosError.ERR_BAD_RESPONSE,
        config,
        undefined,
        { ...response(config, { detail: "No disponible" }), status: 503 },
      );
    return response(config, fixture);
  };
  render(<Page />);
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
  expect(downloadCSV).not.toHaveBeenCalled();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByRole("region", { name: "Reporte exacto confirmado" });
});
