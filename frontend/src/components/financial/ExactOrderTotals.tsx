import type { ExactOrderAggregate } from "@/lib/order-pricing";
import { moneyText } from "@/lib/currency";

export function ExactOrderTotals({ value }: { value?: ExactOrderAggregate }) {
  if (!value) return null;
  return (
    <section
      aria-label="Órdenes con precio exacto"
      className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-cyan-50 p-4 text-emerald-950 space-y-2"
    >
      <h2 className="font-semibold">Órdenes con precio exacto · USD</h2>
      <dl className="grid gap-3 sm:grid-cols-3">
        {[
          ["Productos", value.subtotal],
          ["Envíos", value.delivery_fee],
          ["Total", value.total],
        ].map(([label, amount]) => (
          <div key={label}>
            <dt className="text-sm">{label}</dt>
            <dd className="font-bold break-all">{moneyText(amount, "USD")}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs">
        {value.order_count} órdenes con cálculo decimal confirmado en este
        rango. {value.legacy_order_count} órdenes históricas USD conservan sus
        importes anteriores y quedan fuera de estos totales exactos. Los
        indicadores generales mantienen su criterio contable.
      </p>
    </section>
  );
}
