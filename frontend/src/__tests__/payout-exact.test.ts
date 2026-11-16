import {
  normalizeExactPayout,
  normalizeExactPayoutPage,
  prepareExactPayoutQuery,
  canReviewPayout,
  confirmExactPayoutDecision,
  completedPayoutUsd,
  exactPayoutCsv,
  payoutExactMoney,
} from "@/lib/payout-exact";
import { payoutEnvelope, payoutRecord } from "../../test-fixtures/payout-exact";
import { serializeCSV } from "@/lib/csv-export";
const q = () => prepareExactPayoutQuery({ audience: "STAFF" });
const raw = () =>
  payoutEnvelope(
    {
      items: [{ id: "p", rider_id: "r", currency: "USD", amount: 0.1 }],
      next_cursor: null,
    },
    "/payouts/exact/page?audience=STAFF",
  );
const parse = (r: unknown) => normalizeExactPayoutPage(r, q());
it("keeps all monetary values as decimal strings and absent snapshots as null", () => {
  const p = parse(raw()).items[0];
  expect(p).toMatchObject({
    amount: "0.10",
    balance_before: null,
    balance_after: null,
    orders_count: null,
    currency: "USD",
  });
  expect(payoutExactMoney(p.balance_before, p.currency)).toBe(
    "Monto no informado",
  );
  expect(payoutExactMoney("99999999.99", "USD")).toBe("99.999.999,99 USD");
});
it.each(["amount", "balance_before", "balance_after"])(
  "rejects numeric or noncanonical exact %s",
  (field) => {
    for (const v of [
      0.1,
      "0.1",
      "01.00",
      "NaN",
      "Infinity",
      "1e2",
      "1.001",
      undefined,
    ]) {
      const p = raw();
      (p.items[0] as any)[field] = v;
      if (field === "amount") p.items[0].total_amount = v;
      expect(() => parse(p)).toThrow();
    }
  },
);
it.each(["0.00", "-0.01", "100000000.00"])(
  "does not approve an invalid primary amount %s",
  (amount) => {
    const p = raw();
    p.items[0].amount = p.items[0].total_amount = amount;
    expect(() => parse(p)).toThrow();
  },
);
it("preserves reviewable invalid amounts without fabricating zero or hiding healthy rows", () => {
  const p = raw();
  const bad = {
    ...p.items[0],
    id: "bad",
    amount: null,
    total_amount: null,
    money_review: [{ field: "amount", reason: "IMPORTE_NO_VALIDO" }],
  };
  p.items.push(bad);
  p.total++;
  const rows = parse(p).items;
  expect(rows).toHaveLength(2);
  expect(canReviewPayout(rows[1])).toBe(false);
  expect(payoutExactMoney(rows[1].amount, rows[1].currency, true)).toBe(
    "Importe por revisar",
  );
});
it.each([null, "VES", "COP", "usd", ""])(
  "keeps recorded currency and never invents USD (%s)",
  (currency) => {
    const p = raw();
    Object.assign(p.items[0], {
      currency_recorded: currency,
      currency: currency && /^[A-Z]{3}$/.test(currency) ? currency : null,
      currency_review: currency !== null && !/^[A-Z]{3}$/.test(currency),
    });
    const row = parse(p).items[0];
    expect(row.currency_recorded).toBe(currency);
    expect(row.currency).not.toBe("USD");
  },
);
it.each([
  "bank_verified",
  "available_balance_included",
  "wallet_cents_included",
])("rejects misleading financial claims: %s", (flag) => {
  const p = raw();
  (p as any)[flag] = true;
  expect(() => parse(p)).toThrow();
});
it.each([
  "scope",
  "units_basis",
  "snapshot_basis",
  "pagination_basis",
  "balance_basis",
  "content_sha256",
  "generated_at",
  "viewer_role",
])("rejects invalid envelope %s", (field) => {
  const p = raw();
  (p as any)[field] = "invalid";
  expect(() => parse(p)).toThrow();
});
it("binds ownership, filters, complete-history claims and explicit audience", () => {
  for (const patch of [
    { viewer_role: "REPARTIDOR", effective_rider_id: "other" },
    { filters: { ...raw().filters, audience: "OWNER" } },
    { filters: { ...raw().filters, status: "COMPLETADO" } },
    { total: 2 },
    { history_included: true },
    { history_complete: true },
    { history_limit: 1000 },
  ]) {
    expect(() => parse({ ...raw(), ...patch })).toThrow();
  }
  const p = raw();
  p.items.push(p.items[0]);
  p.total++;
  expect(() => parse(p)).toThrow();
});
it("accepts the original signed cursor shape without interpreting or replacing it", () => {
  const token = "position." + "a".repeat(64),
    p = raw();
  p.limit = 1;
  p.next_cursor = token;
  expect(
    normalizeExactPayoutPage(
      p,
      prepareExactPayoutQuery({ limit: 1, audience: "STAFF" }),
    ).next_cursor,
  ).toBe(token);
  p.cursor = token;
  expect(() =>
    normalizeExactPayoutPage(
      p,
      prepareExactPayoutQuery({ limit: 1, cursor: token, audience: "STAFF" }),
    ),
  ).toThrow();
});
it.each([
  { offset: 0 },
  { cursor: "after-50" },
  { audience: "GLOBAL" },
  { status: "CANCELADO" },
  { rider_id: "  " },
])("rejects unsupported queries %j", (query) => {
  expect(() => prepareExactPayoutQuery(query as never)).toThrow();
});
it("reads independently denominated complete history in the same envelope, without fictitious amounts", () => {
  const url = "/payouts/exact/p?audience=STAFF",
    p = payoutEnvelope(
      { items: [{ id: "p", currency: "USD" }], next_cursor: null },
      url,
    );
  p.history = [
    {
      id: "event",
      payout_id: "p",
      currency: null,
      currency_recorded: null,
      currency_review: false,
      money_review: [],
      balance_before: "20.00",
      balance_after: null,
      old_status: "ESTADO_HISTORICO",
      new_status: null,
      changed_by_user_id: null,
      reason: null,
      created_at: null,
    },
  ];
  const result = normalizeExactPayoutPage(
    p,
    prepareExactPayoutQuery({ limit: 1, audience: "STAFF" }),
    "p",
  );
  expect(result.history[0]).toMatchObject({
    currency: null,
    balance_after: null,
    old_status: "ESTADO_HISTORICO",
  });
  expect(result.history[0]).not.toHaveProperty("amount");
  for (const patch of [
    { history_complete: false },
    { history_limit: 999 },
    { history: [{ ...p.history[0], payout_id: "other" }] },
    { history: [p.history[0], p.history[0]] },
    { history: Array(1001).fill(p.history[0]) },
  ]) {
    expect(() =>
      normalizeExactPayoutPage(
        { ...p, ...patch },
        prepareExactPayoutQuery({ limit: 1, audience: "STAFF" }),
        "p",
      ),
    ).toThrow();
  }
});
it("adds the completed USD page subtotal with BigInt and counts exclusions", () => {
  const rows = [
    ["a", "0.10", "USD"],
    ["b", "0.20", "USD"],
    ["c", "10.00", "VES"],
    ["d", "10.00", null],
  ].map(([id, amount, currency]) =>
    normalizeExactPayout(
      payoutRecord({ id, amount, currency, status: "COMPLETADO" }),
    ),
  );
  expect(completedPayoutUsd(rows)).toEqual({ amount: "0.30", excluded: 2 });
});
it("exports the confirmed exact page cut and scope, with spreadsheet formula protection", () => {
  const p = raw();
  p.items[0].reference_code = "=SUM(A1)";
  const result = parse(p);
  const csv = serializeCSV(
    exactPayoutCsv(
      result.items,
      { status: "ALL", offset: 50, cursor: "opaque", search: "p" },
      result.read_context,
    ),
  );
  expect(csv).toContain('"0.10"');
  expect(csv).toContain('"\'=SUM(A1)"');
  expect(csv).toContain("Solo coincidencias de la página cargada");
  expect(csv).toContain("a".repeat(64));
  expect(() =>
    exactPayoutCsv(
      [],
      { status: "ALL", offset: 0, cursor: null, search: "" },
      null,
    ),
  ).toThrow();
});
it("bridges numeric mutation confirmations by exact cents and never replaces a read model", () => {
  const p = parse(raw()).items[0];
  const confirmed = {
    ...p,
    amount: 0.1,
    total_amount: 0.1,
    status: "EN_PROCESO",
  } as unknown as import("@/services/payout.service").Payout;
  expect(confirmExactPayoutDecision(confirmed, p, "approve")).toBe(
    "EN_PROCESO",
  );
  for (const patch of [
    { id: "other" },
    { rider_id: "other" },
    { currency: "VES" },
    { method: "EFECTIVO" },
    { bank_account_last4: "1234" },
    { amount: 0.11 },
    { status: "COMPLETADO" },
  ]) {
    expect(() =>
      confirmExactPayoutDecision(
        { ...confirmed, ...patch } as never,
        p,
        "approve",
      ),
    ).toThrow();
  }
  expect(
    confirmExactPayoutDecision(
      { ...confirmed, status: "RECHAZADO" } as never,
      p,
      "reject",
    ),
  ).toBe("RECHAZADO");
  expect(p.amount).toBe("0.10");
});
