import { api } from "@/lib/api";
import { deliveryService as service } from "@/services/delivery.service";
import { AxiosError } from "axios";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn() },
}));
const get = jest.mocked(api.get),
  post = jest.mocked(api.post),
  patch = jest.mocked(api.patch);
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  get.mockResolvedValue({ items: [], total: 0 });
  post.mockResolvedValue({ id: "d" });
  patch.mockResolvedValue({ id: "d" });
});
afterEach(() => jest.restoreAllMocks());
it("preserves list filters and does not invent a different query", async () => {
  const result = { items: [{ id: "d" }], total: 50 };
  get.mockResolvedValueOnce(result);
  expect(
    await service.getAll({
      rider_id: "r & 1",
      status: "EN_ROUTE",
      limit: 20,
      offset: 40,
      include_total: true,
    }),
  ).toBe(result);
  expect(get).toHaveBeenCalledWith(
    "/deliveries?rider_id=r+%26+1&status=EN_ROUTE&limit=20&offset=40&include_total=true",
  );
  await service.getAll();
  expect(get).toHaveBeenLastCalledWith("/deliveries");
});
it("keeps legacy array adaptation explicitly separate from a real counted envelope", async () => {
  get.mockResolvedValueOnce([{ id: "d" }]);
  expect(
    await service.getPage({
      limit: 20,
      offset: 20,
      status: "EN_ROUTE",
      rider_id: "r",
    }),
  ).toMatchObject({ items: [{ id: "d" }], total: 1, limit: 20, offset: 20 });
  get.mockResolvedValueOnce([]);
  expect(await service.getPage()).toEqual({
    items: [],
    total: 0,
    limit: 0,
    offset: 0,
  });
  const envelope = { items: [], total: 50 };
  get.mockResolvedValueOnce(envelope);
  expect(await service.getPage()).toBe(envelope);
});
it("encodes IDs in paths and order IDs in queries", async () => {
  await service.getById("d/a?x=1");
  expect(get).toHaveBeenCalledWith("/deliveries/d%2Fa%3Fx%3D1");
  get.mockResolvedValueOnce([{ id: "d" }]);
  expect(await service.getByOrderId("o&limit=200")).toEqual({ id: "d" });
  expect(get).toHaveBeenLastCalledWith(
    "/deliveries?order_id=o%26limit%3D200&limit=1",
  );
  get.mockResolvedValueOnce({ items: [{ id: "envelope" }] });
  expect(await service.getByOrderId("o")).toEqual({ id: "envelope" });
  get.mockResolvedValueOnce({});
  expect(await service.getByOrderId("o")).toBeNull();
});
it("does not turn a lookup outage into a missing delivery", async () => {
  get.mockRejectedValueOnce(new Error("offline"));
  await expect(service.getByOrderId("o")).rejects.toThrow("offline");
});
it.each([
  () => service.getById(""),
  () => service.getById(1 as never),
  () => service.getByOrderId(""),
  () => service.updateStatus("", { status: "EN_ROUTE" }),
  () => service.updateStatus("d", { status: "" }),
  () => service.start(""),
  () => service.complete("", {}),
  () => service.updateLocation("", 0, 0),
  () => service.failDelivery("", "OTRO_REPARTIDOR"),
  () => service.failDelivery("d", "" as never),
])("rejects invalid mutation/lookup input before HTTP %#", async (call) => {
  await expect(call()).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
  expect(post).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
});
it("sends actual delivery IDs and preserves proof, zero location and failure notes", async () => {
  await service.updateStatus(123, { status: "EN_ROUTE" });
  expect(patch).toHaveBeenLastCalledWith("/deliveries/123/status", {
    status: "EN_ROUTE",
  });
  await service.start("d/a");
  expect(post).toHaveBeenLastCalledWith("/deliveries/d%2Fa/start");
  await service.complete("d", { otp_code: "1234", notes: "Proof" });
  expect(post).toHaveBeenLastCalledWith("/deliveries/d/complete", {
    otp_code: "1234",
    notes: "Proof",
  });
  await service.updateLocation("d", 0, 0);
  expect(patch).toHaveBeenLastCalledWith("/deliveries/d/location", {
    lat: 0,
    lng: 0,
    latitude: 0,
    longitude: 0,
  });
  await service.failDelivery("d", "CLIENTE_NO_ESTA", "Called");
  expect(post).toHaveBeenLastCalledWith("/deliveries/d/fail", {
    failure_cause: "CLIENTE_NO_ESTA",
    issue_description: "Called",
  });
  await service.failDelivery("d", "CLIENTE_NO_ESTA", " ");
  expect(post).toHaveBeenLastCalledWith("/deliveries/d/fail", {
    failure_cause: "CLIENTE_NO_ESTA",
  });
});
const mutations = [
  () => service.updateStatus("d", { status: "FALLIDA" }),
  () => service.start("d"),
  () => service.complete("d", {}),
  () => service.updateLocation("d", 0, 0),
  () => service.failDelivery("d", "CLIENTE_NO_ESTA"),
];
it.each(mutations)(
  "preserves server failure detail for a mutation %#",
  async (call) => {
    const error = new AxiosError("bad");
    error.response = {
      status: 409,
      data: { detail: "Concurrent change" },
      headers: {},
      config: {} as never,
      statusText: "Conflict",
    };
    post.mockRejectedValue(error);
    patch.mockRejectedValue(error);
    await expect(call()).rejects.toThrow("Concurrent change");
  },
);
it.each(mutations)(
  "exposes a safe generic mutation failure %#",
  async (call) => {
    post.mockRejectedValue(null);
    patch.mockRejectedValue(null);
    await expect(call()).rejects.toThrow();
  },
);
it.each([
  () => service.getAll(),
  () => service.getPage(),
  () => service.getById("d"),
  () => service.getActiveTracking(),
  () => service.getLiveTracking(),
])(
  "propagates failed private reads without a fake empty list %#",
  async (call) => {
    get.mockRejectedValueOnce(new Error("offline"));
    await expect(call()).rejects.toThrow("offline");
  },
);
it("supports both shapes in legacy active tracking", async () => {
  get.mockResolvedValueOnce([{ id: "a" }]);
  expect(await service.getActiveTracking()).toEqual([{ id: "a" }]);
  get.mockResolvedValueOnce({ items: [{ id: "b" }] });
  expect(await service.getActiveTracking()).toEqual([{ id: "b" }]);
  get.mockResolvedValueOnce({});
  expect(await service.getActiveTracking()).toEqual([]);
});
it.each([
  [0, 0, true],
  [-90, 180, true],
  ["0", "-180", true],
  [91, 0, false],
  [0, 181, false],
  [" ", 0, false],
  [true, 0, false],
  [[1], 0, false],
  [null, 0, false],
  [0, undefined, false],
  [NaN, 0, false],
  [0, Infinity, false],
  ["bad", 0, false],
])("bounds live coordinates %s/%s", async (lat, lng, valid) => {
  get.mockResolvedValueOnce([
    {
      id: "a",
      status: "EN_ROUTE",
      current_latitude: lat,
      current_longitude: lng,
    },
  ]);
  expect(await service.getLiveTracking()).toHaveLength(valid ? 1 : 0);
});
it("preserves explicit zero over a legacy fallback and excludes terminal states", async () => {
  get.mockResolvedValueOnce({
    items: [
      {
        id: "a",
        status: "INICIADA",
        current_latitude: 0,
        current_longitude: 0,
        latitude: 999,
        longitude: 999,
      },
      { id: "b", status: "EN_PICKUP", latitude: 2, longitude: 3 },
      { id: "c", status: "EN_DESTINO", latitude: 2, longitude: 3 },
      { id: "d", status: "COMPLETADA", latitude: 2, longitude: 3 },
    ],
  });
  expect((await service.getLiveTracking()).map((row) => row.id)).toEqual([
    "a",
    "b",
    "c",
  ]);
  get.mockResolvedValueOnce({});
  expect(await service.getLiveTracking()).toEqual([]);
});
