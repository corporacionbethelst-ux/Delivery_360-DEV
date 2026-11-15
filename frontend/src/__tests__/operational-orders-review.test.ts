import { api } from "@/lib/api";
import { orderService } from "@/services/order.service";
import {
  validateHttpOrder,
  validateOperationalHttpOrder,
  OrderAssignmentIntegrityError,
} from "@/lib/operational-catalog";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import sample from "./fixtures/order-assignment-response.json";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() },
}));
const conflict = {
  ...sample,
  delivery: { ...sample.delivery, rider_id: "another-rider" },
};
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "review-a", refresh_token: "refresh-a" });
});
afterEach(clearStoredTokens);
it("reproduces the reported HTTP200 assignment conflict in strict catalog reads", async () => {
  jest
    .mocked(api.get)
    .mockResolvedValue([
      sample,
      {
        ...conflict,
        id: "other-order",
        delivery: { ...conflict.delivery, order_id: "other-order" },
      },
    ]);
  await expect(orderService.getAll()).rejects.toBeInstanceOf(
    OrderAssignmentIntegrityError,
  );
});
it("operational read preserves both links and other fields without mutating the response", () => {
  const before = JSON.stringify(conflict),
    row = validateOperationalHttpOrder(conflict);
  expect(row.assignment_review).toContain("no coinciden");
  expect(row.assigned_rider_id).toBe(sample.assigned_rider_id);
  expect(row.delivery?.rider_id).toBe("another-rider");
  expect(row.total).toBe(conflict.total);
  expect(JSON.stringify(conflict)).toBe(before);
  expect(() => validateHttpOrder(conflict)).toThrow(
    OrderAssignmentIntegrityError,
  );
});
it.each([
  { rider_id: "another-rider" },
  { assigned_rider_id: null },
  { rider: { id: "another-rider" } },
])(
  "marks inconsistent aliases for review without selecting a preferred rider %j",
  (change) => {
    const row = validateOperationalHttpOrder({ ...sample, ...change });
    expect(row.assignment_review).not.toBeNull();
    expect(() => validateHttpOrder({ ...sample, ...change })).toThrow(
      OrderAssignmentIntegrityError,
    );
  },
);
it("returns valid and conflicting records together, in their original order", async () => {
  const bad = {
    ...conflict,
    id: "bad",
    delivery: { ...conflict.delivery, order_id: "bad" },
  };
  jest.mocked(api.get).mockResolvedValue([sample, bad]);
  const rows = await orderService.getOperationalList();
  expect(rows.map((row) => row.id)).toEqual([sample.id, "bad"]);
  expect(rows[0].assignment_review).toBeNull();
  expect(rows[1].assignment_review).not.toBeNull();
});
it.each([
  { delivery: { ...sample.delivery, order_id: "another-order" } },
  { status: "NOT_REAL" },
  { delivery: { ...sample.delivery, status: "NOT_REAL" } },
  { items: {} },
])("still rejects other invalid order evidence %j", (change) =>
  expect(() =>
    validateOperationalHttpOrder({ ...conflict, ...change }),
  ).toThrow(),
);
it("does not accept duplicate order IDs as a reviewable assignment conflict", async () => {
  jest.mocked(api.get).mockResolvedValue([conflict, conflict]);
  await expect(orderService.getOperationalList()).rejects.toThrow(/duplicadas/);
});
it("overrides any response-supplied review marker with actual validation", () => {
  expect(
    validateOperationalHttpOrder({ ...sample, assignment_review: "forged" })
      .assignment_review,
  ).toBeNull();
  expect(
    validateOperationalHttpOrder({ ...conflict, assignment_review: null })
      .assignment_review,
  ).not.toBeNull();
});
it("does not waive price consistency when an assignment needs review", () => {
  const pricing = {
    version: 1,
    currency: "USD",
    revision: 1,
    subtotal: "10.00",
    delivery_fee: "2.00",
    total: "999.00",
    items: [],
  };
  expect(() =>
    validateOperationalHttpOrder({ ...conflict, currency: "USD", pricing }),
  ).toThrow(/precios/);
});
it("mutation confirmation remains strict even after a review read", async () => {
  jest.mocked(api.get).mockResolvedValue([conflict]);
  await orderService.getOperationalList();
  jest.mocked(api.patch).mockResolvedValue(conflict);
  await expect(
    orderService.assignRider(sample.id, sample.assigned_rider_id),
  ).rejects.toThrow();
});
