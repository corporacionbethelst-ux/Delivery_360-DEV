import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  normalizeDeliveryPage,
  prepareDeliveryQuery,
  type DeliveryQuery,
} from "@/lib/delivery-catalog";

export async function readDeliveryPage(input: DeliveryQuery) {
  const task = capturePrivateTask(),
    query = prepareDeliveryQuery(input);
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.status !== "ALL") params.set("status", query.status);
  if (query.rider) params.set("rider_id", query.rider);
  if (query.assignment !== "ALL")
    params.set("unassigned", String(query.assignment === "unassigned"));
  try {
    const raw = await api.get<unknown>(`/deliveries/page?${params}`);
    task.assertCurrent();
    return normalizeDeliveryPage(raw, query);
  } catch (error) {
    task.assertCurrent();
    throw error;
  }
}
