"use client";
import { useEffect, useRef, useState } from "react";
import { Banknote, RefreshCw, ShieldCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { moneyText, canonicalDecimal, exactVes } from "@/lib/currency";
import { moneyInput } from "@/lib/order-pricing";
import {
  collectionKey,
  collectionCents,
  type CollectionInput,
  type CollectionReviewInput,
  type CollectionContext,
  type CustomerCollection,
  type CollectionMethod,
} from "@/lib/customer-collections";
import { customerCollectionsService as service } from "@/services/customer-collections.service";
import { useAuthStore } from "@/stores/authStore";

type Proposal =
  | { kind: "declare"; body: CollectionInput }
  | {
      kind: "review";
      id: string;
      body: CollectionReviewInput;
      entry: CustomerCollection;
    };
const problemText = (p: unknown) => {
  const e = p as {
    message?: string;
    response?: { data?: { detail?: unknown; message?: unknown } };
  };
  return typeof e.response?.data?.detail === "string"
    ? e.response.data.detail
    : typeof e.response?.data?.message === "string"
      ? e.response.data.message
      : e.message || "No se pudo consultar el cobro.";
};
const methodName = {
  EFECTIVO: "Efectivo",
  TRANSFERENCIA: "Transferencia",
  PAGO_MOVIL: "Pago móvil",
};
const statusName = {
  PENDIENTE: "Pendiente de revisión",
  VERIFICADO_MANUALMENTE: "Verificado manualmente",
  RECHAZADO: "Rechazado",
};
export function CustomerCollectionsPanel({ orderId }: { orderId: string }) {
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
      actorId={user.id}
      canDeclare={user.role !== "AUDITOR"}
      canReview={["SUPERADMIN", "GERENTE"].includes(user.role)}
    />
  );
}
function Panel({
  orderId,
  actorId,
  canDeclare,
  canReview,
}: {
  orderId: string;
  actorId: string;
  canDeclare: boolean;
  canReview: boolean;
}) {
  const [context, setContext] = useState<CollectionContext | null>(null),
    [loading, setLoading] = useState(true),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState(""),
    [paid, setPaid] = useState(""),
    [currency, setCurrency] = useState<"USD" | "VES">("USD"),
    [method, setMethod] = useState<CollectionMethod>("EFECTIVO"),
    [source, setSource] = useState(""),
    [reference, setReference] = useState(""),
    [quoteId, setQuoteId] = useState(""),
    [received, setReceived] = useState(false);
  const [entry, setEntry] = useState<CustomerCollection | null>(null),
    [decision, setDecision] = useState<"VERIFICADO" | "RECHAZADO">(
      "VERIFICADO",
    ),
    [note, setNote] = useState(""),
    [evidence, setEvidence] = useState(false),
    [refund, setRefund] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null),
    [pending, setPending] = useState<Proposal | null>(null),
    [saved, setSaved] = useState<CustomerCollection | null>(null);
  const alive = useRef(true),
    sequence = useRef(0),
    busy = useRef(false);
  const load = async () => {
    const seq = ++sequence.current;
    setLoading(true);
    try {
      const value = await service.context(orderId);
      if (alive.current && seq === sequence.current) setContext(value);
    } catch (p) {
      if (alive.current && seq === sequence.current) {
        setContext(null);
        setError(problemText(p));
      }
    } finally {
      if (alive.current && seq === sequence.current) setLoading(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    void load();
    const id = new URLSearchParams(window.location.search).get(
      "customer_collection",
    );
    if (id)
      void service
        .receipt(orderId, id)
        .then((value) => {
          if (alive.current) setSaved(value);
        })
        .catch((p) => {
          if (alive.current) setError(problemText(p));
        });
    return () => {
      alive.current = false;
      sequence.current++;
    }; // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);
  const terminal =
      !!context &&
      ["CANCELADO", "FALLIDO"].includes(context.order_status ?? ""),
    disabled = saving || !!pending || loading;
  const quote = context?.ves_quotes.find((q) => q.id === quoteId);
  let equivalent: string | null = null;
  try {
    if (quote && amount)
      equivalent = exactVes(moneyInput(amount), quote.rate.ves_per_usd);
  } catch {
    /* incomplete amount */
  }
  const prepareDeclaration = (event: React.FormEvent) => {
    event.preventDefault();
    if (!context?.pricing || disabled || terminal || !received) return;
    setError(null);
    try {
      const usd = moneyInput(amount),
        actual =
          currency === "USD"
            ? moneyInput(paid)
            : canonicalDecimal(paid, 2, 21)
                .split(".")
                .map((p, i) => (i === 1 ? p.padEnd(2, "0") : p))
                .join(".");
      const paidAmount = actual.includes(".") ? actual : actual + ".00";
      if (
        collectionCents(usd) <= BigInt(0) ||
        collectionCents(usd) >
          collectionCents(context.summary.available_to_declare_usd ?? "0.00")
      )
        throw new Error(
          "El abono supera el importe disponible o no es positivo.",
        );
      if (
        currency === "USD"
          ? usd !== paidAmount
          : !quote || paidAmount !== exactVes(usd, quote.rate.ves_per_usd)
      )
        throw new Error(
          "El importe recibido no coincide con el abono USD y su referencia BCV.",
        );
      if (method === "PAGO_MOVIL" && currency !== "VES")
        throw new Error("Pago móvil se registra en bolívares.");
      setProposal({
        kind: "declare",
        body: {
          request_key: crypto.randomUUID(),
          expected_pricing_revision: context.pricing.revision,
          expected_collection_revision: context.collection_revision,
          amount_usd: usd,
          paid_amount: paidAmount,
          paid_currency: currency,
          method,
          source_key: collectionKey(source),
          reference_key: collectionKey(reference),
          received_on: context.today,
          quote_id: currency === "VES" ? quoteId : null,
          confirmed_received: true,
        },
      });
    } catch (p) {
      setError(problemText(p));
    }
  };
  const prepareReview = () => {
    if (!entry || !context || disabled) return;
    setError(null);
    const clean = note.trim();
    if (clean.length < 10 || /[\x00-\x1f\x7f]/.test(clean)) {
      setError(
        "Describe la comprobación o el rechazo con al menos 10 caracteres.",
      );
      return;
    }
    if (decision === "VERIFICADO" && (!evidence || (terminal && !refund))) {
      setError(
        "Confirma la evidencia y, si corresponde, la devolución pendiente.",
      );
      return;
    }
    setProposal({
      kind: "review",
      id: entry.id,
      entry,
      body: {
        request_key: crypto.randomUUID(),
        expected_collection_revision: context.collection_revision,
        decision,
        note: clean,
        verified_evidence: decision === "VERIFICADO",
        acknowledge_refund_due: decision === "VERIFICADO" && terminal && refund,
      },
    });
  };
  const showReceipt = (value: CustomerCollection) => {
    setSaved(value);
    const url = new URL(window.location.href);
    url.searchParams.set("customer_collection", value.id);
    window.history.replaceState(null, "", url);
  };
  const save = async (value: Proposal) => {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setPending(value);
    setError(null);
    try {
      const result =
        value.kind === "declare"
          ? await service.declare(orderId, value.body)
          : await service.review(orderId, value.id, value.body);
      if (!alive.current) return;
      showReceipt(result);
      setPending(null);
      setProposal(null);
      setEntry(null);
      setAmount("");
      setPaid("");
      setReference("");
      setReceived(false);
      void load();
    } catch (p) {
      if (!alive.current) return;
      const code = (p as { response?: { status?: number } }).response?.status;
      if (code === 409 || code === 412) {
        setPending(null);
        setProposal(null);
        setEntry(null);
        void load();
      }
      setError(problemText(p));
    } finally {
      busy.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const inputClass =
    "mt-1 h-10 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm disabled:bg-slate-100";
  const field = (
    title: string,
    value: string,
    set: (v: string) => void,
    max = 120,
  ) => (
    <label className="block text-sm font-medium text-slate-700">
      {title}
      <input
        className={inputClass}
        value={value}
        onChange={(e) => set(e.target.value)}
        disabled={disabled}
        maxLength={max}
        required
      />
    </label>
  );
  return (
    <section
      aria-label="Cobros de clientes"
      className="overflow-hidden rounded-xl border border-emerald-200 bg-white shadow-sm"
    >
      <div className="flex items-start justify-between gap-3 bg-gradient-to-r from-emerald-700 via-teal-600 to-cyan-600 p-4 text-white">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <Banknote className="h-5 w-5" />
            Cobros de clientes
          </h2>
          <p className="mt-1 text-sm text-emerald-50">
            Abonos en USD y bolívares · revisión independiente
          </p>
        </div>
        <Button
          type="button"
          aria-label="Actualizar cobros"
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
      <div className="space-y-4 p-4">
        <p className="text-sm text-slate-600">
          Verificación manual por otro responsable, sin integración bancaria.
          Este registro de cobros no modifica los bonos ni retiros del
          repartidor.
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
            Consultando cobros…
          </p>
        )}
        {context && !loading && (
          <>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {[
                [
                  "En revisión",
                  context.summary.pending_usd,
                  "bg-amber-50 text-amber-900",
                ],
                [
                  "Verificado",
                  context.summary.verified_usd,
                  "bg-emerald-50 text-emerald-950",
                ],
                [
                  "Por cobrar",
                  context.summary.due_usd,
                  "bg-cyan-50 text-cyan-950",
                ],
              ].map(([label, value, color]) => (
                <div key={label} className={"rounded-lg p-3 " + color}>
                  <p className="text-xs font-medium">{label}</p>
                  <p className="mt-1 break-all text-lg font-bold">
                    {value ? moneyText(value, "USD") : "Revisar precio"}
                  </p>
                </div>
              ))}
            </div>
            {context.summary.refund_due_usd !== "0.00" && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                Orden cancelada o fallida:{" "}
                {moneyText(context.summary.refund_due_usd, "USD")} pendientes de
                devolución. Este panel no ejecuta reembolsos.
              </p>
            )}
            {context.price_locked && (
              <p className="flex items-start gap-2 text-sm text-emerald-800">
                <ShieldCheck className="h-5 w-5 shrink-0" />
                El precio está protegido por cobros pendientes o verificados.
              </p>
            )}
            {!context.pricing && (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
                Revisa el precio exacto en USD de esta orden antes de declarar
                cobros.
              </p>
            )}
            {canDeclare &&
              context.pricing &&
              !terminal &&
              context.summary.available_to_declare_usd !== "0.00" && (
                <form
                  onSubmit={prepareDeclaration}
                  className="space-y-3 rounded-xl border border-emerald-100 bg-gradient-to-br from-slate-50 to-emerald-50/50 p-3"
                >
                  <h3 className="font-semibold text-slate-900">
                    Declarar un abono recibido
                  </h3>
                  <p className="text-xs text-slate-600">
                    Disponible para declarar:{" "}
                    {moneyText(
                      context.summary.available_to_declare_usd!,
                      "USD",
                    )}
                    . Los cobros en revisión reservan su importe.
                  </p>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="text-sm font-medium text-slate-700">
                      Medio de cobro
                      <select
                        className={inputClass}
                        aria-label="Medio de cobro"
                        value={method}
                        disabled={disabled}
                        onChange={(e) => {
                          const m = e.target.value as CollectionMethod;
                          setMethod(m);
                          if (m === "PAGO_MOVIL") setCurrency("VES");
                        }}
                      >
                        {Object.entries(methodName).map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="text-sm font-medium text-slate-700">
                      Moneda recibida
                      <select
                        className={inputClass}
                        aria-label="Moneda recibida"
                        value={currency}
                        disabled={disabled || method === "PAGO_MOVIL"}
                        onChange={(e) => {
                          setCurrency(e.target.value as "USD" | "VES");
                          setPaid("");
                        }}
                      >
                        <option value="USD">Dólares · USD</option>
                        <option value="VES">Bolívares · VES</option>
                      </select>
                    </label>
                    {field("Abono a la orden en USD", amount, setAmount, 11)}
                    {field("Importe realmente recibido", paid, setPaid, 24)}
                  </div>
                  {currency === "VES" && (
                    <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-3">
                      <label className="block text-sm font-medium text-cyan-950">
                        Cotización BCV conservada
                        <select
                          className={inputClass}
                          aria-label="Cotización BCV conservada"
                          value={quoteId}
                          onChange={(e) => setQuoteId(e.target.value)}
                          disabled={disabled}
                          required
                        >
                          <option value="">
                            Selecciona la cotización acordada
                          </option>
                          {context.ves_quotes.map((q) => (
                            <option key={q.id} value={q.id}>
                              {q.rate.valid_on} · 1 USD = {q.rate.ves_per_usd}{" "}
                              Bs. · {q.id.slice(0, 8)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p className="mt-2 text-xs text-cyan-900">
                        {equivalent
                          ? "Importe VES esperado: " +
                            moneyText(equivalent, "VES")
                          : "Crea una cotización de la orden y actualiza este panel para seleccionarla."}
                      </p>
                    </div>
                  )}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {field(
                      "Alias interno de caja o cuenta",
                      source,
                      setSource,
                      80,
                    )}
                    {field(
                      "Referencia completa o recibo único",
                      reference,
                      setReference,
                    )}
                  </div>
                  <p className="text-xs text-slate-500">
                    Usa un alias interno; evita datos bancarios personales. No
                    reutilices la referencia de un cobro pendiente o verificado.
                    Día de recepción: {context.today} · Caracas.
                  </p>
                  <label className="flex items-start gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={received}
                      onChange={(e) => setReceived(e.target.checked)}
                      disabled={disabled}
                      className="mt-1"
                    />
                    Confirmo que el importe indicado fue recibido y requiere
                    revisión por otro responsable.
                  </label>
                  <Button
                    type="submit"
                    disabled={disabled || !received}
                    className="w-full bg-emerald-700 hover:bg-emerald-800"
                  >
                    Revisar declaración de cobro
                  </Button>
                </form>
              )}
            {context.collections.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-slate-800">
                  Historial conservado · últimos {context.collections.length}
                </h3>
                {context.collections.map((row) => (
                  <article
                    key={row.id}
                    className="rounded-lg border border-slate-200 p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <strong className="break-all">
                        {moneyText(row.amount_usd, "USD")}
                      </strong>
                      <span
                        className={
                          "rounded-full px-2 py-1 text-xs font-medium " +
                          (row.status === "PENDIENTE"
                            ? "bg-amber-100 text-amber-900"
                            : row.status === "RECHAZADO"
                              ? "bg-rose-100 text-rose-900"
                              : "bg-emerald-100 text-emerald-900")
                        }
                      >
                        {statusName[row.status]}
                      </span>
                    </div>
                    <p className="mt-2 break-all text-slate-600">
                      {methodName[row.method]} · recibido{" "}
                      {moneyText(row.paid_amount, row.paid_currency)} ·{" "}
                      {row.received_on}
                    </p>
                    <p className="break-all text-xs text-slate-500">
                      {row.source_key} · {row.reference_key}
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="mt-1 text-teal-800"
                      onClick={() => showReceipt(row)}
                    >
                      Ver registro conservado
                    </Button>
                    {row.review && (
                      <p className="mt-2 break-words text-xs text-slate-600">
                        {row.review.note}
                      </p>
                    )}
                    {canReview &&
                      row.status === "PENDIENTE" &&
                      row.declared_by !== actorId && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="mt-3"
                          disabled={disabled}
                          onClick={() => {
                            setEntry(row);
                            setNote("");
                            setEvidence(false);
                            setRefund(false);
                            setDecision("VERIFICADO");
                            setError(null);
                          }}
                        >
                          Revisar este cobro
                        </Button>
                      )}
                    {row.status === "PENDIENTE" &&
                      row.declared_by === actorId && (
                        <p className="mt-2 text-xs text-amber-800">
                          Otro gerente o superadministrador debe revisar tu
                          declaración.
                        </p>
                      )}
                  </article>
                ))}
                {context.has_more && (
                  <p className="text-xs text-slate-500">
                    Hay registros anteriores conservados. El resumen incluye
                    todos los abonos de la orden.
                  </p>
                )}
              </div>
            )}
            {entry && !pending && (
              <div
                aria-label="Revisión independiente"
                className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50 p-3"
              >
                <h3 className="font-semibold text-indigo-950">
                  Revisión independiente
                </h3>
                <p className="break-all text-sm">
                  {moneyText(entry.amount_usd, "USD")} · recibido{" "}
                  {moneyText(entry.paid_amount, entry.paid_currency)} ·{" "}
                  {entry.source_key} / {entry.reference_key}
                </p>
                <label className="block text-sm">
                  Decisión
                  <select
                    className={inputClass}
                    aria-label="Decisión"
                    value={decision}
                    onChange={(e) => {
                      setDecision(e.target.value as "VERIFICADO" | "RECHAZADO");
                      setEvidence(false);
                    }}
                  >
                    <option value="VERIFICADO">Verificar manualmente</option>
                    <option value="RECHAZADO">Rechazar declaración</option>
                  </select>
                </label>
                <label className="block text-sm">
                  Comprobación o motivo
                  <textarea
                    className={inputClass + " h-20 py-2"}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={500}
                  />
                </label>
                {decision === "VERIFICADO" && (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={evidence}
                      onChange={(e) => setEvidence(e.target.checked)}
                      className="mt-1"
                    />
                    He comprobado el efectivo o el ingreso en la cuenta
                    correspondiente. La referencia coincide y no está duplicada.
                  </label>
                )}
                {decision === "VERIFICADO" && terminal && (
                  <label className="flex items-start gap-2 text-sm text-amber-900">
                    <input
                      type="checkbox"
                      checked={refund}
                      onChange={(e) => setRefund(e.target.checked)}
                      className="mt-1"
                    />
                    Reconozco que este cobro de una orden cancelada o fallida
                    quedará pendiente de devolución.
                  </label>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={disabled}
                    onClick={prepareReview}
                  >
                    Revisar decisión
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={disabled}
                    onClick={() => setEntry(null)}
                  >
                    Cancelar revisión
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
        {pending && (
          <div
            role="status"
            className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3"
          >
            <p className="text-sm text-amber-950">
              El resultado sigue pendiente de confirmar. Reintenta la misma
              solicitud para recuperar el registro sin duplicarlo.
            </p>
            <Button
              type="button"
              disabled={saving}
              onClick={() => void save(pending)}
            >
              Reintentar solicitud de cobro
            </Button>
          </div>
        )}
        {saved && (
          <div
            aria-label="Registro de cobro conservado"
            className="space-y-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"
          >
            <p role="status" className="break-all font-semibold">
              {statusName[saved.status]} · {moneyText(saved.amount_usd, "USD")}{" "}
              · registro {saved.id}
            </p>
            <p className="break-all">
              Recibido {moneyText(saved.paid_amount, saved.paid_currency)} ·{" "}
              {methodName[saved.method]} · {saved.source_key} /{" "}
              {saved.reference_key}
            </p>
            <p className="text-xs">
              Recepción {saved.received_on} · precio revisión{" "}
              {saved.pricing.revision}
              {saved.quote
                ? " · BCV conservado " +
                  saved.quote.rate.ves_per_usd +
                  " Bs./USD"
                : ""}
            </p>
            {saved.review && (
              <p className="break-words text-xs">
                {saved.review.note} · {saved.review.reviewed_at}
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                const url = new URL(window.location.href);
                url.searchParams.set("customer_collection", saved.id);
                void navigator.clipboard
                  ?.writeText(url.toString())
                  .catch(() =>
                    setError(
                      "Conserva la dirección del navegador para recuperar este registro.",
                    ),
                  );
              }}
            >
              Copiar enlace del cobro
            </Button>
          </div>
        )}
      </div>
      <Dialog
        open={!!proposal}
        onOpenChange={(open) => {
          if (!open && !saving) setProposal(null);
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {proposal?.kind === "declare"
                ? "Confirmar declaración de cobro"
                : "Confirmar revisión manual"}
            </DialogTitle>
            <DialogDescription>
              {proposal?.kind === "declare"
                ? "Se guardará pendiente de revisión por otra persona."
                : "La decisión conservará el registro original y la comprobación realizada."}
            </DialogDescription>
          </DialogHeader>
          {proposal && (
            <div className="space-y-3 text-sm">
              <p className="rounded-xl bg-gradient-to-r from-emerald-50 to-cyan-50 p-4 text-xl font-bold text-emerald-950">
                {moneyText(
                  proposal.kind === "declare"
                    ? proposal.body.amount_usd
                    : proposal.entry.amount_usd,
                  "USD",
                )}
              </p>
              {proposal.kind === "declare" ? (
                <p className="break-all">
                  Recibido{" "}
                  {moneyText(
                    proposal.body.paid_amount,
                    proposal.body.paid_currency,
                  )}{" "}
                  · {methodName[proposal.body.method]} ·{" "}
                  {proposal.body.source_key} / {proposal.body.reference_key}
                </p>
              ) : (
                <>
                  <p>
                    {proposal.body.decision === "VERIFICADO"
                      ? "Verificar manualmente"
                      : "Rechazar"}{" "}
                    · {proposal.entry.reference_key}
                  </p>
                  <p className="break-words">{proposal.body.note}</p>
                  {proposal.body.acknowledge_refund_due && (
                    <p className="text-amber-900">
                      Se reconocerá un importe pendiente de devolución.
                    </p>
                  )}
                </>
              )}
              {error && (
                <p role="alert" className="text-red-800">
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
              onClick={() => setProposal(null)}
            >
              {pending ? "Cerrar" : "Cancelar"}
            </Button>
            <Button
              type="button"
              disabled={saving}
              className="bg-emerald-700 hover:bg-emerald-800"
              onClick={() => {
                const value = pending ?? proposal;
                if (value) void save(value);
              }}
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {pending ? "Reintentar misma solicitud" : "Confirmar y guardar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
