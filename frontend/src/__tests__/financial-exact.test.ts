import fixture from "../../test-fixtures/financial-exact.json";
import {
  validateExactReport,
  exactReportCSV,
  exactRange,
  financialMoney,
} from "@/lib/financial-exact";
import { exactFinancialService } from "@/services/financial-exact.service";
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
const copy = () => JSON.parse(JSON.stringify(fixture));
beforeEach(() => {
  jest.resetAllMocks();
  mockCurrent = true;
});
it("accepts a real PostgreSQL fixture with separated exact totals and canonical signs", () => {
  const value = validateExactReport(fixture);
  expect(value.orders.total_usd).toBe("0.50");
  expect(value.ledger.net_change_usd).toBe("0.21");
  expect(value.payouts.amount_usd).toBe("0.12");
  expect(value.excluded_count).toBe(1);
  expect(financialMoney("-0.02")).toBe("−USD 0,02");
  expect(
    value.rows.find((r) => r.exclusion_reason === "MONEDA_NO_VERIFICADA")
      ?.amount_usd,
  ).toBeNull();
});
it.each([
  { bank_verified: true },
  { wallet_cents_included: true },
  { customer_cashbook_included: true },
  { version: 1 },
  { export_complete: false },
  { maximum_rows: 1000 },
  { row_count: 999 },
  { excluded_count: 0 },
  { period_start: "2026-11-14T00:00:00.000000Z" },
  { period_end_exclusive: fixture.period_start },
  { content_sha256: "bad" },
  { rows: [fixture.rows[0], fixture.rows[0]] },
  { date_from: "2026-02-30" },
])("rejects false scope, counts or incomplete snapshot %j", (change) =>
  expect(() => validateExactReport({ ...fixture, ...change })).toThrow(),
);
it.each(["orders", "ledger", "payouts", "sources", "daily", "exclusions"])(
  "checks each aggregate against complete source rows: %s",
  (field) => {
    const v = copy();
    if (field === "orders") v.orders.total_usd = "0.51";
    else if (field === "ledger") v.ledger.net_change_usd = "0.22";
    else if (field === "payouts") v.payouts.amount_usd = "0.13";
    else if (field === "sources") v.sources.ORDEN.included_count = 2;
    else if (field === "daily") v.daily[0].ledger.net_change_usd = "9.99";
    else v.exclusions[0].count = 1;
    expect(() => validateExactReport(v)).toThrow();
  },
);
it.each([
  "order-price",
  "ledger-delta",
  "unknown-currency",
  "self-classified",
  "out-of-range",
  "payout-negative",
  "typed-price",
  "source-id",
])("rejects source inconsistency %s", (mode) => {
  const v = copy(),
    o = v.rows.find((r: any) => r.kind === "ORDEN"),
    l = v.rows.find((r: any) => r.kind === "MOVIMIENTO" && r.included),
    p = v.rows.find((r: any) => r.kind === "RETIRO"),
    x = v.rows.find((r: any) => !r.included);
  if (mode === "order-price") o.total_usd = "0.51";
  if (mode === "ledger-delta") l.delta_usd = "99.99";
  if (mode === "unknown-currency") {
    x.included = true;
    x.exclusion_reason = null;
  }
  if (mode === "self-classified") x.amount_usd = "99.99";
  if (mode === "out-of-range") l.occurred_at = "2026-10-01T16:00:00.000000Z";
  if (mode === "payout-negative") p.amount_usd = "-0.01";
  if (mode === "typed-price") o.total_usd = 0.5;
  if (mode === "source-id") o.id = "bad";
  expect(() => validateExactReport(v)).toThrow();
});
it("binds explicit date range, exports all three sources plus exclusions, and preserves safe exact text", () => {
  const value = validateExactReport(fixture, {
    date_from: fixture.date_from,
    date_to: fixture.date_to,
  });
  expect(() =>
    validateExactReport(fixture, { date_from: "2026-11-13" }),
  ).toThrow();
  const csv = exactReportCSV(value);
  expect(csv).toHaveLength(fixture.row_count);
  expect(new Set(csv.map((r) => r.kind))).toEqual(
    new Set(["ORDEN", "MOVIMIENTO", "RETIRO"]),
  );
  expect(csv[0]).toMatchObject({
    huella_sha256: fixture.content_sha256,
    filas_completas: fixture.row_count,
  });
  expect(csv.some((r) => r.exclusion === "Moneda sin verificar")).toBe(true);
  expect(serializeCSV([{ ...csv[0], status: "=CMD()" }])).toContain("'=CMD()");
});
it("rejects impossible or oversized ranges before HTTP and stale sessions after HTTP", async () => {
  expect(() =>
    exactRange({ date_from: "2026-01-01", date_to: "2026-03-01" }),
  ).toThrow();
  expect(() => exactRange({ date_from: "2026-02-30" })).toThrow();
  (api.get as jest.Mock).mockResolvedValue(fixture);
  await exactFinancialService.report({
    date_from: fixture.date_from,
    date_to: fixture.date_to,
  });
  expect(api.get).toHaveBeenCalledWith(
    "/financial/reports/exact?date_from=2026-11-14&date_to=2026-11-14",
  );
  (api.get as jest.Mock).mockImplementation(async () => {
    mockCurrent = false;
    return fixture;
  });
  await expect(exactFinancialService.report()).rejects.toThrow(
    "session changed",
  );
});
