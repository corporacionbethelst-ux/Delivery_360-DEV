import {
  validateOrderPricing,
  type ExactOrderPricing,
} from "@/lib/order-pricing";

export type OperationalPrice =
  | { state: "exact"; pricing: ExactOrderPricing }
  | { state: "unavailable" }
  | { state: "review" };

/** Only the versioned price is evidence of exact money; legacy aliases stay unused. */
export function operationalOrderPrice(value: unknown): OperationalPrice {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return { state: "review" };
  const order = value as Record<string, unknown>;
  if (order.pricing == null) return { state: "unavailable" };
  try {
    if (order.currency !== "USD") throw new Error("Moneda contradictoria");
    return { state: "exact", pricing: validateOrderPricing(order.pricing) };
  } catch {
    return { state: "review" };
  }
}

/** A separately fetched order must confirm both sides of the delivery link. */
export function assertDeliveryPriceLink(
  value: unknown,
  orderId: string,
  deliveryId: string,
): void {
  const order = value as Record<string, unknown> | null;
  const delivery = order?.delivery as Record<string, unknown> | null;
  if (
    !order ||
    order.id !== orderId ||
    !delivery ||
    delivery.id !== deliveryId ||
    delivery.order_id !== orderId
  )
    throw new Error(
      "El vínculo entre la entrega y su orden requiere revisión.",
    );
}
