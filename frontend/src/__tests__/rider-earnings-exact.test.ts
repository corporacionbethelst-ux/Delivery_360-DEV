import fixture from "../../test-fixtures/rider-exact.json";
import {
  validateRiderReport,
  validateRiderBalance,
  riderEarningsCSV,
  riderMoney,
} from "@/lib/rider-earnings-exact";
import { riderExactService } from "@/services/rider-earnings-exact.service";
import { api } from "@/lib/api";
import { serializeCSV } from "@/lib/csv-export";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
let mockCurrent = true;
jest.mock("@/lib/private-task", () => ({
  capturePrivateTask: () => ({
    assertCurrent: () => {
      if (!mockCurrent) throw new Error("session changed");
    },
  }),
}));
const owner = fixture.report.user_id,
  copy = () => JSON.parse(JSON.stringify(fixture));
beforeEach(() => {
  jest.resetAllMocks();
  mockCurrent = true;
});
it("validates real exact report and balance with recorded credits and independent reserve calculation", () => {
  const report = validateRiderReport(fixture.report, owner),
    balance = validateRiderBalance(fixture.balance, owner);
  expect(report.lifetime.credit_usd).toBe("25.30");
  expect(report.lifetime.net_change_usd).toBe("25.20");
  expect(balance.available).toBe("15.20");
  expect(balance.reserved).toBe("10.00");
  expect(riderMoney("25.30")).toBe("USD 25,30");
});
it.each([
  { scope: "orders" },
  { order_values_included: true },
  { wallet_cents_included: true },
  { available_balance_included: true },
  { bank_verified: true },
  { export_complete: false },
  { row_count: 999 },
  { excluded_count: 0 },
  { maximum_rows: 5 },
  { today: "2000-01-01" },
  { content_sha256: "bad" },
  { user_id: fixture.report.rider_id },
])("rejects inconsistent ownership or report metadata %j", (change) =>
  expect(() =>
    validateRiderReport({ ...fixture.report, ...change }, owner),
  ).toThrow(),
);
it.each(["lifetime", "day", "week", "daily", "exclusions"])(
  "checks aggregate %s against every loaded row",
  (field) => {
    const v = copy().report;
    if (field === "daily") v.daily[0].credit_usd = "999.99";
    else if (field === "exclusions") v.exclusions[0].count = 0;
    else v[field].credit_usd = "999.99";
    expect(() => validateRiderReport(v, owner)).toThrow();
  },
);
it.each([
  "duplicate",
  "foreign-rider",
  "wrong-sign",
  "unknown-unit",
  "typed-number",
  "changed-status",
])("rejects corrupt source rows %s", (mode) => {
  const v = copy().report,
    row = v.rows.find((r: any) => r.included),
    excluded = v.rows.find((r: any) => !r.included);
  if (mode === "duplicate") v.rows.push(v.rows[0]);
  if (mode === "foreign-rider") row.rider_id = owner;
  if (mode === "wrong-sign") row.delta_usd = "999.99";
  if (mode === "unknown-unit") excluded.amount_usd = "999.00";
  if (mode === "typed-number") row.amount_usd = 0.1;
  if (mode === "changed-status") row.status = "PENDIENTE";
  expect(() => validateRiderReport(v, owner)).toThrow();
});
it.each([
  { available: "15.21" },
  { reserved: "99.00" },
  { currency: "VES" },
  { ledger_integrity: "requires_review" },
  { bank_verified: true },
  { minimum_withdrawal_usd: "1.00" },
  { unverified_financial_count: -1 },
  { available: 15.2 },
])("rejects unsafe available balance %j", (change) =>
  expect(() =>
    validateRiderBalance({ ...fixture.balance, ...change }, owner),
  ).toThrow(),
);
it("exports complete owner-scoped rows, exclusions and fingerprint from one snapshot", () => {
  const v = validateRiderReport(fixture.report, owner),
    csv = riderEarningsCSV(v);
  expect(csv).toHaveLength(v.row_count);
  expect(csv[0]).toMatchObject({
    usuario: owner,
    repartidor: v.rider_id,
    huella_sha256: v.content_sha256,
    filas_completas: 3,
  });
  expect(serializeCSV([{ ...csv[0], description: "=CMD()" }])).toContain(
    "'=CMD()",
  );
});
it("uses only private exact read endpoints and rejects stale sessions and invalid account IDs", async () => {
  jest
    .mocked(api.get)
    .mockImplementation(async (url) =>
      url.includes("balance") ? fixture.balance : fixture.report,
    );
  await riderExactService.report(owner);
  await riderExactService.balance(owner);
  expect(api.get).toHaveBeenNthCalledWith(1, "/financial/riders/me/report");
  expect(api.get).toHaveBeenNthCalledWith(2, "/payouts/balance/exact");
  jest.mocked(api.get).mockImplementation(async () => {
    mockCurrent = false;
    return fixture.report;
  });
  await expect(riderExactService.report(owner)).rejects.toThrow(
    "session changed",
  );
  await expect(riderExactService.report("bad")).rejects.toThrow();
});
