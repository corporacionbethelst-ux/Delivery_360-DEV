"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Receipt, RefreshCw } from "lucide-react";
import { moneyText } from "@/lib/currency";
import {
  operationalOrderPrice,
  assertDeliveryPriceLink,
} from "@/lib/operational-order-price";
import { capturePrivateTask } from "@/lib/private-task";
import { orderService } from "@/services/order.service";

function PriceNotice({ review = false }: { review?: boolean }) {
  return (
    <p
      role={review ? "alert" : undefined}
      className="flex items-start gap-2 text-sm leading-relaxed text-amber-900"
    >
      <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      {review
        ? "Precio por revisar. Vuelve a consultar la orden antes de usar sus importes."
        : "Precio versionado no disponible. Los importes anteriores requieren revisión antes de cobrar."}
    </p>
  );
}

export function OrderPriceAmount({ order }: { order: unknown }) {
  const result = operationalOrderPrice(order);
  return result.state === "exact" ? (
    <div className="space-y-1">
      <span className="font-bold text-emerald-800">
        {moneyText(result.pricing.total, "USD")}
      </span>
      <p className="text-xs font-normal text-slate-500">
        Revisión {result.pricing.revision}
      </p>
    </div>
  ) : (
    <span className="text-sm font-medium text-amber-900">
      {result.state === "review"
        ? "Precio por revisar"
        : "Precio no disponible"}
    </span>
  );
}

export function OrderPriceSummary({
  order,
  items = false,
}: {
  order: unknown;
  items?: boolean;
}) {
  const result = operationalOrderPrice(order);
  return (
    <section
      aria-label="Precio registrado de la orden"
      className="min-w-0 overflow-hidden rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 via-white to-emerald-50 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-blue-100 p-5">
        <h2 className="flex items-center gap-2 font-bold text-slate-900">
          <Receipt aria-hidden="true" className="h-5 w-5 text-blue-700" />
          Precio registrado
        </h2>
        {result.state === "exact" && (
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-900">
            USD · Revisión {result.pricing.revision}
          </span>
        )}
      </div>
      <div className="space-y-4 p-5">
        {result.state !== "exact" ? (
          <PriceNotice review={result.state === "review"} />
        ) : (
          <>
            <dl className="space-y-3 text-sm">
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-slate-600">Subtotal</dt>
                <dd className="font-semibold">
                  {moneyText(result.pricing.subtotal, "USD")}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt className="text-slate-600">Envío registrado</dt>
                <dd className="font-semibold">
                  {moneyText(result.pricing.delivery_fee, "USD")}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2 border-t border-blue-100 pt-4">
                <dt className="font-bold">Precio total</dt>
                <dd className="text-xl font-bold text-emerald-800">
                  {moneyText(result.pricing.total, "USD")}
                </dd>
              </div>
            </dl>
            {items && <OrderPriceItems order={order} />}
            <p className="text-xs leading-relaxed text-slate-600">
              Precio de esta revisión. Los cobros, el saldo pendiente y el bono
              del repartidor se consultan por separado.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

export function OrderPriceItems({ order }: { order: unknown }) {
  const result = operationalOrderPrice(order);
  if (result.state === "unavailable" && order && typeof order === "object") {
    const previous = (order as { items?: unknown }).items;
    if (Array.isArray(previous) && previous.length > 0)
      return (
        <section
          aria-label="Artículos anteriores"
          className="rounded-xl border border-amber-200 bg-white p-4"
        >
          <h2 className="font-semibold text-slate-900">Artículos anteriores</h2>
          <p className="mt-1 text-sm text-amber-900">
            Se conserva su descripción. Los precios requieren revisión.
          </p>
          <ul className="mt-3 divide-y divide-slate-100">
            {previous.map((value, index) => {
              const item =
                value && typeof value === "object"
                  ? (value as Record<string, unknown>)
                  : {};
              return (
                <li
                  key={index}
                  className="break-words py-3 text-sm text-slate-700"
                >
                  {typeof item.product_name === "string"
                    ? item.product_name
                    : typeof item.name === "string"
                      ? item.name
                      : "Producto sin nombre"}
                </li>
              );
            })}
          </ul>
        </section>
      );
  }
  if (result.state !== "exact" || !result.pricing.items.length) return null;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <caption className="p-3 text-left font-semibold text-slate-700">
          Artículos del precio registrado
        </caption>
        <thead className="border-y border-slate-200 bg-slate-50 text-xs text-slate-600">
          <tr>
            <th scope="col" className="p-3">
              Producto
            </th>
            <th scope="col" className="p-3">
              Cantidad
            </th>
            <th scope="col" className="p-3">
              Precio unitario
            </th>
            <th scope="col" className="p-3">
              Subtotal
            </th>
          </tr>
        </thead>
        <tbody>
          {result.pricing.items.map((line, index) => (
            <tr key={index} className="border-t border-slate-100">
              <td className="max-w-48 break-words p-3">
                {typeof line.product_name === "string"
                  ? line.product_name
                  : typeof line.name === "string"
                    ? line.name
                    : "Producto sin nombre"}
              </td>
              <td className="p-3">{line.quantity ?? "No registrada"}</td>
              <td className="whitespace-nowrap p-3">
                {line.unit_price === null
                  ? "No informado"
                  : moneyText(line.unit_price, "USD")}
              </td>
              <td className="whitespace-nowrap p-3 font-semibold">
                {moneyText(line.subtotal, "USD")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LinkedDeliveryOrderPrice({
  orderId,
  deliveryId,
}: {
  orderId: unknown;
  deliveryId: string;
}) {
  return (
    <LinkedPriceContent
      key={JSON.stringify([
        typeof orderId === "string" ? orderId : null,
        deliveryId,
      ])}
      orderId={orderId}
      deliveryId={deliveryId}
    />
  );
}

function LinkedPriceContent({
  orderId,
  deliveryId,
}: {
  orderId: unknown;
  deliveryId: string;
}) {
  const [order, setOrder] = useState<unknown>(null),
    [error, setError] = useState<string | null>(null),
    [loading, setLoading] = useState(true);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    setError(null);
    let current = () => ticket === sequence.current;
    try {
      const task = capturePrivateTask();
      current = () => ticket === sequence.current && task.isCurrent();
      if (typeof orderId !== "string" || !orderId.trim())
        throw new Error("La entrega no tiene una orden identificada.");
      const value = await orderService.getById(orderId);
      if (!current()) return;
      assertDeliveryPriceLink(value, orderId, deliveryId);
      setOrder(value);
    } catch {
      if (current())
        setError(
          "No se pudo confirmar el precio de la orden vinculada. Reintenta la consulta.",
        );
    } finally {
      if (current()) setLoading(false);
    }
  }, [orderId, deliveryId]);
  useEffect(() => {
    setOrder(null);
    void load();
    return () => {
      sequence.current++;
    };
  }, [load]);
  return (
    <div className="space-y-3">
      {loading && (
        <p role="status" className="text-sm text-slate-600">
          Consultando precio registrado…
        </p>
      )}
      {error && (
        <div
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
        >
          {error}
          {order !== null && " Se conserva la última lectura confirmada."}
        </div>
      )}
      {order !== null && <OrderPriceSummary order={order} />}
      {!loading && (
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-blue-200 bg-white px-4 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-50"
        >
          <RefreshCw aria-hidden="true" className="h-4 w-4" />
          {error ? "Reintentar precio" : "Actualizar precio"}
        </button>
      )}
    </div>
  );
}
