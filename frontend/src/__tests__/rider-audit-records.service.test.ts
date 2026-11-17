import { api } from "@/lib/api";
import { readExactRiderAudit } from "@/services/rider-audit-exact.service";
import { auditHttpResponse } from "../../test-fixtures/rider-audit";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import { initialAuditOffsets } from "@/lib/rider-audit-contract";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => {
  jest.resetAllMocks();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  get.mockImplementation(async (url) => auditHttpResponse(url, 1));
});
afterEach(() => clearStoredTokens());
it("uses only exact table APIs with the captured rider and independent offsets", async () => {
  const r = await readExactRiderAudit("rider-1", {
    orders: 50,
    deliveries: 0,
    transactions: 100,
  });
  expect(get.mock.calls.map(([url]) => url)).toEqual([
    "/riders/audit/summary/exact?rider_id=rider-1&limit=1&offset=0",
    "/riders/audit/records/exact/v2?kind=orders&rider_id=rider-1&limit=51&offset=50",
    "/riders/audit/records/exact/v2?kind=deliveries&rider_id=rider-1&limit=51&offset=0",
    "/financial/transactions/exact/page?rider_id=rider-1&limit=51&offset=100",
  ]);
  expect(r.deliveries.rows[0].locked_bonus_amount).toBe("0.00");
  expect(r.deliveries.rows[0].currency).toBeNull();
});
it.each(["orders", "deliveries", "transactions"])(
  "rejects another actor in %s rather than publishing a mixed private set",
  async (kind) => {
    get.mockImplementation(async (url) => {
      const p = auditHttpResponse(url, 1) as any;
      const hit =
        kind === "transactions"
          ? url.includes("/financial/")
          : url.includes("kind=" + kind);
      if (hit) p.viewer_user_id = "other";
      return p;
    });
    await expect(
      readExactRiderAudit("rider-1", initialAuditOffsets),
    ).rejects.toThrow("actor");
  },
);
it("rejects a numeric HTTP impostor with no compatibility fallback request", async () => {
  get.mockImplementation(async (url) => {
    const p = auditHttpResponse(url, 1) as any;
    if (url.includes("kind=orders")) p.items[0].amount = 0.1;
    return p;
  });
  await expect(
    readExactRiderAudit("rider-1", initialAuditOffsets),
  ).rejects.toThrow();
  expect(get).toHaveBeenCalledTimes(4);
});
