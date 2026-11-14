import {
  canonicalDecimal,
  exactVes,
  moneyText,
  validateCurrency,
  validateRate,
  validateQuote,
} from "@/lib/currency";
import { context, rate, quote } from "../../test-utils/currency-fixtures";

it.each([
  ["12,34", "12.34"],
  ["0.01", "0.01"],
  ["0", "0"],
])("normalizes decimal input %s without a float", (input, expected) => {
  expect(canonicalDecimal(input, 2, 12)).toBe(expected);
});
it.each([
  "1.234,56",
  "1,234.56",
  "-1",
  "NaN",
  "Infinity",
  "1e2",
  "01.2",
  "1.234",
  "1000000000000",
])("rejects ambiguous or unrepresentable USD %s", (input) => {
  expect(() => canonicalDecimal(input, 2, 12)).toThrow();
});
it.each([
  ["0.01", "1.50000000", "0.02"],
  ["12.34", "40.12345678", "495.12"],
  ["999999999999.99", "999999999.99999999", "999999999999989990000.00"],
])("reproduces the exact saved conversion %#", (usd, r, ves) => {
  expect(exactVes(usd, r)).toBe(ves);
});
it("formats large stored values without rounding through Number", () => {
  expect(moneyText("999999999999989990000.00", "VES")).toBe(
    "Bs. 999.999.999.999.989.990.000,00",
  );
  expect(moneyText("0.01", "USD")).toBe("USD 0,01");
});
it.each([
  { ves_per_usd: "0.00000000" },
  { ves_per_usd: 1.5 },
  { source: "fallback" },
  { automatically_verified: true },
  { source_url: "https://another.example/" },
  { reference_date: "2026-11-15" },
  { revision: 0 },
  { valid_on: "2026-02-30" },
])("rejects an invalid or falsely verified rate %#", (changes) => {
  expect(() => validateRate({ ...rate, ...changes })).toThrow();
});
it("requires the current reference to match the server day and loaded history", () => {
  expect(validateCurrency(context)).toEqual(context);
  expect(() => validateCurrency({ ...context, today: "2026-11-15" })).toThrow();
  expect(() => validateCurrency({ ...context, rates: [] })).toThrow();
  expect(validateCurrency({ ...context, current_rate: null })).toMatchObject({
    current_rate: null,
  });
});
it.each([
  { amount_ves: "0.01" },
  { payment_confirmed: true },
  { base_currency: "COP" },
  { quotation_only: false },
  { amount_usd: 0.01 },
  { amount_usd: "NaN" },
])("rejects a changed quote or false payment %#", (changes) => {
  expect(() => validateQuote({ ...quote, ...changes })).toThrow();
});
