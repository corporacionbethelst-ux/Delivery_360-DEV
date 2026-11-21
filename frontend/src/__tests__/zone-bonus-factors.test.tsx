import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import { ZoneBonusFactorEditor } from "@/components/zones/ZoneBonusFactorEditor";
import {
  factorInput,
  readFactorSnapshot,
  readZoneFactor,
} from "@/lib/zone-bonus-factors";
import { zoneBonusFactorService } from "@/services/zone-bonus-factor.service";
import { normalizeBonusRecords } from "@/lib/delivery-bonus-exact";
import { BonusBreakdownCard } from "@/components/productivity/BonusBreakdownCard";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), put: jest.fn() } }));
let mockRole = "GERENTE";
const actor = "11111111-1111-4111-8111-111111111111",
  id = "11111111-1111-4111-8111-111111111110",
  precise = "1.234567890123456789";
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    isAuthenticated: true,
    user: { id: "11111111-1111-4111-8111-111111111111", role: mockRole },
  }),
}));
const empty = () => ({
  version: 1,
  scope: "zone_bonus_factor",
  zone_id: id,
  revision: 0,
  factor: null,
  legacy_factor: "1.25",
  unit: "dimensionless",
  updated_at: null,
  updated_by: null,
  application: "prospective_delivery_bonus",
});
const saved = () => ({
  ...empty(),
  revision: 1,
  factor: precise,
  updated_at: "2026-11-21T00:00:00Z",
  updated_by: actor,
});
const frozen = () => ({
  version: 1,
  unit: "dimensionless",
  zone_id: id,
  zone_revision: 1,
  zone_factor: precise,
  tier_factor: "1.15",
  basis: "declared_exact",
});
beforeEach(() => {
  jest.resetAllMocks();
  mockRole = "GERENTE";
  clearStoredTokens();
  storeTokens({ access_token: "factor-test", refresh_token: "factor-refresh" });
  jest.mocked(api.get).mockResolvedValue(empty());
});
afterEach(() => clearStoredTokens());
it.each(["0", "-1", "5.1", "1e0", "1.1234567890123456789", ""])(
  "rejects invalid factor %s",
  (value) => {
    expect(() => factorInput(value)).toThrow();
  },
);
it("preserves 18 fractional digits and normalizes comma without Number", () => {
  expect(factorInput("1,234567890123456789")).toBe(precise);
  expect(factorInput("5.000")).toBe("5");
  expect(factorInput("0.100")).toBe("0.1");
});
it.each([
  { factor: 1.2 },
  { factor: "5.1" },
  { unit: "USD" },
  { zone_id: actor },
  { revision: -1 },
  { updated_by: null },
])("rejects inconsistent factor configurations %j", (patch) => {
  expect(() => readZoneFactor({ ...saved(), ...patch }, id)).toThrow();
});
it.each([
  { zone_factor: 1.2 },
  { zone_factor: "NaN" },
  { basis: "USD" },
  { zone_revision: true },
  { zone_id: null },
  { tier_factor: "1.2" },
  { extra: 1 },
])("rejects contradictory frozen factors %j", (patch) => {
  expect(() => readFactorSnapshot({ ...frozen(), ...patch })).toThrow();
});
it("does not adopt the compatibility value as a confirmed factor", async () => {
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText(/Factor decimal sin confirmar/);
  expect(screen.getByLabelText("Factor decimal de zona")).toHaveValue("");
  expect(screen.getByText(/1,25 × \(compatibilidad\)/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  );
  await screen.findByRole("alert");
  expect(api.put).not.toHaveBeenCalled();
});
it("saves exact text with a revision and displays every confirmed digit", async () => {
  jest.mocked(api.put).mockResolvedValue(saved());
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText(/Factor decimal sin confirmar/);
  fireEvent.change(screen.getByLabelText("Factor decimal de zona"), {
    target: { value: "1,234567890123456789" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  );
  await screen.findByText("Factor decimal guardado y confirmado.");
  expect(api.put).toHaveBeenCalledWith(`/zones/${id}/bonus-factor/exact`, {
    expected_revision: 0,
    factor: precise,
  });
  await screen.findByText("1,234567890123456789 ×");
});
it("failed reads never invent a factor of one and cannot enable writing", async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error("503"));
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByRole("alert");
  expect(screen.queryByText("1 ×")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  ).toBeDisabled();
});
it("a conflicting or ambiguous save requires a read before another mutation", async () => {
  jest.mocked(api.get).mockResolvedValue(saved());
  jest.mocked(api.put).mockRejectedValueOnce({ response: { status: 409 } });
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText("1,234567890123456789 ×");
  fireEvent.click(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  );
  await screen.findByRole("alert");
  const button = screen.getByRole("button", { name: "Guardar factor decimal" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(api.put).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Consultar factor actual" }),
  );
  await waitFor(() => expect(button).toBeEnabled());
  expect(api.put).toHaveBeenCalledTimes(1);
});
it("operator reads without a write control", async () => {
  mockRole = "OPERADOR";
  jest.mocked(api.get).mockResolvedValue(saved());
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText("1,234567890123456789 ×");
  expect(
    screen.queryByRole("button", { name: "Guardar factor decimal" }),
  ).not.toBeInTheDocument();
});
it("retires an old-account continuation after credentials change", async () => {
  let resolve!: (v: unknown) => void;
  jest
    .mocked(api.get)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce(empty());
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await act(async () =>
    storeTokens({ access_token: "next", refresh_token: "next-refresh" }),
  );
  await screen.findByText(/Factor decimal sin confirmar/);
  await act(async () => resolve(saved()));
  expect(screen.queryByText("1,234567890123456789 ×")).not.toBeInTheDocument();
});
it("rejects another amount or revision in a save acknowledgement", async () => {
  jest.mocked(api.put).mockResolvedValue({ ...saved(), factor: "2" });
  await expect(zoneBonusFactorService.save(id, 0, precise)).rejects.toThrow();
});
it("normalizes and renders the immutable full factor instead of its rounded alias", () => {
  const identity = { user_id: actor, role: "GERENTE" };
  const row = {
    order_id: "order-1",
    delivery_id: "delivery-1",
    rider_id: "rider-1",
    source: "delivery_snapshot",
    status: "COMPLETADA",
    amount: "3.55",
    base: "2.50",
    zone_multiplier: "1.23",
    tier_multiplier: "1.15",
    tier_level: "PLATINO",
    bonus_type: "SUCCESS",
    snapshot_date: "2026-11-21T00:00:00.000000Z",
    config_warning: null,
    currency: "USD",
    currency_recorded: "USD",
    currency_review: false,
    state_review: false,
    money_review: [],
    factor_snapshot: frozen(),
  };
  const response = {
    version: 1,
    scope: "recorded_delivery_bonus_snapshots",
    snapshot_basis: "single_statement_visibility",
    units_basis: "stored_snapshot_only",
    actor: identity,
    order_ids: ["order-1"],
    records: [row],
    generated_at: "2026-11-21T00:01:00.000000Z",
    bank_verified: false,
    available_balance_included: false,
    ledger_credit_included: false,
    content_sha256: "a".repeat(64),
  };
  const value = normalizeBonusRecords(response, ["order-1"], identity)
    .records[0];
  expect(value.zone_multiplier).toBe(precise);
  render(<BonusBreakdownCard snapshot={value} />);
  expect(screen.getByText("1,234567890123456789 ×")).toBeInTheDocument();
  expect(
    screen.getByText(/Factor de zona confirmado · revisión 1/),
  ).toBeInTheDocument();
  expect(screen.getByText("3,55 USD")).toBeInTheDocument();
});

it("blocks duplicate factor submissions while awaiting confirmation", async () => {
  let resolve!: (v: unknown) => void;
  jest.mocked(api.get).mockResolvedValue(saved());
  jest.mocked(api.put).mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText("1,234567890123456789 ×");
  const button = screen.getByRole("button", { name: "Guardar factor decimal" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(api.put).toHaveBeenCalledTimes(1);
  await act(async () => resolve({ ...saved(), revision: 2 }));
  await screen.findByText("Factor decimal guardado y confirmado.");
});
it("does not accept a save attributed to another actor", async () => {
  jest.mocked(api.get).mockResolvedValue(saved());
  jest
    .mocked(api.put)
    .mockResolvedValue({ ...saved(), revision: 2, updated_by: id });
  render(<ZoneBonusFactorEditor zoneId={id} />);
  await screen.findByText("1,234567890123456789 ×");
  fireEvent.click(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  );
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "Guardar factor decimal" }),
  ).toBeDisabled();
  expect(
    screen.queryByText("Factor decimal guardado y confirmado."),
  ).not.toBeInTheDocument();
});
