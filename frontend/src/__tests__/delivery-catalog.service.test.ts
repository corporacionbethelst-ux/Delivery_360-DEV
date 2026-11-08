import { api } from "@/lib/api";
import { readDeliveryPage } from "@/services/delivery-catalog.service";
import { firstDeliveryQuery } from "@/lib/delivery-catalog";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import { deliveryHttp, riderId } from "../../test-fixtures/delivery-catalog";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => {
  jest.resetAllMocks();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  get.mockImplementation(async (url) => deliveryHttp(url));
});
afterEach(() => clearStoredTokens());
it("uses only the bounded real-delivery endpoint and explicit metadata", async () => {
  const result = await readDeliveryPage(firstDeliveryQuery);
  expect(get).toHaveBeenCalledWith("/deliveries/page?limit=20&offset=0");
  expect(result.rows).toHaveLength(20);
  expect(result.total).toBe(45);
});
it.each([
  ["assigned", "false"],
  ["unassigned", "true"],
] as const)(
  "sends %s as an actual server filter",
  async (assignment, value) => {
    await readDeliveryPage({
      ...firstDeliveryQuery,
      assignment,
      status: "COMPLETADA",
    });
    expect(get).toHaveBeenCalledWith(
      `/deliveries/page?limit=20&offset=0&status=COMPLETADA&unassigned=${value}`,
    );
  },
);
it("preserves rider, status, offset and page size", async () => {
  await readDeliveryPage({
    ...firstDeliveryQuery,
    offset: 50,
    limit: 50,
    status: "EN_ROUTE",
    rider: riderId,
  });
  expect(get).toHaveBeenCalledWith(
    `/deliveries/page?limit=50&offset=50&status=EN_ROUTE&rider_id=${riderId}`,
  );
});
it("fails before HTTP when credentials or query are absent/invalid", async () => {
  await expect(
    readDeliveryPage({ ...firstDeliveryQuery, rider: "bad" }),
  ).rejects.toThrow();
  clearStoredTokens();
  await expect(readDeliveryPage(firstDeliveryQuery)).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it.each(["resolve", "reject"])(
  "retires a private %s after logout",
  async (mode) => {
    let resolve!: (x: unknown) => void, reject!: (x: Error) => void;
    get.mockReturnValueOnce(
      new Promise((a, b) => {
        resolve = a;
        reject = b;
      }),
    );
    const work = readDeliveryPage(firstDeliveryQuery);
    clearStoredTokens();
    if (mode === "resolve") resolve(deliveryHttp("/?limit=20&offset=0"));
    else reject(new Error("old"));
    await expect(work).rejects.toThrow();
  },
);
it("propagates failure without returning a false empty page", async () => {
  get.mockRejectedValueOnce(new Error("offline"));
  await expect(readDeliveryPage(firstDeliveryQuery)).rejects.toThrow("offline");
});
