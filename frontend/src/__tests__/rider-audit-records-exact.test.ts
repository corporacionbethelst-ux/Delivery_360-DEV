import {
  normalizeExactAuditOrders,
  normalizeExactAuditDeliveries,
  exactAuditTableCsv,
} from "@/lib/rider-audit-records-exact";
import { exactTransactionMoney } from "@/lib/transaction-exact";
import {
  auditRecordsReply,
  auditOrderResponse,
  auditDeliveryResponse,
  auditDeliveryPage,
} from "../../test-fixtures/rider-audit";
import { serializeCSV } from "@/lib/csv-export";
const url = (kind = "orders", offset = 0) =>
  `/riders/audit/records/exact/v2?kind=${kind}&rider_id=rider-1&limit=51&offset=${offset}`;
const orders = () => auditRecordsReply([auditOrderResponse()], url()) as any;
const deliveries = () =>
  auditRecordsReply(auditDeliveryPage(), url("deliveries")) as any;
it("keeps registered exact order prices as strings and never turns historical prices into zero", () => {
  const p = orders();
  expect(normalizeExactAuditOrders(p, "rider-1", 0).rows[0]).toMatchObject({
    amount: "0.00",
    currency: "USD",
  });
  Object.assign(p.items[0], {
    amount: null,
    price_review: "PRECIO_HISTORICO_NO_EXACTO",
    pricing_revision: null,
    currency: null,
    currency_recorded: null,
  });
  const row = normalizeExactAuditOrders(p, "rider-1", 0).rows[0];
  expect(row.amount).toBeNull();
  expect(exactTransactionMoney(row.amount, row.currency, true)).toBe(
    "Importe por revisar",
  );
});
it.each([0.1, "0.1", "01.00", "-0.00", "-0.01", "NaN", "1e2", "100000000.00"])(
  "rejects unverified exact order amount %s",
  (amount) => {
    const p = orders();
    p.items[0].amount = amount;
    expect(() => normalizeExactAuditOrders(p, "rider-1", 0)).toThrow();
  },
);
it.each(["VES", "COP", null, "usd", ""])(
  "preserves currency without converting a historical price (%s)",
  (original) => {
    const p = orders();
    Object.assign(p.items[0], {
      amount: null,
      price_review: "PRECIO_HISTORICO_NO_EXACTO",
      currency_recorded: original,
      currency: original && /^[A-Z]{3}$/.test(original) ? original : null,
      currency_review: original !== null && !/^[A-Z]{3}$/.test(original),
    });
    const row = normalizeExactAuditOrders(p, "rider-1", 0).rows[0];
    expect(row.amount).toBeNull();
    expect(row.currency_recorded).toBe(original);
  },
);
it("preserves exact bonus zero and missing values, but cannot inherit denomination from another source", () => {
  const p = deliveries();
  let row = normalizeExactAuditDeliveries(p, "rider-1", 0).rows[0];
  expect(row.locked_bonus_amount).toBe("0.00");
  expect(row.currency).toBeNull();
  p.items[0].locked_bonus_amount = null;
  expect(
    normalizeExactAuditDeliveries(p, "rider-1", 0).rows[0].locked_bonus_amount,
  ).toBeNull();
  for (const patch of [
    { currency: "USD", currency_recorded: null },
    { currency_basis: "order_currency" },
    { locked_bonus_amount: 0.1 },
    { locked_bonus_amount: "-0.01" },
  ]) {
    expect(() =>
      normalizeExactAuditDeliveries(
        { ...p, items: [{ ...p.items[0], ...patch }] },
        "rider-1",
        0,
      ),
    ).toThrow();
  }
});
it("keeps malformed stored bonuses reviewable without hiding healthy rows or fabricating money", () => {
  const p = deliveries();
  p.items.push({
    ...p.items[0],
    id: "bad",
    order_id: "other-order",
    locked_bonus_amount: null,
    money_review: [
      { field: "locked_bonus_amount", reason: "IMPORTE_NO_VALIDO" },
    ],
  });
  p.total++;
  expect(normalizeExactAuditDeliveries(p, "rider-1", 0).rows).toHaveLength(2);
});
it.each([
  "bank_verified",
  "available_balance_included",
  "wallet_cents_included",
])("rejects a misleading claim %s", (key) => {
  const p = orders();
  p[key] = true;
  expect(() => normalizeExactAuditOrders(p, "rider-1", 0)).toThrow();
});
it.each([
  "scope",
  "kind",
  "rider_id",
  "snapshot_basis",
  "amount_basis",
  "units_basis",
  "pagination_basis",
  "viewer_role",
  "generated_at",
  "content_sha256",
])("rejects wrong provenance %s", (key) => {
  const p = orders();
  p[key] = "incorrect";
  expect(() => normalizeExactAuditOrders(p, "rider-1", 0)).toThrow();
});
it("rejects foreign/duplicate rows, inconsistent revisions and understated page counts", () => {
  for (const patch of [
    { rider_id: "foreign" },
    { id: "" },
    { amount: null, price_review: null },
    { pricing_revision: 0 },
    { amount: "0.00", price_review: "PRECIO_POR_REVISAR" },
  ]) {
    const p = orders();
    Object.assign(p.items[0], patch);
    expect(() => normalizeExactAuditOrders(p, "rider-1", 0)).toThrow();
  }
  const p = orders();
  p.items.push(p.items[0]);
  p.total++;
  expect(() => normalizeExactAuditOrders(p, "rider-1", 0)).toThrow();
  const other = orders();
  other.total++;
  expect(() => normalizeExactAuditOrders(other, "rider-1", 0)).toThrow();
});
it("paginates only real records and distinguishes capped support from a complete set", () => {
  const raw = [
    ...Array.from({ length: 51 }, (_, i) => auditDeliveryResponse(`d-${i}`)),
    auditDeliveryResponse("order-support", "rider-1", {
      order_id: "support",
      locked_bonus_amount: null,
    }),
  ];
  const p = auditRecordsReply(auditDeliveryPage(raw), url("deliveries")) as any;
  const page = normalizeExactAuditDeliveries(p, "rider-1", 0);
  expect(page.rows).toHaveLength(50);
  expect(page.hasNext).toBe(true);
  expect(page.fallback).toHaveLength(1);
  p.fallback_has_more = true;
  expect(() => normalizeExactAuditDeliveries(p, "rider-1", 0)).toThrow();
  p.fallback_has_more = false;
  p.offset = 50;
  expect(() => normalizeExactAuditDeliveries(p, "rider-1", 50)).toThrow();
  p.offset = 0;
  p.fallback[0].order_id = p.items[0].order_id;
  p.fallback[0].id = "order-" + p.items[0].order_id;
  expect(() => normalizeExactAuditDeliveries(p, "rider-1", 0)).toThrow();
});
it("exports only the visible exact table cut without numeric conversion, including unknown units and review flags", () => {
  const p = orders();
  p.items[0].amount = "99999999.99";
  const page = normalizeExactAuditOrders(p, "rider-1", 0);
  const csv = serializeCSV(
    exactAuditTableCsv("orders", page.rows, page.read_context, "rider-1", 0),
  );
  expect(csv).toContain('"99999999.99"');
  expect(csv).toContain('"orders"');
  expect(csv).toContain('"USD"');
  expect(csv).toContain("a".repeat(64));
  expect(csv).toContain("lecturas independientes");
});

it("shows only the stored bonus unit in v2 and exports it without inheriting the order currency", () => {
  const p = deliveries();
  Object.assign(p.items[0], {
    locked_bonus_amount: "0.10",
    currency: "USD",
    currency_recorded: "USD",
  });
  const page = normalizeExactAuditDeliveries(p, "rider-1", 0),
    r = page.rows[0];
  expect(r.currency).toBe("USD");
  expect(exactTransactionMoney(r.locked_bonus_amount, r.currency)).toBe(
    "0,10 USD",
  );
  const csv = exactAuditTableCsv(
    "deliveries",
    page.rows,
    page.read_context,
    "rider-1",
    0,
  );
  expect(csv[0]).toMatchObject({
    bono_conservado: "0.10",
    moneda: "USD",
    moneda_original: "USD",
  });
  p.version = 1;
  expect(() => normalizeExactAuditDeliveries(p, "rider-1", 0)).toThrow();
});
