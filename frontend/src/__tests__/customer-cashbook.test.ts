import {
  cashReport,
  cashRows,
} from "../../test-utils/customer-cashbook-fixtures";
import {
  validateCashReport,
  cashCents,
  cashText,
  cashbookCSV,
  cashFilters,
} from "@/lib/customer-cashbook";
import { customerCashbookService } from "@/services/customer-cashbook.service";
import { api } from "@/lib/api";
import { serializeCSV } from "@/lib/csv-export";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
let mockCurrent = true;
jest.mock("@/lib/private-task", () => ({
  capturePrivateTask: () => ({
    assertCurrent: () => {
      if (!mockCurrent) throw new Error("Session changed");
    },
  }),
}));
beforeEach(() => {
  jest.resetAllMocks();
  mockCurrent = true;
});
it("checks exact VES cumulative rounding, grouped totals, empty and negative nets", () => {
  for (const rows of [cashRows, [], [cashRows[0]]])
    expect(validateCashReport(cashReport(rows))).toEqual(cashReport(rows));
  expect(cashReport([cashRows[0]]).summary.net_usd).toBe("-0.01");
  expect(cashText("-0.01")).toBe("−USD 0,01");
  expect(cashCents("99999999999999999999999.99")).toBe(
    BigInt("9999999999999999999999999"),
  );
});
it.each([
  { bank_verified: true },
  { export_complete: false },
  { maximum_rows: 100 },
  { scope: "bank_balance" },
  { date_from: "2026-02-30" },
  { date_to: "2026-11-15" },
  { period_start: "2026-11-14T00:00:00.000000Z" },
  { period_end_exclusive: "2026-11-14T04:00:00.000000Z" },
  { content_sha256: "bad" },
  { filters: { method: "EFECTIVO", currency: null, source_key: null } },
  { rows: [cashRows[0], cashRows[0]] },
  { summary: { ...cashReport().summary, net_usd: "0.50" } },
  { currencies: [] },
  { methods: [] },
  { daily: [] },
])("rejects malformed report or mismatched filters %j", (change) =>
  expect(() => validateCashReport({ ...cashReport(), ...change })).toThrow(),
);
it.each([
  { amount_original: "0.02" },
  { amount_usd: 0.01 },
  { prior_refunded_original: "0.01" },
  { bcv_rate: "2.00000000" },
  { verified_by: cashRows[0].declared_by },
  { verified_at: "2026-11-14T18:00:00.000000Z" },
  { declared_at: "2026-11-14T16:03:00.000000Z" },
  { operation_date: "2026-11-13" },
  { refund_id: null },
  { bcv_rate_id: null },
  { method: "CARD" },
  { source_key: " caja " },
  { reference_key: "\n" },
  { original_currency: "USD" },
  { collection_amount_original: "0.74" },
])("rejects incoherent original source %j", (change) =>
  expect(() =>
    validateCashReport(
      cashReport([{ ...cashRows[0], ...change } as (typeof cashRows)[0]]),
    ),
  ).toThrow(),
);
it("validates every grouped total and zero day, rather than only summary", () => {
  for (const field of ["currencies", "methods", "daily"] as const) {
    const value = cashReport();
    value[field][0].net_usd = "1.00";
    expect(() => validateCashReport(value)).toThrow();
  }
  const value = cashReport();
  value.daily[0].date = "2026-11-13";
  expect(() => validateCashReport(value)).toThrow();
});
it("exports every row from the same snapshot with metadata and protects spreadsheet formulas", () => {
  const value = cashReport(),
    rows = cashbookCSV(value);
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({
    huella_sha256: value.content_sha256,
    desde_caracas: value.date_from,
    filas_completas: 2,
    amount_original: "0.01",
  });
  expect(cashbookCSV(cashReport([]))[0].nota).toMatch(/Sin movimientos/);
  expect(serializeCSV([{ ...rows[0], source_key: "=CMD()" }])).toContain(
    "'=CMD()",
  );
});
it("canonicalizes filters, binds the response and rejects stale sessions", async () => {
  expect(cashFilters({ source_key: " caja principal " })).toEqual({
    source_key: "CAJA PRINCIPAL",
  });
  (api.get as jest.Mock).mockResolvedValue(cashReport());
  await customerCashbookService.report({
    date_from: "2026-11-14",
    date_to: "2026-11-14",
  });
  expect(api.get).toHaveBeenCalledWith(
    "/customer-cashbook/report?date_from=2026-11-14&date_to=2026-11-14",
  );
  await expect(
    customerCashbookService.report({ currency: "USD" }),
  ).rejects.toThrow();
  (api.get as jest.Mock).mockImplementation(async () => {
    mockCurrent = false;
    return cashReport();
  });
  await expect(customerCashbookService.report()).rejects.toThrow(
    "Session changed",
  );
});
