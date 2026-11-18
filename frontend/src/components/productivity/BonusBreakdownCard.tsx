"use client";
import { BadgeDollarSign, Info, MapPin, Award } from "lucide-react";
import type { BonusRecord } from "@/lib/delivery-bonus-exact";
import { exactTransactionMoney as payoutAmountLabel } from "@/lib/transaction-exact";
import { decimalText, settingsTime } from "@/lib/bonus-settings-exact";
export function BonusBreakdownCard({
  snapshot,
  hideIfEmpty = true,
  compact = false,
}: {
  snapshot: BonusRecord | null;
  hideIfEmpty?: boolean;
  compact?: boolean;
}) {
  if (!snapshot && hideIfEmpty) return null;
  const label = (value: string | null, field: string) =>
    payoutAmountLabel(
      value,
      snapshot?.currency ?? null,
      !!snapshot?.money_review.some((i) => i.field === field),
    );
  return (
    <section
      aria-label="Bono conservado"
      className={`min-w-0 rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 via-white to-teal-50 ${compact ? "p-3" : "p-5"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-emerald-950">
          <BadgeDollarSign aria-hidden="true" className="h-4 w-4" />
          Bono conservado
        </p>
        <p className="break-words text-right text-lg font-bold text-emerald-900">
          {snapshot
            ? label(snapshot.amount, "locked_bonus_amount")
            : "Bono por confirmar"}
        </p>
      </div>
      {!snapshot ? (
        <p className="mt-2 text-xs text-slate-600">
          No se pudo confirmar el snapshot. El importe no se reemplaza por cero.
        </p>
      ) : (
        <>
          {snapshot.source === "order_without_delivery" ? (
            <p className="mt-2 text-xs text-slate-600">
              La orden no tiene entrega registrada. No hay un bono conservado.
            </p>
          ) : (
            <>
              {snapshot.amount === null &&
                !snapshot.money_review.some(
                  (i) => i.field === "locked_bonus_amount",
                ) && (
                  <p className="mt-2 text-xs text-slate-600">
                    Sin importe de bono guardado para este cierre o estado.
                  </p>
                )}
              <dl className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
                <div>
                  <dt className="text-slate-600">Base registrada</dt>
                  <dd className="font-medium text-slate-900">
                    {label(snapshot.base, "locked_bonus_base")}
                  </dd>
                </div>
                <div>
                  <dt className="flex items-center gap-1 text-slate-600">
                    <MapPin aria-hidden="true" className="h-3 w-3" />
                    Factor zona
                  </dt>
                  <dd>
                    {snapshot.zone_multiplier === null
                      ? "No informado"
                      : decimalText(snapshot.zone_multiplier) + " ×"}
                  </dd>
                </div>
                <div>
                  <dt className="flex items-center gap-1 text-slate-600">
                    <Award aria-hidden="true" className="h-3 w-3" />
                    Factor nivel
                  </dt>
                  <dd>
                    {snapshot.tier_multiplier === null
                      ? "No informado"
                      : decimalText(snapshot.tier_multiplier) + " ×"}{" "}
                    · {snapshot.tier_level ?? "Nivel no informado"}
                  </dd>
                </div>
              </dl>
              {snapshot.snapshot_date && (
                <p className="mt-2 text-xs text-slate-500">
                  Conservado: {settingsTime(snapshot.snapshot_date)} ·
                  America/Caracas.
                </p>
              )}
            </>
          )}
          {(snapshot.state_review ||
            snapshot.currency_review ||
            snapshot.money_review.length > 0 ||
            snapshot.config_warning) && (
            <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-950">
              Requiere revisión. {snapshot.config_warning}
              {snapshot.currency_review &&
                ` Moneda registrada por revisar: ${snapshot.currency_recorded ?? "No informada"}.`}
            </p>
          )}
          {snapshot.currency === null &&
            !snapshot.currency_review &&
            snapshot.amount !== null && (
              <p className="mt-2 text-xs text-amber-900">
                Moneda no informada en este bono; no se deduce desde la orden o
                un movimiento.
              </p>
            )}
        </>
      )}
      <p className="mt-3 flex items-start gap-1 text-xs text-slate-600">
        <Info aria-hidden="true" className="mt-0.5 h-3 w-3 shrink-0" />
        Componentes guardados, sin recalcular importes. Este bono no acredita
        saldo disponible ni pago bancario.
      </p>
    </section>
  );
}
