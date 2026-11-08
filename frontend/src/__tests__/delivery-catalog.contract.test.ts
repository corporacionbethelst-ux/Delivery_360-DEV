import {
  firstDeliveryQuery as initial,
  prepareDeliveryQuery,
  normalizeDeliveryPage,
  searchDeliveries,
  deliveryDuration,
} from "@/lib/delivery-catalog";
import {
  deliveryRow,
  deliveryPage,
  riderId,
} from "../../test-fixtures/delivery-catalog";

it.each([20, 50, 100])(
  "captures validated pages of %s independently",
  (limit) => {
    const input = { ...initial, limit, offset: limit };
    const captured = prepareDeliveryQuery(input);
    input.status = "FALLIDA";
    expect(captured.status).toBe("ALL");
    expect(captured.offset).toBe(limit);
  },
);
it.each([
  { offset: -1 },
  { offset: 1 },
  { offset: Infinity },
  { limit: 0 },
  { limit: 200 },
  { limit: NaN },
  { status: "UNKNOWN" },
  { status: "EN_RUTA" },
  { assignment: "false" },
  { rider: "bad" },
  { rider: riderId, assignment: "unassigned" },
])("rejects invalid query %j", (change) =>
  expect(() =>
    prepareDeliveryQuery({ ...initial, ...change } as never),
  ).toThrow(),
);
it("trims UUID input but preserves exact query identity", () =>
  expect(prepareDeliveryQuery({ ...initial, rider: ` ${riderId} ` })).toEqual({
    ...initial,
    rider: riderId,
  }));
it("retains IDs, zero duration, null reference and false SLA without inventing defaults", () => {
  const page = normalizeDeliveryPage(deliveryPage(), initial);
  expect(page.rows[0]).toMatchObject({
    id: "delivery-1",
    order: "order-1",
    reference: null,
    minutes: 0,
    sla: false,
    customer: "José Cliente",
    riderName: "Ana Rider",
  });
});
it.each([
  null,
  [],
  false,
  {},
  { items: [], total: 0, limit: 20 },
  { items: [], total: "0", limit: 20, offset: 0 },
  deliveryPage({}, 1, { offset: 20 }),
  deliveryPage({}, 1, { limit: 50 }),
  deliveryPage({}, 1, { total: NaN }),
  deliveryPage({}, 1, { total: -1 }),
  deliveryPage({}, 21),
  deliveryPage({}, 2, { total: 1 }),
  deliveryPage({}, 2, { items: [deliveryRow(), deliveryRow()] }),
])("rejects unverifiable envelopes %#", (raw) =>
  expect(() => normalizeDeliveryPage(raw, initial)).toThrow(),
);
it.each([
  { id: "" },
  { order_id: null },
  { status: { value: "EN_ROUTE" } },
  { total_time: -1 },
  { total_time: Infinity },
  { total_time: "0" },
  { sla_compliant: 0 },
  { rider: { id: "other" } },
  { customer_name: [] },
  { external_id: "x".repeat(501) },
])("rejects invalid row %j", (change) =>
  expect(() =>
    normalizeDeliveryPage(
      deliveryPage({}, 1, { items: [deliveryRow(1, change)] }),
      initial,
    ),
  ).toThrow(),
);
it.each([
  { status: "FALLIDA" },
  { assignment: "unassigned" },
  { rider: "00000000-0000-0000-0000-000000000200" },
])("rejects rows outside server filter %j", (query) =>
  expect(() =>
    normalizeDeliveryPage(deliveryPage(query as never), {
      ...initial,
      ...query,
    } as never),
  ).toThrow(),
);
it("validates assigned and unassigned filter results separately", () => {
  expect(
    normalizeDeliveryPage(deliveryPage(), {
      ...initial,
      assignment: "assigned",
    }).rows,
  ).toHaveLength(1);
  const raw = deliveryPage({}, 1, {
    items: [
      deliveryRow(1, {
        rider_id: null,
        rider: null,
        status: null,
        total_time: null,
        sla_compliant: null,
      }),
    ],
  });
  const row = normalizeDeliveryPage(raw, {
    ...initial,
    assignment: "unassigned",
  }).rows[0];
  expect(row).toMatchObject({
    riderId: null,
    riderName: null,
    status: null,
    minutes: null,
    sla: null,
  });
  expect(() =>
    normalizeDeliveryPage(raw, { ...initial, assignment: "assigned" }),
  ).toThrow();
});
it("accepts an empty page after concurrent shrink without fabricating a new offset", () =>
  expect(
    normalizeDeliveryPage(deliveryPage({ offset: 40 }, 0, { total: 2 }), {
      ...initial,
      offset: 40,
    }),
  ).toMatchObject({ total: 2, rows: [], query: { offset: 40 } }));
it.each([
  "Jóse",
  "jose",
  " ana ",
  "delivery-1",
  "order-1",
  riderId,
  "en_route",
])("searches page IDs and human text with %s", (term) => {
  const rows = normalizeDeliveryPage(deliveryPage(), initial).rows;
  expect(searchDeliveries(rows, term)).toHaveLength(1);
  expect(searchDeliveries(rows, "absent")).toHaveLength(0);
});
it("uses only actual reference metadata in search", () => {
  const rows = normalizeDeliveryPage(deliveryPage(), initial).rows;
  expect(searchDeliveries(rows, "ORD-")).toHaveLength(0);
  expect(searchDeliveries(rows, " ")).toHaveLength(1);
});
const duration = (changes: Record<string, unknown>) =>
  ({
    minutes: null,
    started: "2026-11-07T10:00:00",
    completed: null,
    status: "EN_ROUTE",
    ...changes,
  }) as Parameters<typeof deliveryDuration>[0];
it.each([
  [0, "0 min"],
  [0.5, "0.5 min"],
  [12, "12 min"],
])("preserves provided duration %s", (minutes, expected) =>
  expect(deliveryDuration(duration({ minutes }))).toBe(expected),
);
it.each([
  "2026-11-07T10:00:00",
  "2026-11-07T10:00:00Z",
  "2026-11-07T06:00:00-04:00",
  "2026-11-07T10:00:00.000000",
])("treats API timestamp %s as the same instant", (started) =>
  expect(
    deliveryDuration(duration({ started }), Date.parse("2026-11-07T10:02:59Z")),
  ).toBe("2 min · en curso"),
);
it.each([
  { started: null },
  { started: "bad" },
  { started: "2026-02-30T10:00:00" },
  { started: "2026-11-07T25:00:00" },
  { started: "2026-11-07T10:70:00" },
  { completed: "bad" },
  { completed: "2026-11-07T09:00:00Z" },
  { status: "COMPLETADA" },
  { status: "FALLIDA" },
  { status: "PENDIENTE" },
  { status: "FUTURE" },
  { status: null },
])("does not invent elapsed duration for %j", (value) =>
  expect(
    deliveryDuration(duration(value), Date.parse("2026-11-07T10:03:00Z")),
  ).toBe("Duración no informada"),
);
it("uses the completed timestamp rather than now for a terminal record", () =>
  expect(
    deliveryDuration(
      duration({ completed: "2026-11-07T10:02:00Z", status: "COMPLETADA" }),
    ),
  ).toBe("2 min"));
