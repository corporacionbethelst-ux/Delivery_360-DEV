import type {
  CashReport,
  CashTotals,
  CashRow,
} from "../src/lib/customer-cashbook";
const uuid = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const cashRows: CashRow[] = [
  {
    key: `DEVOLUCION:${uuid(1)}`,
    kind: "DEVOLUCION",
    verification_id: uuid(1),
    collection_id: uuid(10),
    refund_id: uuid(11),
    order_id: uuid(20),
    verified_at: "2026-11-14T16:02:00.000000Z",
    verified_by: uuid(30),
    declared_at: "2026-11-14T16:01:00.000000Z",
    declared_by: uuid(31),
    operation_date: "2026-11-14",
    method: "PAGO_MOVIL",
    source_key: "CAJA DEVOLUCIONES",
    reference_key: "SALIDA-1",
    amount_usd: "0.01",
    amount_original: "0.01",
    original_currency: "VES",
    collection_amount_usd: "0.50",
    collection_amount_original: "0.75",
    prior_refunded_usd: "0.01",
    prior_refunded_original: "0.02",
    bcv_rate: "1.50000000",
    bcv_rate_id: uuid(40),
    bcv_valid_on: "2026-11-14",
  },
  {
    key: `COBRO:${uuid(2)}`,
    kind: "COBRO",
    verification_id: uuid(2),
    collection_id: uuid(10),
    refund_id: null,
    order_id: uuid(20),
    verified_at: "2026-11-14T16:00:00.000000Z",
    verified_by: uuid(30),
    declared_at: "2026-11-14T15:59:00.000000Z",
    declared_by: uuid(31),
    operation_date: "2026-11-14",
    method: "PAGO_MOVIL",
    source_key: "CAJA PRINCIPAL",
    reference_key: "RECIBO-1",
    amount_usd: "0.50",
    amount_original: "0.75",
    original_currency: "VES",
    collection_amount_usd: "0.50",
    collection_amount_original: "0.75",
    prior_refunded_usd: null,
    prior_refunded_original: null,
    bcv_rate: "1.50000000",
    bcv_rate_id: uuid(40),
    bcv_valid_on: "2026-11-14",
  },
];
const decimal = (n: bigint) =>
  (n < BigInt(0) ? "-" : "") +
  (n < BigInt(0) ? -n : n) / BigInt(100) +
  "." +
  ((n < BigInt(0) ? -n : n) % BigInt(100)).toString().padStart(2, "0");
const cents = (s: string) => BigInt(s.replace(".", ""));
function totals(rows: CashRow[], physical = false) {
  const credits = rows.filter((r) => r.kind === "COBRO"),
    debits = rows.filter((r) => r.kind === "DEVOLUCION");
  const sum = (rs: CashRow[], key: "amount_usd" | "amount_original") =>
    rs.reduce((n, r) => n + cents(r[key]), BigInt(0));
  const c = sum(credits, "amount_usd"),
    d = sum(debits, "amount_usd"),
    pc = sum(credits, "amount_original"),
    pd = sum(debits, "amount_original");
  return {
    collection_count: credits.length,
    refund_count: debits.length,
    entry_count: rows.length,
    collection_usd: decimal(c),
    refund_usd: decimal(d),
    net_usd: decimal(c - d),
    ...(physical
      ? {
          collection_original: decimal(pc),
          refund_original: decimal(pd),
          net_original: decimal(pc - pd),
        }
      : {}),
  };
}
export function cashReport(rows: CashRow[] = cashRows): CashReport {
  return {
    version: 1,
    scope: "verified_customer_cashbook",
    base_currency: "USD",
    timezone: "America/Caracas",
    recognition_basis: "manual_verification_time",
    snapshot_basis: "single_statement_visibility",
    bank_verified: false,
    date_from: "2026-11-14",
    date_to: "2026-11-14",
    period_start: "2026-11-14T04:00:00.000000Z",
    period_end_exclusive: "2026-11-15T04:00:00.000000Z",
    generated_at: "2026-11-14T17:00:00.000000Z",
    filters: { method: null, currency: null, source_key: null },
    summary: totals(rows),
    currencies: ["USD", "VES"].map((currency) => ({
      currency,
      ...totals(
        rows.filter((r) => r.original_currency === currency),
        true,
      ),
    })),
    methods: ["USD", "VES"].flatMap((currency) =>
      ["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"]
        .filter((method) => currency !== "USD" || method !== "PAGO_MOVIL")
        .map((method) => ({
          currency,
          method,
          ...totals(
            rows.filter(
              (r) => r.original_currency === currency && r.method === method,
            ),
            true,
          ),
        })),
    ),
    daily: [{ date: "2026-11-14", ...totals(rows) }],
    rows,
    export_complete: true,
    maximum_rows: 5000,
    content_sha256: "a".repeat(64),
  } as CashReport;
}
