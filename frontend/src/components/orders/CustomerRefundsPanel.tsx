"use client";
import { useEffect, useRef, useState } from "react";
import { RotateCcw, RefreshCw, ShieldCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useAuthStore } from "@/stores/authStore";
import { moneyText, canonicalDecimal } from "@/lib/currency";
import { moneyInput } from "@/lib/order-pricing";
import {
  collectionCents,
  collectionKey,
  type CollectionMethod,
} from "@/lib/customer-collections";
import {
  refundAmount,
  refundNote,
  type RefundContext,
  type CustomerRefund,
  type RefundRequestInput,
  type RefundEventInput,
  type RefundAction,
  type RefundEvent,
} from "@/lib/customer-refunds";
import { customerRefundsService as service } from "@/services/customer-refunds.service";
const names: Record<RefundAction, string> = {
  APROBAR: "Aprobar solicitud",
  RECHAZAR: "Rechazar solicitud",
  DECLARAR_EJECUCION: "Registrar devolución realizada",
  VERIFICAR_DEVOLUCION: "Verificar devolución",
  OBSERVAR_EJECUCION: "Observar ejecución",
  CONFIRMAR_NO_EJECUTADA: "Confirmar que no se ejecutó",
  ANULAR_APROBACION: "Anular aprobación sin ejecución",
};
const states = {
  SOLICITADA: "Pendiente de autorización",
  APROBADA: "Aprobada · falta ejecución",
  RECHAZADA: "Solicitud rechazada",
  EJECUCION_DECLARADA: "Ejecución pendiente de verificación",
  OBSERVADA: "Ejecución observada · importe bloqueado",
  DEVUELTA: "Devolución verificada manualmente",
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
      : e.message || "No se pudo consultar la devolución.";
};
type Proposal =
  | {
      kind: "request";
      body: RefundRequestInput;
      expectedReturn: string;
      currency: "USD" | "VES";
    }
  | { kind: "event"; body: RefundEventInput; refund: CustomerRefund };
export function CustomerRefundsPanel({
  orderId,
  orderStatus,
}: {
  orderId: string;
  orderStatus: string;
}) {
  const user = useAuthStore((s) => s.user),
    generation = useAuthStore((s) => s.sessionRevision);
  const linked =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("refund");
  if (
    !user ||
    !["SUPERADMIN", "GERENTE", "OPERADOR", "AUDITOR"].includes(user.role) ||
    (!["CANCELADO", "FALLIDO"].includes(orderStatus) && !linked)
  )
    return null;
  return (
    <Panel
      key={JSON.stringify([orderId, user.id, user.role, generation])}
      orderId={orderId}
      canRequest={user.role !== "AUDITOR"}
      canReview={["SUPERADMIN", "GERENTE"].includes(user.role)}
    />
  );
}
function Panel({
  orderId,
  canRequest,
  canReview,
}: {
  orderId: string;
  canRequest: boolean;
  canReview: boolean;
}) {
  const [context, setContext] = useState<RefundContext | null>(null),
    [selected, setSelected] = useState<CustomerRefund | null>(null),
    [older, setOlder] = useState<RefundEvent[]>([]),
    [moreBefore, setMoreBefore] = useState<number | null>(null),
    [historyLoading, setHistoryLoading] = useState(false);
  const [loading, setLoading] = useState(true),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState(""),
    [amount, setAmount] = useState(""),
    [reason, setReason] = useState(""),
    [confirmedRequest, setConfirmedRequest] = useState(false);
  const [target, setTarget] = useState<{
      refund: CustomerRefund;
      kind: RefundAction;
    } | null>(null),
    [note, setNote] = useState(""),
    [evidence, setEvidence] = useState(false),
    [noExecution, setNoExecution] = useState(false),
    [executed, setExecuted] = useState(false),
    [method, setMethod] = useState<CollectionMethod>("EFECTIVO"),
    [source, setSource] = useState(""),
    [reference, setReference] = useState(""),
    [paid, setPaid] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null),
    [pending, setPending] = useState<Proposal | null>(null);
  const alive = useRef(true),
    sequence = useRef(0),
    receiptSequence = useRef(0),
    busy = useRef(false);
  const selectReceipt = (value: CustomerRefund) => {
    receiptSequence.current++;
    setSelected(value);
    setOlder([]);
    setMoreBefore(
      value.has_more_events
        ? value.events[value.events.length - 1].revision
        : null,
    );
    const url = new URL(window.location.href);
    url.searchParams.set("refund", value.id);
    window.history.replaceState(null, "", url);
  };
  const load = async () => {
    const seq = ++sequence.current;
    setLoading(true);
    try {
      const value = await service.context(orderId);
      if (alive.current && seq === sequence.current) {
        setContext(value);
        setCollectionId((previous) =>
          value.collections.some(
            (c) => c.collection.id === previous && c.can_request,
          )
            ? previous
            : (value.collections.find((c) => c.can_request)?.collection.id ??
              ""),
        );
      }
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
    const id = new URLSearchParams(window.location.search).get("refund");
    if (id) {
      const seq = receiptSequence.current;
      void service
        .receipt(orderId, id)
        .then((value) => {
          if (alive.current && seq === receiptSequence.current)
            selectReceipt(value);
        })
        .catch((p) => {
          if (alive.current && seq === receiptSequence.current)
            setError(problemText(p));
        });
    }
    return () => {
      alive.current = false;
      sequence.current++;
      receiptSequence.current++;
    }; // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);
  const disabled = loading || saving || !!pending,
    entry = context?.collections.find((c) => c.collection.id === collectionId);
  let expectedReturn: string | null = null;
  try {
    if (entry && amount)
      expectedReturn = refundAmount(
        moneyInput(amount),
        entry.returned_usd,
        entry.returned_paid,
        entry.rate,
      );
  } catch {
    /* incomplete input */
  }
  const prepareRequest = (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !context ||
      !entry ||
      !entry.can_request ||
      disabled ||
      !confirmedRequest
    )
      return;
    setError(null);
    try {
      const usd = moneyInput(amount);
      if (
        collectionCents(usd) <= BigInt(0) ||
        collectionCents(usd) > collectionCents(entry.remaining_usd) ||
        !expectedReturn ||
        collectionCents(expectedReturn) <= BigInt(0)
      )
        throw new Error(
          "Indica un abono válido dentro del saldo del cobro y con al menos un centavo en su moneda.",
        );
      setProposal({
        kind: "request",
        body: {
          request_key: crypto.randomUUID(),
          collection_id: collectionId,
          expected_book_revision: context.book_revision,
          amount_usd: usd,
          reason: refundNote(reason.trim()),
          confirmed_request: true,
        },
        expectedReturn,
        currency: entry.collection.paid_currency,
      });
    } catch (p) {
      setError(problemText(p));
    }
  };
  const prepareEvent = () => {
    if (!context || !target || disabled) return;
    setError(null);
    try {
      const kind = target.kind,
        execution = kind === "DECLARAR_EJECUCION",
        mustNo = ["CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION"].includes(kind),
        mustEvidence = [
          "VERIFICAR_DEVOLUCION",
          "CONFIRMAR_NO_EJECUTADA",
          "ANULAR_APROBACION",
        ].includes(kind);
      if (
        (mustEvidence && !evidence) ||
        (mustNo && !noExecution) ||
        (execution && !executed)
      )
        throw new Error(
          "Confirma la comprobación y las declaraciones requeridas antes de continuar.",
        );
      const body: RefundEventInput = {
        request_key: crypto.randomUUID(),
        expected_revision: target.refund.revision,
        kind,
        note: refundNote(note.trim()),
        verified_evidence: mustEvidence,
        confirmed_no_execution: mustNo,
        confirmed_execution: execution,
      };
      if (execution) {
        const normalized = canonicalDecimal(paid, 2, 21),
          [units, decimals = ""] = normalized.split("."),
          actual = units + "." + decimals.padEnd(2, "0");
        if (actual !== target.refund.return_amount)
          throw new Error(
            "El importe realmente devuelto debe coincidir con la solicitud aprobada.",
          );
        if (method === "PAGO_MOVIL" && target.refund.return_currency !== "VES")
          throw new Error("Pago móvil se registra en bolívares.");
        Object.assign(body, {
          method,
          source_key: collectionKey(source),
          reference_key: collectionKey(reference),
          paid_amount: actual,
          paid_currency: target.refund.return_currency,
          executed_on: context.today,
        });
      }
      setProposal({ kind: "event", body, refund: target.refund });
    } catch (p) {
      setError(problemText(p));
    }
  };
  const save = async (value: Proposal) => {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setPending(value);
    setError(null);
    try {
      const result =
        value.kind === "request"
          ? await service.request(orderId, value.body)
          : (await service.event(orderId, value.refund.id, value.body)).refund;
      if (!alive.current) return;
      if (
        value.kind === "request" &&
        (result.return_amount !== value.expectedReturn ||
          result.return_currency !== value.currency)
      )
        throw new Error(
          "El importe confirmado no corresponde al revisado. Recupera la misma solicitud.",
        );
      selectReceipt(result);
      setPending(null);
      setProposal(null);
      setTarget(null);
      setAmount("");
      setReason("");
      setConfirmedRequest(false);
      void load();
    } catch (p) {
      if (!alive.current) return;
      const code = (p as { response?: { status?: number } }).response?.status;
      if (
        code !== undefined &&
        code >= 400 &&
        code < 500 &&
        code !== 408 &&
        code !== 429
      ) {
        setPending(null);
        setProposal(null);
        setTarget(null);
        void load();
      }
      setError(problemText(p));
    } finally {
      busy.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const history = async () => {
    if (!selected || moreBefore === null || historyLoading) return;
    const id = selected.id,
      seq = receiptSequence.current;
    setHistoryLoading(true);
    try {
      const page = await service.events(selected, moreBefore);
      if (
        alive.current &&
        seq === receiptSequence.current &&
        selected.id === id
      ) {
        setOlder((previous) => [...previous, ...page.events]);
        setMoreBefore(page.next_before_revision);
      }
    } catch (p) {
      if (alive.current && seq === receiptSequence.current)
        setError(problemText(p));
    } finally {
      if (alive.current) setHistoryLoading(false);
    }
  };
  const openAction = (refund: CustomerRefund, kind: RefundAction) => {
    setTarget({ refund, kind });
    setNote("");
    setEvidence(false);
    setNoExecution(false);
    setExecuted(false);
    setSource("");
    setReference("");
    setPaid("");
    setMethod(refund.return_currency === "VES" ? "PAGO_MOVIL" : "EFECTIVO");
    setError(null);
  };
  const inputClass =
    "mt-1 h-10 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm disabled:bg-slate-100";
  const field = (
    title: string,
    value: string,
    set: (value: string) => void,
    max = 120,
  ) => (
    <label className="block text-sm font-medium text-slate-700">
      {title}
      <input
        value={value}
        onChange={(e) => set(e.target.value)}
        disabled={disabled}
        maxLength={max}
        className={inputClass}
      />
    </label>
  );
  const mustNo =
      !!target &&
      ["CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION"].includes(target.kind),
    mustEvidence =
      !!target &&
      [
        "VERIFICAR_DEVOLUCION",
        "CONFIRMAR_NO_EJECUTADA",
        "ANULAR_APROBACION",
      ].includes(target.kind);
  return (
    <section
      aria-label="Devoluciones de clientes"
      className="overflow-hidden rounded-xl border border-violet-200 bg-white shadow-sm"
    >
      <div className="flex items-start justify-between gap-3 bg-gradient-to-r from-violet-700 via-purple-600 to-rose-600 p-4 text-white">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <RotateCcw className="h-5 w-5" />
            Devoluciones de clientes
          </h2>
          <p className="mt-1 text-sm text-violet-50">
            Autorización y comprobación por responsables distintos
          </p>
        </div>
        <Button
          type="button"
          aria-label="Actualizar devoluciones"
          variant="ghost"
          size="icon"
          disabled={loading || saving}
          className="shrink-0 text-white hover:bg-white/20"
          onClick={() => {
            setError(null);
            void load();
          }}
        >
          <RefreshCw className={"h-4 w-4 " + (loading ? "animate-spin" : "")} />
        </Button>
      </div>
      <div className="space-y-4 p-4">
        <p className="text-sm text-slate-600">
          Una aprobación reserva el importe. Solo la devolución verificada
          reduce el saldo pendiente. Las salidas se realizan fuera de este
          sistema y se comprueban manualmente.
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
            Consultando devoluciones…
          </p>
        )}
        {context && !loading && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                [
                  "Pendiente de devolver",
                  context.summary.remaining_usd,
                  "bg-rose-50 text-rose-950",
                ],
                [
                  "En trámite",
                  context.summary.in_progress_usd,
                  "bg-amber-50 text-amber-950",
                ],
                [
                  "Devuelto y verificado",
                  context.summary.refunded_usd,
                  "bg-violet-50 text-violet-950",
                ],
              ].map(([label, value, color]) => (
                <div key={label} className={"rounded-lg p-3 " + color}>
                  <p className="text-xs font-medium">{label}</p>
                  <p className="mt-1 break-all text-xl font-bold">
                    {moneyText(value, "USD")}
                  </p>
                </div>
              ))}
            </div>
            <p className="flex items-start gap-2 text-sm text-violet-900">
              <ShieldCheck className="h-5 w-5 shrink-0" />
              Se conserva la moneda y la tasa del cobro original. Los centavos
              se ajustan de forma acumulada para devolver exactamente lo
              recibido.
            </p>
            {!["CANCELADO", "FALLIDO"].includes(context.order_status ?? "") && (
              <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
                Las solicitudes nuevas requieren que la orden esté cancelada o
                fallida.
              </p>
            )}
            {canRequest && context.collections.some((c) => c.can_request) && (
              <form
                onSubmit={prepareRequest}
                className="space-y-3 rounded-xl border border-violet-100 bg-gradient-to-br from-slate-50 to-violet-50 p-4"
              >
                <h3 className="font-semibold text-slate-900">
                  Solicitar devolución parcial o total
                </h3>
                <label className="block text-sm font-medium text-slate-700">
                  Cobro original
                  <select
                    aria-label="Cobro original"
                    className={inputClass}
                    value={collectionId}
                    disabled={disabled}
                    onChange={(e) => {
                      setCollectionId(e.target.value);
                      setAmount("");
                    }}
                  >
                    {context.collections
                      .filter((c) => c.can_request)
                      .map((c) => (
                        <option key={c.collection.id} value={c.collection.id}>
                          {c.collection.reference_key} · saldo{" "}
                          {moneyText(c.remaining_usd, "USD")} · recibido{" "}
                          {moneyText(
                            c.collection.paid_amount,
                            c.collection.paid_currency,
                          )}
                        </option>
                      ))}
                  </select>
                </label>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {field("Importe a devolver en USD", amount, setAmount, 11)}
                  <div className="rounded-lg border border-violet-200 bg-white p-3">
                    <p className="text-xs text-violet-700">
                      Salida a autorizar en moneda original
                    </p>
                    <p className="mt-1 break-all text-lg font-bold text-violet-950">
                      {entry && expectedReturn
                        ? moneyText(
                            expectedReturn,
                            entry.collection.paid_currency,
                          )
                        : "Por confirmar"}
                    </p>
                    {entry?.collection.quote && (
                      <p className="mt-1 text-xs text-slate-500">
                        BCV del cobro: {entry.rate} Bs./USD ·{" "}
                        {entry.collection.received_on}
                      </p>
                    )}
                  </div>
                </div>
                <label className="block text-sm font-medium text-slate-700">
                  Motivo de devolución
                  <textarea
                    className={inputClass + " h-20 py-2"}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    disabled={disabled}
                    maxLength={500}
                  />
                </label>
                <label className="flex items-start gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={confirmedRequest}
                    onChange={(e) => setConfirmedRequest(e.target.checked)}
                    disabled={disabled}
                    className="mt-1"
                  />
                  Confirmo que solicito este importe para revisión por otro
                  responsable. Esta solicitud no devuelve dinero.
                </label>
                <Button
                  type="submit"
                  disabled={disabled || !confirmedRequest}
                  className="w-full bg-violet-700 hover:bg-violet-800"
                >
                  Revisar solicitud de devolución
                </Button>
              </form>
            )}
            {context.collections.some((c) => c.active_request) && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                Hay un trámite en curso. Resuélvelo antes de solicitar otra
                devolución del mismo cobro, aunque todavía quede saldo.
              </p>
            )}
            {context.refunds.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-slate-800">
                  Solicitudes conservadas · últimas {context.refunds.length}
                </h3>
                {context.refunds.map((row) => (
                  <article
                    key={row.id}
                    className="rounded-lg border border-slate-200 p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <strong>
                        {moneyText(row.amount_usd, "USD")} →{" "}
                        {moneyText(row.return_amount, row.return_currency)}
                      </strong>
                      <span
                        className={
                          "rounded-full px-2 py-1 text-xs font-medium " +
                          (row.state === "DEVUELTA"
                            ? "bg-emerald-100 text-emerald-900"
                            : row.state === "OBSERVADA"
                              ? "bg-rose-100 text-rose-900"
                              : "bg-violet-100 text-violet-900")
                        }
                      >
                        {states[row.state]}
                      </span>
                    </div>
                    <p className="mt-2 break-words text-slate-600">
                      {row.reason}
                    </p>
                    <p className="mt-1 break-all text-xs text-slate-500">
                      Cobro {row.original_collection.reference_key} · solicitud{" "}
                      {row.id}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => selectReceipt(row)}
                      >
                        Ver historial de devolución
                      </Button>
                      {canReview &&
                        row.allowed_actions.map((kind) => (
                          <Button
                            key={kind}
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={disabled}
                            onClick={() => openAction(row, kind)}
                          >
                            {names[kind]}
                          </Button>
                        ))}
                    </div>
                  </article>
                ))}
                {context.has_more && (
                  <p className="text-xs text-slate-500">
                    Hay solicitudes anteriores. Sus enlaces conservados permiten
                    recuperarlas; el resumen incluye toda la orden.
                  </p>
                )}
              </div>
            )}
            {target && !pending && (
              <div
                aria-label="Acción de devolución"
                className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4"
              >
                <h3 className="font-semibold text-indigo-950">
                  {names[target.kind]}
                </h3>
                <p className="text-sm">
                  {moneyText(target.refund.amount_usd, "USD")} · salida
                  autorizada{" "}
                  {moneyText(
                    target.refund.return_amount,
                    target.refund.return_currency,
                  )}
                </p>
                {target.kind === "DECLARAR_EJECUCION" && (
                  <>
                    <p className="rounded-lg bg-white p-3 text-sm text-indigo-950">
                      Registra una devolución que ya realizaste fuera del
                      sistema. El guardado quedará pendiente de verificación por
                      otra persona.
                    </p>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium text-slate-700">
                        Medio de devolución
                        <select
                          aria-label="Medio de devolución"
                          className={inputClass}
                          value={method}
                          onChange={(e) =>
                            setMethod(e.target.value as CollectionMethod)
                          }
                          disabled={disabled}
                        >
                          <option value="EFECTIVO">Efectivo</option>
                          <option value="TRANSFERENCIA">Transferencia</option>
                          {target.refund.return_currency === "VES" && (
                            <option value="PAGO_MOVIL">Pago móvil</option>
                          )}
                        </select>
                      </label>
                      {field("Importe realmente devuelto", paid, setPaid, 24)}
                      {field(
                        "Alias de caja o cuenta de salida",
                        source,
                        setSource,
                        80,
                      )}
                      {field(
                        "Referencia única de devolución",
                        reference,
                        setReference,
                      )}
                    </div>
                    <p className="text-xs text-slate-600">
                      Moneda {target.refund.return_currency} · salida del{" "}
                      {context.today} en Caracas. Usa un alias interno y un
                      recibo o referencia completa, sin datos bancarios
                      personales.
                    </p>
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={executed}
                        onChange={(e) => setExecuted(e.target.checked)}
                        className="mt-1"
                      />
                      Confirmo que ya realicé la devolución por el importe
                      indicado.
                    </label>
                  </>
                )}
                {target.kind === "OBSERVAR_EJECUCION" && (
                  <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-950">
                    La observación conservará el importe bloqueado. No habilita
                    un segundo pago ni libera el saldo.
                  </p>
                )}
                <label className="block text-sm font-medium text-slate-700">
                  Motivo o comprobación de devolución
                  <textarea
                    className={inputClass + " h-20 py-2"}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={500}
                  />
                </label>
                {mustEvidence && (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={evidence}
                      onChange={(e) => setEvidence(e.target.checked)}
                      className="mt-1"
                    />
                    He comprobado el efectivo, los movimientos y la evidencia
                    correspondientes a esta decisión.
                  </label>
                )}
                {mustNo && (
                  <label className="flex items-start gap-2 text-sm text-amber-950">
                    <input
                      type="checkbox"
                      checked={noExecution}
                      onChange={(e) => setNoExecution(e.target.checked)}
                      className="mt-1"
                    />
                    Confirmo expresamente que no hubo salida de dinero. Esta
                    decisión permite{" "}
                    {target.kind === "CONFIRMAR_NO_EJECUTADA"
                      ? "registrar otro intento"
                      : "liberar la reserva"}
                    .
                  </label>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={disabled}
                    onClick={prepareEvent}
                  >
                    Revisar acción de devolución
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={disabled}
                    onClick={() => setTarget(null)}
                  >
                    Cancelar acción
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
              Falta confirmar el resultado. Reintenta la misma solicitud para
              recuperar el registro sin duplicar una devolución.
            </p>
            <Button
              type="button"
              disabled={saving}
              onClick={() => void save(pending)}
            >
              Reintentar devolución pendiente
            </Button>
          </div>
        )}
        {selected && (
          <div
            aria-label="Devolución conservada"
            className="space-y-3 rounded-xl border border-violet-200 bg-violet-50 p-4"
          >
            <h3 className="font-semibold text-violet-950">
              {states[selected.state]}
            </h3>
            <p className="break-all font-bold text-violet-950">
              {moneyText(selected.amount_usd, "USD")} →{" "}
              {moneyText(selected.return_amount, selected.return_currency)}
            </p>
            <p className="break-all text-xs text-slate-600">
              Solicitud {selected.id} · cobro{" "}
              {selected.original_collection.reference_key}
            </p>
            <p className="text-sm text-slate-700">{selected.reason}</p>
            <ol className="space-y-2">
              {[...selected.events, ...older].map((e) => (
                <li
                  key={e.id}
                  className="rounded-lg border border-violet-100 bg-white p-3 text-sm"
                >
                  <p className="font-semibold text-violet-950">
                    {e.revision}. {names[e.kind]}
                  </p>
                  <p className="mt-1 break-words text-slate-600">{e.note}</p>
                  {e.kind === "DECLARAR_EJECUCION" && (
                    <p className="mt-1 break-all text-xs text-slate-600">
                      Salida declarada{" "}
                      {moneyText(e.paid_amount!, e.paid_currency!)} ·{" "}
                      {e.source_key} / {e.reference_key}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">{e.created_at}</p>
                </li>
              ))}
            </ol>
            {moreBefore !== null && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={historyLoading}
                onClick={() => void history()}
              >
                Cargar eventos anteriores
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                const url = new URL(window.location.href);
                url.searchParams.set("refund", selected.id);
                void navigator.clipboard
                  ?.writeText(url.toString())
                  .catch(() =>
                    setError(
                      "Conserva la dirección del navegador para recuperar la devolución.",
                    ),
                  );
              }}
            >
              Copiar enlace de devolución
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
              {proposal?.kind === "request"
                ? "Confirmar solicitud de devolución"
                : "Confirmar acción de devolución"}
            </DialogTitle>
            <DialogDescription>
              Revisa el importe y la decisión. Una aprobación o declaración no
              confirma por sí sola que el dinero haya sido devuelto.
            </DialogDescription>
          </DialogHeader>
          {proposal && (
            <div className="space-y-3">
              <div className="rounded-xl bg-gradient-to-r from-violet-50 to-rose-50 p-4">
                <p className="text-xl font-bold text-violet-950">
                  {moneyText(
                    proposal.kind === "request"
                      ? proposal.body.amount_usd
                      : proposal.refund.amount_usd,
                    "USD",
                  )}
                </p>
                <p className="mt-1 text-lg font-semibold text-rose-900">
                  {moneyText(
                    proposal.kind === "request"
                      ? proposal.expectedReturn
                      : proposal.refund.return_amount,
                    proposal.kind === "request"
                      ? proposal.currency
                      : proposal.refund.return_currency,
                  )}
                </p>
              </div>
              <p className="break-words text-sm text-slate-700">
                {proposal.kind === "request"
                  ? proposal.body.reason
                  : names[proposal.body.kind] + " · " + proposal.body.note}
              </p>
              {proposal.kind === "event" &&
                proposal.body.kind === "DECLARAR_EJECUCION" && (
                  <p className="break-all text-sm">
                    {proposal.body.source_key} / {proposal.body.reference_key}
                  </p>
                )}
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
              onClick={() => setProposal(null)}
            >
              {pending ? "Cerrar" : "Cancelar"}
            </Button>
            <Button
              type="button"
              disabled={saving}
              className="bg-violet-700 hover:bg-violet-800"
              onClick={() => {
                const value = pending ?? proposal;
                if (value) void save(value);
              }}
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {pending
                ? "Reintentar misma devolución"
                : "Confirmar y guardar devolución"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
