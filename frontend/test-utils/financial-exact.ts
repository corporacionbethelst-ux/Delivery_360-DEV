import fixture from "../test-fixtures/financial-exact.json";
import type { ExactReport } from "../src/lib/financial-exact";
export function emptyExact(): ExactReport {
  const copy = JSON.parse(JSON.stringify(fixture));
  copy.rows = [];
  function zero(value: any) {
    if (!value || typeof value !== "object") return;
    for (const [key, v] of Object.entries(value)) {
      if (key.endsWith("_usd")) value[key] = "0.00";
      else if (
        ["count", "row_count", "included_count", "excluded_count"].includes(key)
      )
        value[key] = 0;
      else if (typeof v === "object") zero(v);
    }
  }
  zero(copy);
  return copy;
}
export function negativeExact(): ExactReport {
  const value = emptyExact(),
    row = {
      ...fixture.rows.find((r) => r.transaction_type === "AJUSTE")!,
      amount_usd: "-0.01",
      delta_usd: "-0.01",
    };
  value.rows = [row as ExactReport["rows"][number]];
  value.row_count = 1;
  value.sources.MOVIMIENTO = {
    row_count: 1,
    included_count: 1,
    excluded_count: 0,
  };
  Object.assign(value.ledger, {
    count: 1,
    adjustment_usd: "-0.01",
    net_change_usd: "-0.01",
  });
  Object.assign(
    value.ledger.by_type.find((t) => t.transaction_type === "AJUSTE")!,
    { count: 1, amount_usd: "-0.01", delta_usd: "-0.01" },
  );
  value.daily[0].ledger = {
    count: 1,
    credit_usd: "0.00",
    debit_usd: "0.00",
    adjustment_usd: "-0.01",
    net_change_usd: "-0.01",
  };
  return value;
}
