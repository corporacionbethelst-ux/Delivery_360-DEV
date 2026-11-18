import { render, screen } from "@testing-library/react";
import {
  normalizeBonusRecords,
  type BonusRecord,
  type BonusRecords,
} from "@/lib/delivery-bonus-exact";
import { BonusBreakdownCard } from "@/components/productivity/BonusBreakdownCard";
import { deliveryBonusService } from "@/services/delivery-bonus-exact.service";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const actor = { user_id: "rider-user", role: "REPARTIDOR" };
function row(patch: Partial<BonusRecord> = {}): BonusRecord {
  return {
    order_id: "order-1",
    delivery_id: "delivery-1",
    rider_id: "rider-1",
    source: "delivery_snapshot",
    status: "COMPLETADA",
    amount: "0.00",
    base: "0.10",
    zone_multiplier: "1.50",
    tier_multiplier: null,
    tier_level: null,
    bonus_type: "SUCCESS",
    snapshot_date: "2026-11-17T12:00:00.000000Z",
    config_warning: null,
    currency: "USD",
    currency_recorded: "USD",
    currency_review: false,
    state_review: false,
    money_review: [],
    ...patch,
  };
}
function report(r = row()): BonusRecords {
  return {
    version: 1,
    scope: "recorded_delivery_bonus_snapshots",
    snapshot_basis: "single_statement_visibility",
    units_basis: "stored_snapshot_only",
    actor,
    order_ids: ["order-1"],
    records: [r],
    generated_at: "2026-11-17T12:01:00.000000Z",
    bank_verified: false,
    available_balance_included: false,
    ledger_credit_included: false,
    content_sha256: "f".repeat(64),
  };
}
beforeEach(() => {
  jest.clearAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "r" });
});
afterEach(() => clearStoredTokens());
it("renders zero as a stored USD bonus instead of hiding it", () => {
  render(
    <BonusBreakdownCard
      snapshot={normalizeBonusRecords(report(), ["order-1"], actor).records[0]}
    />,
  );
  expect(screen.getByText("0,00 USD")).toBeInTheDocument();
  expect(screen.getByText("0,10 USD")).toBeInTheDocument();
  expect(screen.getByText(/1,50 ×/)).toBeInTheDocument();
  expect(screen.queryByText(/Bronce/)).not.toBeInTheDocument();
});
it("preserves historical unknown units without adopting USD from other data", () => {
  render(
    <BonusBreakdownCard
      snapshot={row({
        amount: "17.03",
        currency: null,
        currency_recorded: null,
        base: null,
        zone_multiplier: null,
      })}
    />,
  );
  expect(screen.getByText(/17,03/)).toBeInTheDocument();
  expect(screen.queryByText(/USD|COP/)).not.toBeInTheDocument();
  expect(
    screen.getByText(/Moneda no informada en este bono/),
  ).toBeInTheDocument();
});
it("does not fabricate a total when the stored snapshot is missing", () => {
  render(
    <BonusBreakdownCard
      snapshot={row({
        amount: null,
        base: null,
        zone_multiplier: null,
        bonus_type: null,
        snapshot_date: null,
        currency: null,
        currency_recorded: null,
      })}
      hideIfEmpty={false}
    />,
  );
  expect(screen.getByText(/Sin importe de bono/)).toBeInTheDocument();
  expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
});
it("keeps corruption visible as review instead of zero", () => {
  render(
    <BonusBreakdownCard
      snapshot={row({
        amount: null,
        money_review: [
          { field: "locked_bonus_amount", reason: "IMPORTE_NO_VALIDO" },
        ],
      })}
    />,
  );
  expect(screen.getByText(/Requiere revisión/)).toBeInTheDocument();
  expect(screen.queryByText("0,00 USD")).not.toBeInTheDocument();
});
it.each([
  { amount: 0 },
  { amount: "NaN" },
  { amount: "-0.01" },
  { currency_recorded: null },
  { money_review: [{ field: "unknown", reason: "IMPORTE_NO_VALIDO" }] },
  { source: "order_without_delivery" },
  { state_review: "false" },
])("refuses contradictory snapshot %j", (patch) =>
  expect(() =>
    normalizeBonusRecords(
      report({ ...row(), ...patch } as BonusRecord),
      ["order-1"],
      actor,
    ),
  ).toThrow(),
);
it("refuses a different actor, reordered IDs and duplicate delivery identity", () => {
  expect(() =>
    normalizeBonusRecords(
      { ...report(), actor: { ...actor, user_id: "other" } },
      ["order-1"],
      actor,
    ),
  ).toThrow();
  expect(() => normalizeBonusRecords(report(), ["order-2"], actor)).toThrow();
  expect(() =>
    normalizeBonusRecords(
      {
        ...report(),
        order_ids: ["order-1", "order-2"],
        records: [row(), row({ order_id: "order-2" })],
      },
      ["order-1", "order-2"],
      actor,
    ),
  ).toThrow();
});
it("queries one bounded batch and never falls back to a numeric bonus", async () => {
  jest.mocked(api.get).mockResolvedValue(report());
  await deliveryBonusService.read(["order-1"], actor);
  expect(api.get).toHaveBeenCalledWith("/deliveries/bonuses/exact", {
    params: { order_ids: "order-1" },
  });
  await expect(
    deliveryBonusService.read(
      Array.from({ length: 11 }, (_, i) => "order-" + i),
      actor,
    ),
  ).rejects.toThrow();
  expect(api.get).toHaveBeenCalledTimes(1);
});
it("retires a late bonus response after the session changes", async () => {
  let resolve!: (value: any) => void;
  jest.mocked(api.get).mockReturnValue(new Promise((done) => (resolve = done)));
  const pending = deliveryBonusService.read(["order-1"], actor);
  storeTokens({ access_token: "b", refresh_token: "rb" });
  resolve(report());
  await expect(pending).rejects.toThrow(/sesión cambió/i);
});
