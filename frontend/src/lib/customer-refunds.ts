import { exactVes } from "@/lib/currency";
import {
  collectionMoney,
  collectionCents,
  collectionKey,
  validateCollection,
  type CustomerCollection,
  type CollectionMethod,
} from "@/lib/customer-collections";
import { orderQuoteId } from "@/lib/order-currency-quote";
import { ORDER_STATUSES } from "@/lib/operational-catalog";
export type RefundState =
  | "SOLICITADA"
  | "APROBADA"
  | "RECHAZADA"
  | "EJECUCION_DECLARADA"
  | "OBSERVADA"
  | "DEVUELTA";
export type RefundAction =
  | "APROBAR"
  | "RECHAZAR"
  | "DECLARAR_EJECUCION"
  | "VERIFICAR_DEVOLUCION"
  | "OBSERVAR_EJECUCION"
  | "CONFIRMAR_NO_EJECUTADA"
  | "ANULAR_APROBACION";
export const refundStates: Record<RefundAction, RefundState> = {
  APROBAR: "APROBADA",
  RECHAZAR: "RECHAZADA",
  DECLARAR_EJECUCION: "EJECUCION_DECLARADA",
  VERIFICAR_DEVOLUCION: "DEVUELTA",
  OBSERVAR_EJECUCION: "OBSERVADA",
  CONFIRMAR_NO_EJECUTADA: "APROBADA",
  ANULAR_APROBACION: "RECHAZADA",
};
export const refundActions: Record<RefundState, readonly RefundAction[]> = {
  SOLICITADA: ["APROBAR", "RECHAZAR"],
  APROBADA: ["DECLARAR_EJECUCION", "ANULAR_APROBACION"],
  EJECUCION_DECLARADA: ["VERIFICAR_DEVOLUCION", "OBSERVAR_EJECUCION"],
  OBSERVADA: ["VERIFICAR_DEVOLUCION", "CONFIRMAR_NO_EJECUTADA"],
  DEVUELTA: [],
  RECHAZADA: [],
};
export interface RefundRequestInput {
  request_key: string;
  collection_id: string;
  expected_book_revision: number;
  amount_usd: string;
  reason: string;
  confirmed_request: true;
}
export interface RefundEventInput {
  request_key: string;
  expected_revision: number;
  kind: RefundAction;
  note: string;
  verified_evidence: boolean;
  confirmed_no_execution: boolean;
  confirmed_execution: boolean;
  method?: CollectionMethod | null;
  source_key?: string | null;
  reference_key?: string | null;
  paid_amount?: string | null;
  paid_currency?: "USD" | "VES" | null;
  executed_on?: string | null;
}
export interface RefundEvent
  extends Omit<Required<RefundEventInput>, "expected_revision"> {
  id: string;
  refund_id: string;
  revision: number;
  actor_id: string;
  created_at: string;
}
export interface CustomerRefund {
  id: string;
  request_key: string;
  order_id: string;
  collection_id: string;
  amount_usd: string;
  return_amount: string;
  return_currency: "USD" | "VES";
  prior_refunded_usd: string;
  prior_refunded_paid: string;
  reason: string;
  requested_by: string;
  created_at: string;
  revision: number;
  state: RefundState;
  original_collection: CustomerCollection;
  events: RefundEvent[];
  has_more_events: boolean;
  allowed_actions: RefundAction[];
  policy: "ORIGINAL_RECEIVED";
  rounding: "CUMULATIVE_ORIGINAL_BCV";
  scope: "manual_customer_refunds";
  bank_verified: false;
}
export interface RefundCollection {
  collection: CustomerCollection;
  returned_usd: string;
  returned_paid: string;
  remaining_usd: string;
  active_request: boolean;
  can_request: boolean;
  rate: string;
}
export interface RefundContext {
  order_id: string;
  order_status: string | null;
  today: string;
  book_revision: number;
  summary: {
    currency: "USD";
    gross_verified_usd: string;
    refunded_usd: string;
    in_progress_usd: string;
    remaining_usd: string;
    requestable_now_usd: string;
  };
  collections: RefundCollection[];
  refunds: CustomerRefund[];
  has_more: boolean;
  policy: "ORIGINAL_RECEIVED";
  scope: "manual_customer_refunds";
  bank_integration_available: false;
}
export interface RefundEventPage {
  refund_id: string;
  events: RefundEvent[];
  has_more: boolean;
  next_before_revision: number | null;
}
const invalid = (): never => {
  throw new Error(
    "La devolución contiene datos incoherentes. Actualiza antes de continuar.",
  );
};
const obj = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) return invalid();
  return v as Record<string, unknown>;
};
const rev = (v: unknown): number => {
  if (
    typeof v !== "number" ||
    !Number.isSafeInteger(v) ||
    v < 0 ||
    v > 2147483647
  )
    return invalid();
  return v;
};
const day = (v: unknown): string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(v) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v
  )
    return invalid();
  return v;
};
const time = (v: unknown): string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?Z$/.test(
      v,
    ) ||
    !Number.isFinite(Date.parse(v)) ||
    new Date(v).toISOString().slice(0, 10) !== v.slice(0, 10)
  )
    return invalid();
  return v;
};
const caracas = (v: string) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Caracas",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(v));
  return ["year", "month", "day"]
    .map((k) => parts.find((p) => p.type === k)!.value)
    .join("-");
};
export function refundNote(v: unknown): string {
  if (
    typeof v !== "string" ||
    v.trim() !== v ||
    v.length < 10 ||
    v.length > 500 ||
    /[\x00-\x1f\x7f]/.test(v)
  )
    return invalid();
  return v;
}
export function centsText(v: bigint): string {
  if (v < BigInt(0)) return invalid();
  return (
    (v / BigInt(100)).toString() +
    "." +
    (v % BigInt(100)).toString().padStart(2, "0")
  );
}
export function refundAmount(
  usd: string,
  returnedUsd: string,
  returnedPaid: string,
  rate: string,
): string {
  const cumulative = centsText(
    collectionCents(usd) + collectionCents(returnedUsd),
  );
  return centsText(
    collectionCents(exactVes(cumulative, rate)) - collectionCents(returnedPaid),
  );
}
const originalRate = (collection: CustomerCollection) =>
  collection.quote?.rate.ves_per_usd ?? "1.00000000";
export function validateRefundEvent(
  value: unknown,
  refund: Pick<
    CustomerRefund,
    "id" | "requested_by" | "return_amount" | "return_currency" | "created_at"
  >,
): RefundEvent {
  const r = obj(value);
  for (const k of ["id", "request_key", "refund_id", "actor_id"])
    orderQuoteId(r[k]);
  const revision = rev(r.revision),
    created = time(r.created_at);
  refundNote(r.note);
  if (
    r.refund_id !== refund.id ||
    revision < 1 ||
    Date.parse(created) < Date.parse(refund.created_at) ||
    typeof r.kind !== "string" ||
    !Object.hasOwn(refundStates, r.kind)
  )
    return invalid();
  const kind = r.kind as RefundAction,
    execute = kind === "DECLARAR_EJECUCION",
    noExecution = ["CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION"].includes(
      kind,
    ),
    evidence = [
      "VERIFICAR_DEVOLUCION",
      "CONFIRMAR_NO_EJECUTADA",
      "ANULAR_APROBACION",
    ].includes(kind);
  if (
    r.confirmed_execution !== execute ||
    r.confirmed_no_execution !== noExecution ||
    r.verified_evidence !== evidence ||
    (["APROBAR", "RECHAZAR", "ANULAR_APROBACION"].includes(kind) &&
      r.actor_id === refund.requested_by)
  )
    return invalid();
  if (execute) {
    if (
      !["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"].includes(
        r.method as string,
      ) ||
      r.paid_amount !== refund.return_amount ||
      r.paid_currency !== refund.return_currency ||
      (r.method === "PAGO_MOVIL" && r.paid_currency !== "VES") ||
      day(r.executed_on) !== caracas(created)
    )
      return invalid();
    for (const [k, max] of [
      ["source_key", 80],
      ["reference_key", 120],
    ] as const)
      if (
        typeof r[k] !== "string" ||
        (r[k] as string).length > max ||
        collectionKey(r[k] as string) !== r[k]
      )
        return invalid();
  } else if (
    [
      "method",
      "source_key",
      "reference_key",
      "paid_amount",
      "paid_currency",
      "executed_on",
    ].some((k) => r[k] !== null)
  )
    return invalid();
  return r as unknown as RefundEvent;
}
export function validateRefund(
  value: unknown,
  orderId: string,
): CustomerRefund {
  const r = obj(value);
  for (const k of [
    "id",
    "request_key",
    "order_id",
    "collection_id",
    "requested_by",
  ])
    orderQuoteId(r[k]);
  const original = validateCollection(r.original_collection, orderId),
    created = time(r.created_at),
    revision = rev(r.revision),
    usd = collectionMoney(r.amount_usd),
    paid = collectionMoney(r.return_amount, 21),
    priorUsd = collectionMoney(r.prior_refunded_usd),
    priorPaid = collectionMoney(r.prior_refunded_paid, 21);
  refundNote(r.reason);
  if (
    r.order_id !== orderId ||
    original.id !== r.collection_id ||
    original.status !== "VERIFICADO_MANUALMENTE" ||
    r.return_currency !== original.paid_currency ||
    r.policy !== "ORIGINAL_RECEIVED" ||
    r.rounding !== "CUMULATIVE_ORIGINAL_BCV" ||
    r.scope !== "manual_customer_refunds" ||
    r.bank_verified !== false ||
    collectionCents(usd) <= BigInt(0) ||
    collectionCents(paid) <= BigInt(0) ||
    collectionCents(priorUsd) + collectionCents(usd) >
      collectionCents(original.amount_usd) ||
    priorPaid !== exactVes(priorUsd, originalRate(original)) ||
    paid !== refundAmount(usd, priorUsd, priorPaid, originalRate(original)) ||
    Date.parse(created) < Date.parse(original.review!.reviewed_at) ||
    !Array.isArray(r.events) ||
    r.events.length > 50 ||
    typeof r.has_more_events !== "boolean" ||
    !Array.isArray(r.allowed_actions)
  )
    return invalid();
  const refund = {
      ...r,
      original_collection: original,
    } as unknown as CustomerRefund,
    events = r.events.map((e) => validateRefundEvent(e, refund));
  if (
    (r.has_more_events
      ? events.length !== 50 || revision <= 50
      : events.length !== revision) ||
    r.state !== (events.length ? refundStates[events[0].kind] : "SOLICITADA")
  )
    return invalid();
  if (
    !r.has_more_events &&
    events.length &&
    !refundActions.SOLICITADA.includes(events[events.length - 1].kind)
  )
    return invalid();
  const ids = new Set<string>();
  for (let i = 0; i < events.length; i++) {
    const e = events[i];
    if (
      ids.has(e.id) ||
      e.revision !== revision - i ||
      (i > 0 && Date.parse(events[i - 1].created_at) < Date.parse(e.created_at))
    )
      return invalid();
    ids.add(e.id);
    if (
      i < events.length - 1 &&
      !refundActions[refundStates[events[i + 1].kind]].includes(e.kind)
    )
      return invalid();
    if (
      [
        "VERIFICAR_DEVOLUCION",
        "OBSERVAR_EJECUCION",
        "CONFIRMAR_NO_EJECUTADA",
      ].includes(e.kind)
    ) {
      const execution = events
        .slice(i + 1)
        .find((x) => x.kind === "DECLARAR_EJECUCION");
      if (execution && execution.actor_id === e.actor_id) return invalid();
    }
  }
  if (
    new Set(r.allowed_actions).size !== r.allowed_actions.length ||
    r.allowed_actions.some(
      (a) => !refundActions[refund.state].includes(a as RefundAction),
    )
  )
    return invalid();
  return { ...refund, events };
}
export function validateRefundContext(
  value: unknown,
  orderId: string,
): RefundContext {
  const r = obj(value),
    s = obj(r.summary);
  orderQuoteId(r.order_id);
  const today = day(r.today),
    revision = rev(r.book_revision);
  if (
    r.order_id !== orderId ||
    r.policy !== "ORIGINAL_RECEIVED" ||
    r.scope !== "manual_customer_refunds" ||
    r.bank_integration_available !== false ||
    typeof r.has_more !== "boolean" ||
    !Array.isArray(r.refunds) ||
    r.refunds.length > 20 ||
    !Array.isArray(r.collections) ||
    s.currency !== "USD" ||
    (r.order_status !== null &&
      !ORDER_STATUSES.includes(r.order_status as never))
  )
    return invalid();
  for (const k of [
    "gross_verified_usd",
    "refunded_usd",
    "in_progress_usd",
    "remaining_usd",
    "requestable_now_usd",
  ])
    collectionMoney(s[k]);
  const gross = collectionCents(s.gross_verified_usd as string),
    returned = collectionCents(s.refunded_usd as string),
    pending = collectionCents(s.in_progress_usd as string),
    remaining = collectionCents(s.remaining_usd as string),
    available = collectionCents(s.requestable_now_usd as string),
    terminal = ["CANCELADO", "FALLIDO"].includes(r.order_status as string);
  if (
    returned + pending > gross ||
    remaining !== (terminal ? gross - returned : BigInt(0)) ||
    available + pending > remaining
  )
    return invalid();
  const collections = r.collections.map((value) => {
    const c = obj(value),
      original = validateCollection(c.collection, orderId),
      usd = collectionMoney(c.returned_usd),
      paid = collectionMoney(c.returned_paid, 21),
      left = collectionMoney(c.remaining_usd);
    if (
      original.status !== "VERIFICADO_MANUALMENTE" ||
      c.rate !== originalRate(original) ||
      typeof c.active_request !== "boolean" ||
      typeof c.can_request !== "boolean" ||
      collectionCents(usd) + collectionCents(left) !==
        collectionCents(original.amount_usd) ||
      paid !== exactVes(usd, c.rate as string) ||
      (c.can_request && (!terminal || c.active_request || left === "0.00"))
    )
      return invalid();
    return { ...c, collection: original } as unknown as RefundCollection;
  });
  const refunds = r.refunds.map((v) => validateRefund(v, orderId)),
    ids = new Set<string>();
  if (r.has_more && refunds.length !== 20) return invalid();
  let seenRevision = 0;
  for (const row of refunds) {
    if (ids.has(row.id) || caracas(row.created_at) > today) return invalid();
    ids.add(row.id);
    seenRevision += 1 + row.revision;
  }
  if (
    seenRevision > revision ||
    new Set(collections.map((c) => c.collection.id)).size !==
      collections.length ||
    collections.reduce(
      (sum, c) => sum + collectionCents(c.collection.amount_usd),
      BigInt(0),
    ) > gross
  )
    return invalid();
  return { ...r, summary: s, collections, refunds } as unknown as RefundContext;
}
