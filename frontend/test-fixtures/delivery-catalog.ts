import { firstDeliveryQuery, type DeliveryQuery } from "@/lib/delivery-catalog";
export const riderId = "00000000-0000-0000-0000-000000000100";
export const deliveryRow = (
  index = 1,
  changes: Record<string, unknown> = {},
) => ({
  id: `delivery-${index}`,
  order_id: `order-${index}`,
  external_id: null,
  customer_name: "José Cliente",
  rider_id: riderId,
  rider: { id: riderId, first_name: "Ana", last_name: "Rider" },
  status: "EN_ROUTE",
  started_at: "2026-11-07T10:00:00",
  completed_at: null,
  total_time: 0,
  sla_compliant: false,
  ...changes,
});
export const deliveryPage = (
  query: Partial<DeliveryQuery> = {},
  count = 1,
  changes: Record<string, unknown> = {},
) => {
  const q = { ...firstDeliveryQuery, ...query };
  return {
    items: Array.from({ length: count }, (_, i) =>
      deliveryRow(q.offset + i + 1),
    ),
    total: Math.max(count + q.offset, 45),
    limit: q.limit,
    offset: q.offset,
    ...changes,
  };
};
export function deliveryHttp(url: string) {
  const query = new URL(url, "http://local").searchParams;
  const q = {
    ...firstDeliveryQuery,
    limit: Number(query.get("limit")),
    offset: Number(query.get("offset")),
    status: query.get("status") || "ALL",
  };
  const raw = deliveryPage(q, Math.min(q.limit, Math.max(0, 45 - q.offset)));
  raw.items = raw.items.map((row) => ({
    ...row,
    status: q.status === "ALL" ? "EN_ROUTE" : q.status,
    rider_id:
      query.get("unassigned") === "true"
        ? null
        : query.get("rider_id") || riderId,
    rider:
      query.get("unassigned") === "true"
        ? null
        : {
            id: query.get("rider_id") || riderId,
            first_name: "Ana",
            last_name: "Rider",
          },
  })) as typeof raw.items;
  return raw;
}
