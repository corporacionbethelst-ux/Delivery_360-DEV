import { api } from "@/lib/api";
import { zoneService, normalizeZoneFilters } from "@/services/zone.service";
import {
  vehicleService,
  normalizeVehicleFilters,
} from "@/services/vehicle.service";
import { apiDetail } from "@/lib/service-error";
import { AxiosError } from "axios";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));
const get = jest.mocked(api.get),
  post = jest.mocked(api.post),
  patch = jest.mocked(api.patch),
  remove = jest.mocked(api.delete);
const id = "00000000-0000-4000-8000-000000000001",
  rid = "00000000-0000-4000-8000-000000000002",
  revision = "a".repeat(64);
const vehicle = {
  plate: " ab-123 ",
  type: "MOTO" as const,
  model: "Moto",
  color: "red",
  year: 2020,
};
const zone = {
  name: " Centro ",
  code: " ctr ",
  description: " ",
  color_hex: " #AABBCC ",
  delivery_fee_base: 0,
  cost_per_km: 0,
  estimated_time_min: 1,
};
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  get.mockResolvedValue([]);
  post.mockResolvedValue({ id });
  patch.mockResolvedValue({ id });
  remove.mockResolvedValue(undefined);
});
afterEach(() => jest.restoreAllMocks());
it.each([
  [NaN, 100],
  [Infinity, 100],
  [-1, 1],
  [2.5, 2],
  [9999, 500],
])("bounds list limits %s for both services", (value, expected) => {
  expect(normalizeZoneFilters({ limit: value }).limit).toBe(expected);
  expect(normalizeVehicleFilters({ limit: value }).limit).toBe(expected);
});
it("preserves explicit false and nullable absence without inventing active-only filtering", () => {
  expect(normalizeZoneFilters()).toEqual({});
  expect(
    normalizeZoneFilters({
      search: "  Centro  ",
      active_only: false,
      page: 0,
      limit: null,
    }),
  ).toEqual({ search: "Centro", page: 1 });
  expect(normalizeZoneFilters({ active_only: true, page: NaN })).toEqual({
    active_only: true,
    page: 1,
  });
  expect(
    normalizeVehicleFilters({
      type: "moto",
      status: " activo ",
      search: " a ",
      available_only: true,
      page: 2.5,
    }),
  ).toEqual({
    type: "MOTO",
    status: "ACTIVO",
    search: "a",
    available_only: true,
    page: 2,
  });
  expect(
    normalizeVehicleFilters({
      type: "ALL",
      status: "bad",
      available_only: false,
      page: NaN,
    }),
  ).toEqual({ page: 1 });
  expect(normalizeVehicleFilters()).toEqual({});
});
it("reads actual resource routes with normalized queries", async () => {
  await zoneService.getAll({ active_only: true });
  expect(get).toHaveBeenLastCalledWith("/zones", {
    params: { active_only: true },
  });
  await zoneService.getById(id);
  expect(get).toHaveBeenLastCalledWith(`/zones/${id}`);
  await vehicleService.getAll({ type: "auto" });
  expect(get).toHaveBeenLastCalledWith("/vehicles", {
    params: { type: "AUTO" },
  });
  await vehicleService.getById(id);
  expect(get).toHaveBeenLastCalledWith(`/vehicles/${id}`);
  await vehicleService.getAvailableCompanyVehicles();
  expect(get).toHaveBeenLastCalledWith("/vehicles/available", {
    params: { ownership_type: "EMPRESA" },
  });
});
it("normalizes a copy of zone metadata without changing the editable draft", async () => {
  await zoneService.create(zone);
  expect(post).toHaveBeenLastCalledWith("/zones", {
    ...zone,
    name: "Centro",
    code: "CTR",
    description: null,
    color_hex: "#aabbcc",
  });
  expect(zone.name).toBe(" Centro ");
  await zoneService.update(id, { description: " a ", color_hex: "#ABCDEF" });
  expect(patch).toHaveBeenLastCalledWith(`/zones/${id}`, {
    description: "a",
    color_hex: "#abcdef",
  });
  await zoneService.update(id, {});
  await zoneService.delete(id);
  expect(remove).toHaveBeenLastCalledWith(`/zones/${id}`);
});
it.each([
  { name: "" },
  { code: "" },
  { delivery_fee_base: -1 },
  { delivery_fee_base: NaN },
  { delivery_fee_base: Infinity },
  { cost_per_km: -1 },
  { cost_per_km: NaN },
  { cost_per_km: Infinity },
  { estimated_time_min: 0 },
  { estimated_time_min: NaN },
  { estimated_time_min: 1.5 },
  { color_hex: "red" },
])("rejects invalid zone data before HTTP %j", async (invalid) => {
  await expect(zoneService.create({ ...zone, ...invalid })).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it("normalizes plate and requires an optimistic edit revision for fleet mutations", async () => {
  await vehicleService.create(vehicle);
  expect(post).toHaveBeenLastCalledWith("/vehicles", {
    ...vehicle,
    plate: "AB-123",
  });
  await vehicleService.update(id, { plate: " new-1 " }, revision);
  expect(patch).toHaveBeenLastCalledWith(
    `/vehicles/${id}`,
    { plate: "NEW-1" },
    { headers: { "If-Match": `"${revision}"` } },
  );
  await vehicleService.deactivate(id, revision);
  expect(patch).toHaveBeenLastCalledWith(
    `/vehicles/${id}`,
    { status: "BAJA" },
    { headers: { "If-Match": `"${revision}"` } },
  );
  await vehicleService.delete(id, revision);
  expect(remove).toHaveBeenLastCalledWith(`/vehicles/${id}`, {
    headers: { "If-Match": `"${revision}"` },
  });
});
it.each([
  { plate: "" },
  { model: "" },
  { year: 0 },
  { plate: "bad / plate" },
  { year: 1899 },
  { year: 9999 },
  { year: NaN },
  { year: Infinity },
  { year: 2020.5 },
])("rejects invalid vehicle creation %j", async (invalid) => {
  await expect(
    vehicleService.create({ ...vehicle, ...invalid }),
  ).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it.each([
  () => vehicleService.update(id, {}, ""),
  () => vehicleService.deactivate(id),
  () => vehicleService.delete(id),
  () => vehicleService.update(id, { plate: "bad / plate" }, revision),
])("does not issue an unsafe fleet mutation %#", async (call) => {
  await expect(call()).rejects.toThrow();
  expect(patch).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});
it.each([
  () => zoneService.getById(""),
  () => zoneService.update("bad", {}),
  () => zoneService.delete("bad"),
  () => vehicleService.getById(""),
  () => vehicleService.update("bad", {}, revision),
  () => vehicleService.delete("bad", revision),
  () => vehicleService.deactivate("bad", revision),
  () => vehicleService.assignToRider("bad", rid),
  () => vehicleService.assignToRider(id, "bad"),
  () => vehicleService.unassignFromRider("bad"),
])("validates identifiers before sending a request %#", async (call) => {
  await expect(call()).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});
const calls = [
  () => zoneService.getAll(),
  () => zoneService.getById(id),
  () => zoneService.create(zone),
  () => zoneService.update(id, {}),
  () => zoneService.delete(id),
  () => vehicleService.getAll(),
  () => vehicleService.getById(id),
  () => vehicleService.create(vehicle),
  () => vehicleService.update(id, {}, revision),
  () => vehicleService.deactivate(id, revision),
  () => vehicleService.delete(id, revision),
  () => vehicleService.getAvailableCompanyVehicles(),
  () => vehicleService.assignToRider(id, rid),
  () => vehicleService.unassignFromRider(id),
];
it.each(calls)(
  "propagates backend rejection (including unsupported legacy assignment routes) %#",
  async (call) => {
    const error = new AxiosError("server");
    error.response = {
      status: 409,
      data: { detail: "Concurrent edit" },
      headers: {},
      statusText: "Conflict",
      config: {} as never,
    };
    for (const method of [get, post, patch, remove])
      method.mockRejectedValue(error);
    await expect(call()).rejects.toMatchObject({
      message: "Concurrent edit",
      status: 409,
    });
  },
);
it.each([
  [null, undefined],
  [false, undefined],
  [{}, undefined],
  [{ detail: "Conflict" }, "Conflict"],
  [{ detail: { message: "Locked" } }, "Locked"],
  [
    { detail: [{ loc: ["body", "name"], msg: "Required" }] },
    "body.name: Required",
  ],
  [{ detail: [null, { message: "Invalid" }] }, "campo: Invalid"],
  [{ detail: [{}] }, "campo: inválido"],
  [{ detail: [] }, undefined],
  [
    { message: "Invalid", details: [{ field: "name", message: "Required" }] },
    "Invalid: name: Required",
  ],
  [
    { message: "Invalid", details: [{ msg: "Required" }] },
    "Invalid: campo: Required",
  ],
  [{ message: "Failed" }, "Failed"],
])("handles supported API error shape %#", (body, expected) =>
  expect(apiDetail(body)).toBe(expected),
);
it.each([new Error("offline"), undefined, "unknown"])(
  "wraps non-Axios errors consistently %#",
  async (error) => {
    get.mockRejectedValue(error);
    await expect(zoneService.getAll()).rejects.toThrow(
      error instanceof Error ? "offline" : "Error inesperado",
    );
    await expect(vehicleService.getAll()).rejects.toThrow(
      error instanceof Error ? "offline" : "Error inesperado",
    );
  },
);
