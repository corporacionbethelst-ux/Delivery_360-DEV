"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, ReceiptText, ArrowRightLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { moneyText, exactVes, type BcvRate } from "@/lib/currency";
import type { ExactOrderPricing } from "@/lib/order-pricing";
import type {
  OrderQuoteContext,
  OrderQuoteInput,
  OrderCurrencyQuote,
} from "@/lib/order-currency-quote";
import { orderCurrencyQuoteService as service } from "@/services/order-currency-quote.service";
import { useAuthStore } from "@/stores/authStore";

type Proposal = {
  body: OrderQuoteInput;
  pricing: ExactOrderPricing;
  rate: BcvRate;
  amount_ves: string;
};
const message = (problem: unknown): string => {
  const error = problem as {
    response?: { data?: { detail?: unknown; message?: unknown } };
    message?: string;
  };
  return typeof error.response?.data?.detail === "string"
    ? error.response.data.detail
    : typeof error.response?.data?.message === "string"
      ? error.response.data.message
      : error.message || "No se pudo consultar el comprobante.";
};

export function OrderCurrencyQuotePanel({ orderId }: { orderId: string }) {
  const user = useAuthStore((s) => s.user),
    generation = useAuthStore((s) => s.sessionRevision);
  if (
    !user ||
    !["SUPERADMIN", "GERENTE", "OPERADOR", "AUDITOR"].includes(user.role)
  )
    return null;
  return (
    <Panel
      key={JSON.stringify([orderId, user.id, user.role, generation])}
      orderId={orderId}
      canWrite={user.role !== "AUDITOR"}
    />
  );
}

function Panel({ orderId, canWrite }: { orderId: string; canWrite: boolean }) {
  const [context, setContext] = useState<OrderQuoteContext | null>(null),
    [selected, setSelected] = useState<OrderCurrencyQuote | null>(null);
  const [review, setReview] = useState<Proposal | null>(null),
    [pending, setPending] = useState<Proposal | null>(null);
  const [loading, setLoading] = useState(true),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  const alive = useRef(true),
    sequence = useRef(0),
    writeBusy = useRef(false);

  const load = async () => {
    const current = ++sequence.current;
    setLoading(true);
    try {
      const result = await service.context(orderId);
      if (alive.current && sequence.current === current) setContext(result);
    } catch (problem) {
      if (alive.current && sequence.current === current) {
        setContext(null);
        setError(message(problem));
      }
    } finally {
      if (alive.current && sequence.current === current) setLoading(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    void load();
    const id = new URLSearchParams(window.location.search).get("bcv_quote");
    if (id)
      void service
        .receipt(id, orderId)
        .then((result) => {
          if (alive.current) setSelected(result);
        })
        .catch((problem) => {
          if (alive.current) setError(message(problem));
        });
    return () => {
      alive.current = false;
      sequence.current++;
    };
    // Identity changes remount this panel, retiring all private state and requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  const showReceipt = (receipt: OrderCurrencyQuote) => {
    setSelected(receipt);
    const url = new URL(window.location.href);
    url.searchParams.set("bcv_quote", receipt.id);
    window.history.replaceState(null, "", url);
  };
  const openReview = () => {
    if (
      !context?.pricing ||
      !context.current_rate ||
      pending ||
      writeBusy.current
    )
      return;
    setError(null);
    setReview({
      body: {
        request_key: crypto.randomUUID(),
        rate_id: context.current_rate.id,
        expected_pricing_revision: context.pricing.revision,
      },
      pricing: context.pricing,
      rate: context.current_rate,
      amount_ves: exactVes(
        context.pricing.total,
        context.current_rate.ves_per_usd,
      ),
    });
  };
  const save = async (proposal: Proposal) => {
    if (writeBusy.current) return;
    writeBusy.current = true;
    setSaving(true);
    setPending(proposal);
    setError(null);
    try {
      const receipt = await service.create(orderId, proposal.body);
      if (!alive.current) return;
      if (
        receipt.amount_usd !== proposal.pricing.total ||
        receipt.amount_ves !== proposal.amount_ves
      )
        throw new Error(
          "El resultado no coincide con los importes revisados. Reintenta recuperar el mismo comprobante.",
        );
      showReceipt(receipt);
      setPending(null);
      setReview(null);
      void load();
    } catch (problem) {
      if (!alive.current) return;
      const status = (problem as { response?: { status?: number } }).response
        ?.status;
      if (status === 409 || status === 412) {
        setPending(null);
        setReview(null);
        void load();
      }
      setError(message(problem));
    } finally {
      writeBusy.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const eligible =
    !!context?.pricing &&
    !!context.current_rate &&
    !["CANCELADO", "FALLIDO"].includes(context.status);
  const day = (value: string) => value.split("-").reverse().join("/");

  return (
    <section
      aria-label="Cotización BCV de la orden"
      className="rounded-xl border border-cyan-200 bg-white shadow-sm overflow-hidden"
    >
      <div className="flex items-start justify-between gap-3 bg-gradient-to-r from-indigo-600 to-cyan-600 p-4 text-white">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <ArrowRightLeft className="h-5 w-5" /> USD y bolívares de esta orden
          </h2>
          <p className="mt-1 text-sm text-cyan-50">
            Conserva el precio revisado y la referencia BCV aplicada.
          </p>
        </div>
        <Button
          type="button"
          aria-label="Actualizar referencia de la orden"
          variant="ghost"
          size="icon"
          disabled={loading || saving}
          onClick={() => {
            setError(null);
            void load();
          }}
          className="shrink-0 text-white hover:bg-white/20"
        >
          <RefreshCw className={"h-4 w-4 " + (loading ? "animate-spin" : "")} />
        </Button>
      </div>
      <div className="p-4 space-y-4">
        <p className="text-sm text-slate-600">
          Este comprobante es una cotización. No confirma cobro ni modifica
          saldos.
        </p>
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"
          >
            {error}
          </p>
        )}
        {loading && (
          <p role="status" className="text-sm text-slate-500">
            Consultando precio y referencia…
          </p>
        )}
        {!loading && context && (
          <>
            {!context.pricing ? (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                Esta orden necesita revisión de su precio y moneda antes de
                cotizar. Los importes anteriores se conservan.
              </p>
            ) : (
              <div className="rounded-lg bg-indigo-50 p-3">
                <span className="text-xs font-medium text-indigo-700">
                  Precio de la orden · revisión {context.pricing.revision}
                </span>
                <p className="text-xl font-bold text-indigo-950">
                  {moneyText(context.pricing.total, "USD")}
                </p>
              </div>
            )}
            {context.current_rate ? (
              <div className="text-sm text-slate-700">
                <p>
                  Referencia BCV del {day(context.current_rate.reference_date)}{" "}
                  · registrada para {day(context.today)}
                </p>
                <p className="font-semibold break-all">
                  1 USD = {context.current_rate.ves_per_usd.replace(".", ",")}{" "}
                  Bs.
                </p>
                <p className="text-xs text-slate-500">
                  Registro manual verificado por el responsable.{" "}
                  {context.current_rate.note}
                </p>
              </div>
            ) : (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                Falta una referencia BCV para hoy. Un superadministrador o
                gerente debe registrarla en USD / Bolívares.
              </p>
            )}
            {eligible && context.pricing && context.current_rate && (
              <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-3">
                <span className="text-xs text-cyan-800">
                  Equivalente con la referencia actual
                </span>
                <p className="text-xl font-bold text-cyan-950 break-all">
                  {moneyText(
                    exactVes(
                      context.pricing.total,
                      context.current_rate.ves_per_usd,
                    ),
                    "VES",
                  )}
                </p>
              </div>
            )}
            {canWrite && !pending && (
              <Button
                type="button"
                disabled={!eligible || loading || saving}
                onClick={openReview}
                className="w-full bg-indigo-600 hover:bg-indigo-700"
              >
                <ReceiptText className="h-4 w-4 mr-2" /> Revisar cotización de
                la orden
              </Button>
            )}
            {context.receipts.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-slate-800">
                  Comprobantes conservados · últimos {context.receipts.length}
                </h3>
                {context.receipts.map((row) => (
                  <button
                    type="button"
                    key={row.id}
                    onClick={() => showReceipt(row)}
                    className="block w-full rounded-lg border border-slate-200 p-3 text-left text-sm hover:border-indigo-300 hover:bg-indigo-50"
                  >
                    <span className="font-medium">
                      {moneyText(row.amount_usd, "USD")} →{" "}
                      {moneyText(row.amount_ves, "VES")}
                    </span>
                    <span className="block text-xs text-slate-500">
                      Precio revisión {row.pricing.revision} · referencia{" "}
                      {day(row.rate.valid_on)}
                    </span>
                  </button>
                ))}
                {context.has_more && (
                  <p className="text-xs text-slate-500">
                    Hay más comprobantes anteriores; sus enlaces conservados
                    permiten recuperarlos.
                  </p>
                )}
              </div>
            )}
          </>
        )}
        {pending && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-2">
            <p className="text-sm text-amber-950">
              El resultado está pendiente de confirmar. El reintento recupera la
              misma solicitud, aunque hayan cambiado el precio o la tasa.
            </p>
            <Button
              type="button"
              disabled={saving}
              onClick={() => void save(pending)}
              className="w-full"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}{" "}
              Reintentar comprobante pendiente
            </Button>
          </div>
        )}
        {selected && (
          <div
            aria-label="Comprobante conservado"
            className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 space-y-2"
          >
            <h3 className="font-semibold text-emerald-950">
              Cotización guardada
            </h3>
            <p className="font-bold text-lg text-emerald-950 break-all">
              {moneyText(selected.amount_usd, "USD")} →{" "}
              {moneyText(selected.amount_ves, "VES")}
            </p>
            <p className="text-sm text-emerald-900">
              Precio revisión {selected.pricing.revision} · referencia del{" "}
              {day(selected.rate.reference_date)}, aplicada el{" "}
              {day(selected.rate.valid_on)}.
            </p>
            {context?.pricing &&
              context.pricing.revision !== selected.pricing.revision && (
                <p className="rounded bg-amber-100 p-2 text-sm text-amber-950">
                  El precio actual de la orden cambió. Este comprobante conserva
                  su revisión anterior.
                </p>
              )}
            <p className="text-xs text-emerald-900">
              La tasa y los importes de este documento se conservan. No es un
              recibo de pago.
            </p>
            <p className="font-mono text-xs break-all text-emerald-800">
              {selected.id}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                const url = new URL(window.location.href);
                url.searchParams.set("bcv_quote", selected.id);
                void navigator.clipboard
                  ?.writeText(url.toString())
                  .catch(() =>
                    setError(
                      "No se pudo copiar el enlace; puedes conservar la dirección del navegador.",
                    ),
                  );
              }}
            >
              Copiar enlace del comprobante
            </Button>
          </div>
        )}
      </div>
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open && !saving) setReview(null);
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Revisar cotización de esta orden</DialogTitle>
            <DialogDescription>
              Confirma los importes y la referencia antes de conservar el
              comprobante. No registra un cobro.
            </DialogDescription>
          </DialogHeader>
          {review && (
            <div className="space-y-3">
              <p className="text-sm text-slate-600 break-all">
                Orden {context?.order_external_id || orderId} · precio revisión{" "}
                {review.pricing.revision}
              </p>
              <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-cyan-50 p-4">
                <p className="font-bold text-lg">
                  {moneyText(review.pricing.total, "USD")}
                </p>
                <p className="font-bold text-2xl text-cyan-900 break-all">
                  {moneyText(review.amount_ves, "VES")}
                </p>
              </div>
              <p className="text-sm">
                Referencia BCV del {day(review.rate.reference_date)} · aplicada
                el {day(review.rate.valid_on)} · 1 USD ={" "}
                {review.rate.ves_per_usd.replace(".", ",")} Bs.
              </p>
              {error && (
                <p role="alert" className="text-sm text-red-800">
                  {error}
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() => setReview(null)}
            >
              {pending ? "Cerrar revisión" : "Cancelar"}
            </Button>
            <Button
              type="button"
              disabled={saving}
              onClick={() => {
                const proposal = pending ?? review;
                if (proposal) void save(proposal);
              }}
              className="bg-indigo-600 hover:bg-indigo-700"
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{" "}
              {pending ? "Reintentar comprobante" : "Guardar cotización"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
