import { api } from "@/lib/api";
import {
  getOperationalDashboard,
  parseDashboardSnapshot,
  DashboardSnapshot,
} from "@/services/operational-dashboard.service";
import { dashboardSnapshot } from "../../test-utils/operational-dashboard";

jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());

it("preserves actual totals, null evidence and zero measurements", () => {
  const data = dashboardSnapshot();
  data.summary.avg_delivery_minutes = 0;
  data.summary.sla_percent = 0;
  data.summary.sla_known_count = 1;
  data.summary.sla_unknown_count = 2;
  expect(parseDashboardSnapshot(data)).toEqual(data);
  expect(data.summary.pending_orders).toBe(123);
  expect(data.pending_orders).toHaveLength(0);
});

it.each([
  [
    "negative count",
    (d: DashboardSnapshot) => {
      d.summary.pending_orders = -1;
    },
  ],
  [
    "fraction count",
    (d: DashboardSnapshot) => {
      d.summary.pending_orders = 1.5;
    },
  ],
  [
    "unsafe count",
    (d: DashboardSnapshot) => {
      d.summary.pending_orders = Number.MAX_SAFE_INTEGER + 1;
    },
  ],
  [
    "NaN",
    (d: DashboardSnapshot) => {
      d.summary.avg_delivery_minutes = NaN;
    },
  ],
  [
    "infinity",
    (d: DashboardSnapshot) => {
      d.summary.avg_delivery_minutes = Infinity;
    },
  ],
  [
    "negative duration",
    (d: DashboardSnapshot) => {
      d.summary.avg_delivery_minutes = -1;
    },
  ],
  [
    "percent range",
    (d: DashboardSnapshot) => {
      d.summary.sla_percent = 101;
    },
  ],
  [
    "incoherent SLA counts",
    (d: DashboardSnapshot) => {
      d.summary.sla_unknown_count = 100;
    },
  ],
  [
    "duration count",
    (d: DashboardSnapshot) => {
      d.summary.valid_duration_count = 4;
    },
  ],
  [
    "timezone",
    (d: DashboardSnapshot) => {
      d.timezone = "Invalid/Zone";
    },
  ],
  [
    "naive timestamp",
    (d: DashboardSnapshot) => {
      d.generated_at = "2026-10-30T12:00:00";
    },
  ],
  [
    "invalid timestamp",
    (d: DashboardSnapshot) => {
      d.period_start = "bad";
    },
  ],
  [
    "reversed interval",
    (d: DashboardSnapshot) => {
      d.period_start = "2027-01-01T00:00:00Z";
    },
  ],
  [
    "empty series",
    (d: DashboardSnapshot) => {
      d.series = [];
    },
  ],
  [
    "impossible day",
    (d: DashboardSnapshot) => {
      d.series[0].date = "2026-02-30";
    },
  ],
  [
    "duplicate days",
    (d: DashboardSnapshot) => {
      d.series[0].date = d.series[1].date;
    },
  ],
  [
    "invalid series count",
    (d: DashboardSnapshot) => {
      d.series[0].orders_created = -1;
    },
  ],
  [
    "oversized series",
    (d: DashboardSnapshot) => {
      d.series = Array.from({ length: 32 }, () => d.series[0]);
    },
  ],
])("refuses %s", (_name, mutate) => {
  const data = dashboardSnapshot();
  mutate(data);
  expect(() => parseDashboardSnapshot(data)).toThrow(
    "Respuesta de métricas inválida",
  );
});

it.each([
  null,
  [],
  {},
  { summary: [] },
  { ...dashboardSnapshot(), source: "demo" },
  { ...dashboardSnapshot(), financials_available: true },
  { ...dashboardSnapshot(), queue_truncated: "false" },
  {
    ...dashboardSnapshot(),
    summary: { ...dashboardSnapshot().summary, pending_orders: "123" },
  },
])("refuses malformed or fabricated payloads %#", (value) => {
  expect(() => parseDashboardSnapshot(value)).toThrow();
});

it("accepts zero coordinates and validates bounded operator previews", () => {
  const data = dashboardSnapshot();
  data.riders_online = [
    { id: "rider", lat: 0, lng: 0, recorded_at: data.generated_at },
  ];
  data.pending_orders = [
    {
      id: "order",
      number: null,
      status: "PENDIENTE",
      priority: null,
      address: "Test street",
    },
  ];
  expect(parseDashboardSnapshot(data).riders_online[0].lat).toBe(0);
  data.riders_online[0].lat = 91;
  expect(() => parseDashboardSnapshot(data)).toThrow();
  data.riders_online[0].lat = 0;
  data.riders_online[0].lng = Infinity;
  expect(() => parseDashboardSnapshot(data)).toThrow();
  data.riders_online = [];
  data.pending_orders = Array.from(
    { length: 21 },
    () => data.pending_orders[0],
  );
  expect(() => parseDashboardSnapshot(data)).toThrow();
  data.pending_orders = [];
  data.riders_online = Array.from({ length: 51 }, () => ({
    id: "r",
    lat: 0,
    lng: 0,
    recorded_at: data.generated_at,
  }));
  expect(() => parseDashboardSnapshot(data)).toThrow();
});

it("uses canonical authenticated API paths and propagates cancellation", async () => {
  jest.mocked(api.get).mockResolvedValue(dashboardSnapshot());
  const controller = new AbortController();
  await expect(
    getOperationalDashboard("operator", 7, controller.signal),
  ).resolves.toEqual(dashboardSnapshot());
  expect(api.get).toHaveBeenCalledWith("/dashboard/operator?days=7", {
    signal: controller.signal,
  });
});

it.each([0, 32, 1.5, NaN])(
  "rejects invalid query days %s before requesting",
  async (days) => {
    await expect(getOperationalDashboard("manager", days)).rejects.toThrow();
    expect(api.get).not.toHaveBeenCalled();
  },
);

it("rejects invalid modes before requesting", async () => {
  await expect(
    getOperationalDashboard("customer" as "manager", 7),
  ).rejects.toThrow();
  expect(api.get).not.toHaveBeenCalled();
});
