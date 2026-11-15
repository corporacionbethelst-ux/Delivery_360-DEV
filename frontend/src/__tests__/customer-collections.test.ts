import {
  validateCollection,
  validateCollectionContext,
} from "@/lib/customer-collections";
import { customerCollectionsService as service } from "@/services/customer-collections.service";
import { api } from "@/lib/api";
import {
  collection,
  reviewed,
  collectionContext,
  pendingContext,
  declaration,
  reviewCommand,
} from "../../test-utils/customer-collection-fixtures";
import {
  orderId,
  orderReceipt,
} from "../../test-utils/order-currency-fixtures";
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
it("accepts pending and manually reviewed receipts, never bank verification", () => {
  expect(validateCollection(collection, orderId)).toEqual(collection);
  expect(validateCollection(reviewed, orderId)).toEqual(reviewed);
  expect(validateCollectionContext(collectionContext, orderId)).toEqual(
    collectionContext,
  );
  expect(validateCollectionContext(pendingContext, orderId)).toEqual(
    pendingContext,
  );
});
it("checks partial VES against the preserved quote", () => {
  const ves = {
    ...collection,
    paid_currency: "VES",
    method: "PAGO_MOVIL",
    paid_amount: "0.30",
    quote: orderReceipt,
  };
  expect(validateCollection(ves, orderId).paid_amount).toBe("0.30");
  expect(() =>
    validateCollection({ ...ves, paid_amount: "0.31" }, orderId),
  ).toThrow();
});
it.each([
  { bank_verified: true },
  { order_id: collection.id },
  { amount_usd: "NaN" },
  { amount_usd: "0.60" },
  { amount_usd: "0.00" },
  { paid_amount: "0.21" },
  { paid_currency: "VES" },
  { method: "PAGO_MOVIL" },
  { source_key: "caja" },
  { reference_key: "RECIBO\n94" },
  { status: "VERIFICADO_MANUALMENTE" },
  { received_on: "2026-02-30" },
  { review: { ...reviewed.review, reviewed_by: collection.declared_by } },
  { review: { ...reviewed.review, verified_evidence: false } },
  { review: { ...reviewed.review, note: "Invisible control \x7f character" } },
  { review: { ...reviewed.review, reviewed_at: "2026-11-14T16:00:00Z" } },
])("rejects forged receipt %j", (change) =>
  expect(() =>
    validateCollection(
      { ...("review" in change ? reviewed : collection), ...change },
      orderId,
    ),
  ).toThrow(),
);
it.each([
  { collection_revision: 2 },
  { price_locked: false },
  { bank_integration_available: true },
  { summary: { ...pendingContext.summary, verified_usd: "0.20" } },
  { summary: { ...pendingContext.summary, due_usd: "0.30" } },
  { summary: { ...pendingContext.summary, available_to_declare_usd: "0.50" } },
  { summary: { ...pendingContext.summary, state: "COMPLETO" } },
  { summary: { ...pendingContext.summary, refund_due_usd: "0.20" } },
])("rejects inconsistent context %j", (change) =>
  expect(() =>
    validateCollectionContext({ ...pendingContext, ...change }, orderId),
  ).toThrow(),
);
it("allows operator privacy with global summary and a refund liability on canceled orders", () => {
  expect(
    validateCollectionContext({ ...pendingContext, collections: [] }, orderId)
      .summary.pending_usd,
  ).toBe("0.20");
  const canceled = {
    ...pendingContext,
    order_status: "CANCELADO",
    collection_revision: 2,
    collections: [reviewed],
    summary: {
      ...pendingContext.summary,
      pending_usd: "0.00",
      verified_usd: "0.20",
      review_count: 1,
      due_usd: "0.00",
      available_to_declare_usd: "0.00",
      refund_due_usd: "0.20",
      state: "DEVOLUCION_PENDIENTE",
    },
  };
  expect(
    validateCollectionContext(canceled, orderId).summary.refund_due_usd,
  ).toBe("0.20");
});
it("sends exactly the reviewed declaration and validates its receipt", async () => {
  jest.mocked(api.post).mockResolvedValue(collection);
  expect(await service.declare(orderId, declaration)).toEqual(collection);
  expect(api.post).toHaveBeenCalledWith(
    "/customer-collections/orders/" + orderId,
    declaration,
  );
  jest
    .mocked(api.post)
    .mockResolvedValue({ ...collection, reference_key: "OTHER" });
  await expect(service.declare(orderId, declaration)).rejects.toThrow();
});
it("validates the independent decision returned for a review", async () => {
  jest.mocked(api.post).mockResolvedValue(reviewed);
  expect(await service.review(orderId, collection.id, reviewCommand)).toEqual(
    reviewed,
  );
  jest.mocked(api.post).mockResolvedValue({
    ...reviewed,
    review: { ...reviewed.review, note: "Otra comprobación distinta" },
  });
  await expect(
    service.review(orderId, collection.id, reviewCommand),
  ).rejects.toThrow();
});
it("rejects late private responses after credentials change", async () => {
  jest.mocked(api.get).mockImplementation(async () => {
    mockCurrent = false;
    return collectionContext;
  });
  await expect(service.context(orderId)).rejects.toThrow("Session changed");
});
