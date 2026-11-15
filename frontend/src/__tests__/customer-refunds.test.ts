import {
  validateRefund,
  validateRefundContext,
  refundAmount,
} from "@/lib/customer-refunds";
import { customerRefundsService as service } from "@/services/customer-refunds.service";
import { api } from "@/lib/api";
import {
  refund,
  refundContext,
  withRefund,
  approved,
  declared,
  returned,
  approval,
  verification,
  refundEvent,
  refundRequest,
  eventCommand,
} from "../../test-utils/customer-refund-fixtures";
import {
  orderId,
  orderReceipt,
} from "../../test-utils/order-currency-fixtures";
import { reviewerId } from "../../test-utils/customer-collection-fixtures";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
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
it("preserves requests, authorization, declaration and independently confirmed refunds", () => {
  for (const row of [refund, approved, declared, returned]) {
    expect(validateRefund(row, orderId)).toEqual(row);
    expect(validateRefundContext(withRefund(row), orderId)).toEqual(
      withRefund(row),
    );
  }
  expect(validateRefundContext(refundContext, orderId)).toEqual(refundContext);
});
it("uses differences of cumulative original conversion and closes paid cents", () => {
  expect(refundAmount("0.01", "0.00", "0.00", "1.50000000")).toBe("0.02");
  expect(refundAmount("0.01", "0.01", "0.02", "1.50000000")).toBe("0.01");
  expect(refundAmount("0.48", "0.02", "0.03", "1.50000000")).toBe("0.72");
  const original = {
    ...refund.original_collection,
    paid_currency: "VES",
    paid_amount: "0.30",
    method: "PAGO_MOVIL",
    quote: orderReceipt,
  };
  const ves = {
    ...refund,
    amount_usd: "0.01",
    return_amount: "0.01",
    return_currency: "VES",
    prior_refunded_usd: "0.01",
    prior_refunded_paid: "0.02",
    original_collection: original,
  };
  expect(validateRefund(ves, orderId).return_amount).toBe("0.01");
  expect(() =>
    validateRefund({ ...ves, return_amount: "0.02" }, orderId),
  ).toThrow();
});
it.each([
  { bank_verified: true },
  { order_id: refund.id },
  { policy: "TODAY_RATE" },
  { return_currency: "VES" },
  { amount_usd: "0.30" },
  { return_amount: "0.11" },
  { prior_refunded_paid: "0.01" },
  { reason: "Invalid \x7f text" },
  { state: "DEVUELTA" },
  { revision: 1 },
  { has_more_events: true },
  { allowed_actions: ["VERIFICAR_DEVOLUCION"] },
])("rejects forged request data %j", (change) =>
  expect(() => validateRefund({ ...refund, ...change }, orderId)).toThrow(),
);
it.each([
  { verified_evidence: true },
  { confirmed_execution: true },
  { note: "Invalid \x7f text" },
  { actor_id: refund.requested_by },
  { source_key: "CAJA" },
])("rejects malformed authorization %j", (change) =>
  expect(() =>
    validateRefund(
      { ...approved, events: [{ ...approval, ...change }] },
      orderId,
    ),
  ).toThrow(),
);
it("rejects self verification, missing root authorization and broken revision history", () => {
  expect(() =>
    validateRefund(
      {
        ...returned,
        events: [
          { ...verification, actor_id: refund.requested_by },
          ...returned.events.slice(1),
        ],
      },
      orderId,
    ),
  ).toThrow();
  expect(() =>
    validateRefund(
      {
        ...returned,
        revision: 1,
        events: [{ ...verification, revision: 1 }],
        state: "DEVUELTA",
      },
      orderId,
    ),
  ).toThrow();
  expect(() =>
    validateRefund(
      { ...returned, events: [returned.events[0], returned.events[2]] },
      orderId,
    ),
  ).toThrow();
});
it.each([
  { book_revision: 0 },
  { bank_integration_available: true },
  { summary: { ...withRefund(refund).summary, remaining_usd: "0.10" } },
  { summary: { ...withRefund(refund).summary, refunded_usd: "0.30" } },
  { summary: { ...withRefund(refund).summary, requestable_now_usd: "0.20" } },
  {
    collections: [{ ...withRefund(refund).collections[0], can_request: true }],
  },
])("rejects incoherent refund balances %j", (change) =>
  expect(() =>
    validateRefundContext({ ...withRefund(refund), ...change }, orderId),
  ).toThrow(),
);
it("keeps observed executions reserved until reconciled", () => {
  const observation = refundEvent("OBSERVAR_EJECUCION", 3, reviewerId),
    observed = {
      ...declared,
      revision: 3,
      state: "OBSERVADA" as const,
      events: [observation, ...declared.events],
      allowed_actions: [
        "VERIFICAR_DEVOLUCION",
        "CONFIRMAR_NO_EJECUTADA",
      ] as const,
    };
  const c = withRefund({
    ...observed,
    allowed_actions: [...observed.allowed_actions],
  });
  expect(validateRefundContext(c, orderId).summary).toMatchObject({
    refunded_usd: "0.00",
    in_progress_usd: "0.10",
    remaining_usd: "0.20",
  });
});
it("sends the reviewed request and rejects a mismatched response", async () => {
  jest.mocked(api.post).mockResolvedValue(refund);
  expect(await service.request(orderId, refundRequest)).toEqual(refund);
  expect(api.post).toHaveBeenCalledWith(
    "/customer-refunds/orders/" + orderId,
    refundRequest,
  );
  jest
    .mocked(api.post)
    .mockResolvedValue({ ...refund, reason: "Otro motivo de devolución" });
  await expect(service.request(orderId, refundRequest)).rejects.toThrow();
});
it("matches the applied event even if a later refund state is returned on replay", async () => {
  const body = eventCommand("APROBAR", 0);
  jest
    .mocked(api.post)
    .mockResolvedValue({ refund: returned, applied_event: approval });
  expect((await service.event(orderId, refund.id, body)).applied_event).toEqual(
    approval,
  );
  jest
    .mocked(api.post)
    .mockResolvedValue({
      refund: approved,
      applied_event: { ...approval, note: "Otra comprobación diferente" },
    });
  await expect(service.event(orderId, refund.id, body)).rejects.toThrow();
});
it("rejects private responses after a session change", async () => {
  jest.mocked(api.get).mockImplementation(async () => {
    mockCurrent = false;
    return refundContext;
  });
  await expect(service.context(orderId)).rejects.toThrow("Session changed");
});
