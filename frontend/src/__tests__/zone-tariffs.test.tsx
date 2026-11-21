import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { ZoneTariffEditor } from "@/components/zones/ZoneTariffEditor";
import { api } from "@/lib/api";
import { readZoneTariff, zoneMoneyInput } from "@/lib/zone-tariffs";
import { zoneTariffService } from "@/services/zone-tariff.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), put: jest.fn() } }));
let mockRole = "GERENTE";
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    isAuthenticated: true,
    user: { id: "11111111-1111-4111-8111-111111111111", role: mockRole },
  }),
}));
const id = "11111111-1111-4111-8111-111111111109";
const actor = "11111111-1111-4111-8111-111111111111";
const empty = () => ({
  version: 1,
  scope: "zone_usd_tariff",
  zone_id: id,
  revision: 0,
  currency: null,
  base_usd: null,
  per_km_usd: null,
  updated_at: null,
  updated_by: null,
  application: "zone_configuration_only",
});
const saved = () => ({
  ...empty(),
  revision: 1,
  currency: "USD",
  base_usd: "0.31",
  per_km_usd: "0.10",
  updated_at: "2026-11-21T00:00:00Z",
  updated_by: actor,
});
beforeEach(() => {
  jest.resetAllMocks();
  mockRole = "GERENTE";
  clearStoredTokens();
  storeTokens({ access_token: "test", refresh_token: "refresh" });
  jest.mocked(api.get).mockResolvedValue(empty());
});
afterEach(() => clearStoredTokens());
it.each(["-1", "1e2", "0.001", "1,000.00", "100000000.00", ""])(
  "rejects ambiguous money %s",
  (value) => {
    expect(() => zoneMoneyInput(value)).toThrow();
  },
);
it.each([0, 0.31, true, null])(
  "rejects numeric or missing canonical money %s",
  (value) => {
    expect(() => readZoneTariff({ ...saved(), base_usd: value }, id)).toThrow();
  },
);
it.each([
  { zone_id: actor },
  { revision: -1 },
  { revision: 0 },
  { currency: "VES" },
  { updated_by: null },
  { application: "order_pricing" },
])("rejects mismatched provenance %j", (change) => {
  expect(() => readZoneTariff({ ...saved(), ...change }, id)).toThrow();
});
it("distinguishes absent configuration from an explicit zero without Float conversion", () => {
  expect(readZoneTariff(empty(), id).base_usd).toBeNull();
  expect(readZoneTariff({ ...saved(), base_usd: "0.00" }, id).base_usd).toBe(
    "0.00",
  );
  expect(zoneMoneyInput("0,31")).toBe("0.31");
  expect(zoneMoneyInput("99999999.99")).toBe("99999999.99");
});
it("validates input locally then saves decimal strings with the loaded revision", async () => {
  jest.mocked(api.put).mockResolvedValue(saved());
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByText(/Tarifas USD sin configurar/);
  fireEvent.click(screen.getByRole("button", { name: "Guardar tarifas USD" }));
  await screen.findByRole("alert");
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Tarifa base USD"), {
    target: { value: "0,31" },
  });
  fireEvent.change(screen.getByLabelText("Tarifa por kilómetro USD"), {
    target: { value: "0.10" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Guardar tarifas USD" }));
  await screen.findByText("Tarifas USD guardadas y confirmadas.");
  expect(api.put).toHaveBeenCalledWith(`/zones/${id}/tariff/exact`, {
    currency: "USD",
    expected_revision: 0,
    base_usd: "0.31",
    per_km_usd: "0.10",
  });
  await screen.findByText("USD 0,31");
});
it("a failed read is not zero and cannot enable saving", async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error("503"));
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByRole("alert");
  expect(screen.queryByText("USD 0,00")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Guardar tarifas USD" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Consultar tarifas actuales" }),
  );
  await screen.findByText(/Tarifas USD sin configurar/);
});
it("an ambiguous or conflicting save requires a read and cannot repeat a mutation", async () => {
  jest.mocked(api.get).mockResolvedValue(saved());
  jest.mocked(api.put).mockRejectedValueOnce({ response: { status: 409 } });
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByText("USD 0,31");
  fireEvent.click(screen.getByRole("button", { name: "Guardar tarifas USD" }));
  await screen.findByRole("alert");
  const button = screen.getByRole("button", { name: "Guardar tarifas USD" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(api.put).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Consultar tarifas actuales" }),
  );
  await waitFor(() => expect(button).toBeEnabled());
  expect(api.put).toHaveBeenCalledTimes(1);
});
it("operator reads the canonical tariff without a write control", async () => {
  mockRole = "OPERADOR";
  jest.mocked(api.get).mockResolvedValue(saved());
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByText("USD 0,31");
  expect(
    screen.queryByRole("button", { name: "Guardar tarifas USD" }),
  ).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});
it("retires old-account continuations after credentials change", async () => {
  let resolve!: (value: unknown) => void;
  jest
    .mocked(api.get)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce(empty());
  render(<ZoneTariffEditor zoneId={id} />);
  await act(async () =>
    storeTokens({ access_token: "next", refresh_token: "next-refresh" }),
  );
  await screen.findByText(/Tarifas USD sin configurar/);
  await act(async () => resolve(saved()));
  expect(screen.queryByText("USD 0,31")).not.toBeInTheDocument();
});
it("rejects batch duplicates or foreign identities rather than inventing missing tariffs", async () => {
  for (const items of [[empty(), empty()], [{ ...empty(), zone_id: actor }]]) {
    jest
      .mocked(api.get)
      .mockResolvedValueOnce({ version: 1, scope: "zone_usd_tariffs", items });
    await expect(zoneTariffService.getMany([id])).rejects.toThrow();
  }
});
it("does not accept an acknowledgement of another revision or amount", async () => {
  jest.mocked(api.put).mockResolvedValue({ ...saved(), base_usd: "0.32" });
  await expect(zoneTariffService.save(id, 0, "0.31", "0.10")).rejects.toThrow(
    /confirmar/,
  );
});

it("does not submit twice while a tariff save is pending", async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.get).mockResolvedValue(saved());
  jest.mocked(api.put).mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByText("USD 0,31");
  const button = screen.getByRole("button", { name: "Guardar tarifas USD" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(api.put).toHaveBeenCalledTimes(1);
  await act(async () => resolve({ ...saved(), revision: 2 }));
  await screen.findByText("Tarifas USD guardadas y confirmadas.");
});
it("rejects a save acknowledgement attributed to another actor", async () => {
  jest.mocked(api.get).mockResolvedValue(saved());
  jest
    .mocked(api.put)
    .mockResolvedValue({ ...saved(), revision: 2, updated_by: id });
  render(<ZoneTariffEditor zoneId={id} />);
  await screen.findByText("USD 0,31");
  fireEvent.click(screen.getByRole("button", { name: "Guardar tarifas USD" }));
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "Guardar tarifas USD" }),
  ).toBeDisabled();
  expect(
    screen.queryByText("Tarifas USD guardadas y confirmadas."),
  ).not.toBeInTheDocument();
});
