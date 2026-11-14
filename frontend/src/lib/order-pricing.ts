import { moneyText } from "@/lib/currency";

export type DecimalInput = string | number;
export type PriceLineInput = Record<string, unknown> & {
  quantity?: DecimalInput | null;
  unit_price?: DecimalInput | null;
  subtotal?: DecimalInput | null;
};
export type ExactPriceLine = Record<string, unknown> & {
  quantity: string | null;
  unit_price: string | null;
  subtotal: string;
};
export interface ExactOrderPricing {
  version: 1;
  currency: "USD";
  revision: number;
  subtotal: string;
  delivery_fee: string;
  total: string;
  items: ExactPriceLine[];
}
export interface ExactOrderAggregate {
  scope: "exact_usd_only";
  currency: "USD";
  order_count: number;
  legacy_order_count: number;
  subtotal: string;
  delivery_fee: string;
  total: string;
}
const MAX = BigInt("9999999999");
const invalid = (): never => {
  throw new Error(
    "Revisa los precios: importes de hasta dos decimales, cantidades positivas y totales coherentes.",
  );
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}
export function moneyInput(value: unknown): string {
  if (typeof value !== "string" && typeof value !== "number") return invalid();
  const text = String(value).trim().replace(",", ".");
  if (!/^(?:0|[1-9]\d{0,7})(?:\.\d{1,2})?$/.test(text)) return invalid();
  const [units, fraction = ""] = text.split(".");
  return units + "." + fraction.padEnd(2, "0");
}
export function quantityInput(value: unknown): string {
  if (typeof value !== "string" && typeof value !== "number") return invalid();
  const text = String(value).trim().replace(",", ".");
  if (
    !/^(?:0|[1-9]\d{0,5})(?:\.\d{1,3})?$/.test(text) ||
    BigInt(text.replace(".", "")) <= BigInt(0)
  )
    return invalid();
  return text;
}
const cents = (value: string) => BigInt(value.replace(".", ""));
const text = (value: bigint) =>
  (value / BigInt(100)).toString() +
  "." +
  (value % BigInt(100)).toString().padStart(2, "0");
function bounded(value: bigint): bigint {
  if (value < BigInt(0) || value > MAX) return invalid();
  return value;
}
export function priceOrder(
  items: readonly PriceLineInput[],
  shipping: DecimalInput = "0.00",
  declaredSubtotal?: DecimalInput,
): Omit<ExactOrderPricing, "revision"> {
  if (!Array.isArray(items) || items.length > 200) return invalid();
  const lines: ExactPriceLine[] = items.map((value) => {
    const item = object(value);
    if (
      item.quantity == null &&
      item.unit_price == null &&
      item.subtotal != null
    )
      return {
        ...item,
        quantity: null,
        unit_price: null,
        subtotal: moneyInput(item.subtotal),
      };
    const quantity = quantityInput(item.quantity),
      unit_price = moneyInput(item.unit_price),
      [units, part = ""] = quantity.split(".");
    const scaled = BigInt(units + part.padEnd(3, "0"));
    const subtotal = text(
      bounded((scaled * cents(unit_price) + BigInt(500)) / BigInt(1000)),
    );
    if (item.subtotal != null && moneyInput(item.subtotal) !== subtotal)
      return invalid();
    return { ...item, quantity, unit_price, subtotal };
  });
  const sum = bounded(
    lines.reduce((sum, item) => sum + cents(item.subtotal), BigInt(0)),
  );
  const base =
    declaredSubtotal === undefined ? sum : cents(moneyInput(declaredSubtotal));
  if (lines.length && base !== sum) return invalid();
  const delivery_fee = moneyInput(shipping);
  return {
    version: 1,
    currency: "USD",
    subtotal: text(base),
    delivery_fee,
    total: text(bounded(base + cents(delivery_fee))),
    items: lines,
  };
}
export function validateOrderPricing(value: unknown): ExactOrderPricing {
  const p = object(value);
  if (
    p.version !== 1 ||
    p.currency !== "USD" ||
    !Number.isSafeInteger(p.revision) ||
    Number(p.revision) < 1 ||
    Number(p.revision) > 2147483647 ||
    !Array.isArray(p.items)
  )
    return invalid();
  for (const key of ["subtotal", "delivery_fee", "total"] as const)
    if (typeof p[key] !== "string" || moneyInput(p[key]) !== p[key])
      return invalid();
  const price = priceOrder(
    p.items as PriceLineInput[],
    p.delivery_fee as string,
    p.subtotal as string,
  );
  if (price.total !== p.total) return invalid();
  for (let i = 0; i < price.items.length; i++) {
    const raw = object(p.items[i]);
    if (
      raw.quantity !== price.items[i].quantity ||
      raw.unit_price !== price.items[i].unit_price ||
      raw.subtotal !== price.items[i].subtotal
    )
      return invalid();
  }
  return { ...price, revision: Number(p.revision) };
}
export function checkedOrder<
  T extends {
    currency?: string | null;
    pricing?: ExactOrderPricing | null;
    subtotal?: number;
    delivery_fee?: number;
    total?: number;
    total_amount?: number;
  },
>(order: T): T {
  if (order.pricing == null) return order;
  const pricing = validateOrderPricing(order.pricing);
  if (order.currency !== "USD") return invalid();
  for (const key of ["subtotal", "delivery_fee", "total"] as const)
    if (order[key] == null || moneyInput(order[key]) !== pricing[key])
      return invalid();
  if (
    order.total_amount != null &&
    moneyInput(order.total_amount) !== pricing.total
  )
    return invalid();
  return { ...order, pricing };
}
export function preparePricePayload<
  T extends {
    items?: readonly PriceLineInput[];
    subtotal?: DecimalInput;
    delivery_fee?: DecimalInput;
    total?: DecimalInput;
    declared_value?: DecimalInput;
  },
>(input: T): T {
  const data: Record<string, unknown> = { ...input };
  for (const key of [
    "subtotal",
    "delivery_fee",
    "total",
    "declared_value",
  ] as const)
    if (input[key] !== undefined) data[key] = moneyInput(input[key]);
  if (input.items) {
    const pricing = priceOrder(
      input.items,
      input.delivery_fee ?? "0.00",
      input.subtotal,
    );
    data.items = pricing.items;
    if (
      input.delivery_fee !== undefined &&
      input.total !== undefined &&
      moneyInput(input.total) !== pricing.total
    )
      return invalid();
  }
  return data as T;
}
export const exactMoneyLabel = (value: string | undefined): string =>
  value === undefined ? "Por confirmar" : moneyText(value, "USD");
export function validateExactAggregate(value: unknown): ExactOrderAggregate {
  const p = object(value);
  if (
    p.scope !== "exact_usd_only" ||
    p.currency !== "USD" ||
    ![p.order_count, p.legacy_order_count].every(
      (x) => typeof x === "number" && Number.isSafeInteger(x) && x >= 0,
    )
  )
    return invalid();
  for (const key of ["subtotal", "delivery_fee", "total"])
    if (
      typeof p[key] !== "string" ||
      !/^(?:0|[1-9]\d{0,21})\.\d{2}$/.test(p[key] as string)
    )
      return invalid();
  if (
    cents(p.subtotal as string) + cents(p.delivery_fee as string) !==
    cents(p.total as string)
  )
    return invalid();
  return p as unknown as ExactOrderAggregate;
}
