import { normalizeUsdEarnings, normalizeRiderLedger } from "@/lib/usd-ledger";
import {
  confirmWithdrawal,
  normalizePayoutBalance,
} from "@/lib/payout-contract";

const summary = {
  rider_id: "r",
  rider_name: "Rider",
  currency: "USD",
  total_earned: "25.00",
  pending_payout: "15.00",
  completed_deliveries: 1,
};
const entry = {
  id: "e",
  rider_id: "r",
  type: "INGRESO",
  transaction_type: "INGRESO",
  amount: 1000,
  status: "PROCESADO",
  currency: null,
};
it("accepts an explicitly declared zero USD account without importing old balances", () => {
  expect(
    normalizeUsdEarnings({ ...summary, total_earned: 0, pending_payout: 0 }),
  ).toMatchObject({ currency: "USD", total_earned: 0, pending_payout: 0 });
});
it.each([undefined, null, "COP", "VES", "usd"])(
  "requires USD for new personal earnings (%s)",
  (currency) => {
    expect(() => normalizeUsdEarnings({ ...summary, currency })).toThrow();
  },
);
it.each([
  { total_earned: -1 },
  { pending_payout: "0.001" },
  { completed_deliveries: -1 },
  { completed_deliveries: 1.5 },
  { rider_id: "" },
])("rejects malformed earnings (%j)", (change) => {
  expect(() => normalizeUsdEarnings({ ...summary, ...change })).toThrow();
});
it("retains unknown-unit history beside explicit USD without relabelling or summing", () => {
  const history = normalizeRiderLedger({
    rider_id: "r",
    items: [entry, { ...entry, id: "usd", currency: "USD", amount: 25 }],
  });
  expect(history.items.map((x) => [x.amount, x.currency])).toEqual([
    [1000, null],
    [25, "USD"],
  ]);
});
it.each([
  { items: [entry, entry] },
  { items: [{ ...entry, rider_id: "another" }] },
  { items: [{ ...entry, amount: "1.001" }] },
])("rejects contradictory private history", ({ items }) => {
  expect(() => normalizeRiderLedger({ rider_id: "r", items })).toThrow();
});
it("preserves measured exclusion counts and rejects malformed counts", () => {
  expect(
    normalizePayoutBalance({
      available: 0,
      pending: 0,
      currency: "USD",
      unverified_financial_count: 2,
      unverified_payout_count: 1,
    }),
  ).toMatchObject({
    unverified_financial_count: 2,
    unverified_payout_count: 1,
  });
  expect(() =>
    normalizePayoutBalance({
      available: 0,
      pending: 0,
      unverified_financial_count: -1,
    }),
  ).toThrow();
});
it.each([null, undefined, "COP", "VES"])(
  "does not confirm a new USD withdrawal with another unit (%s)",
  (currency) => {
    const row = {
      id: "p",
      rider_id: "r",
      amount: 10,
      status: "PENDIENTE",
      method: "TRANSFERENCIA",
      requested_by_user_id: "u",
      idempotency_key: "key",
      currency,
    };
    expect(() =>
      confirmWithdrawal(row, {
        version: 1,
        userId: "u",
        key: "key",
        amountCents: 1000,
        bankLast4: "",
      }),
    ).toThrow();
  },
);
