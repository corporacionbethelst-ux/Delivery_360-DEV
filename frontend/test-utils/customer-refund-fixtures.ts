import { reviewed, reviewerId } from "./customer-collection-fixtures";
import { orderId } from "./order-currency-fixtures";
import { actorId, nextId } from "./currency-fixtures";
import {
  refundStates,
  type CustomerRefund,
  type RefundContext,
  type RefundEvent,
  type RefundAction,
  type RefundRequestInput,
  type RefundEventInput,
} from "@/lib/customer-refunds";
export const refundId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const refundRequest: RefundRequestInput = {
  request_key: nextId,
  collection_id: reviewed.id,
  expected_book_revision: 0,
  amount_usd: "0.10",
  reason: "Cliente solicita devolución por cancelación",
  confirmed_request: true,
};
export const refund: CustomerRefund = {
  id: refundId,
  request_key: nextId,
  order_id: orderId,
  collection_id: reviewed.id,
  amount_usd: "0.10",
  return_amount: "0.10",
  return_currency: "USD",
  prior_refunded_usd: "0.00",
  prior_refunded_paid: "0.00",
  reason: refundRequest.reason,
  requested_by: actorId,
  created_at: "2026-11-14T16:04:00Z",
  revision: 0,
  state: "SOLICITADA",
  original_collection: reviewed,
  events: [],
  has_more_events: false,
  allowed_actions: [],
  policy: "ORIGINAL_RECEIVED",
  rounding: "CUMULATIVE_ORIGINAL_BCV",
  scope: "manual_customer_refunds",
  bank_verified: false,
};
export function refundEvent(
  kind: RefundAction,
  revision: number,
  actor: string,
): RefundEvent {
  const executing = kind === "DECLARAR_EJECUCION";
  return {
    id: `bbbbbbbb-bbbb-4bbb-8bbb-${String(revision).padStart(12, "0")}`,
    request_key: nextId,
    refund_id: refundId,
    revision,
    kind,
    note: "Comprobación manual del recibo de devolución",
    verified_evidence: [
      "VERIFICAR_DEVOLUCION",
      "CONFIRMAR_NO_EJECUTADA",
      "ANULAR_APROBACION",
    ].includes(kind),
    confirmed_no_execution: [
      "CONFIRMAR_NO_EJECUTADA",
      "ANULAR_APROBACION",
    ].includes(kind),
    confirmed_execution: executing,
    method: executing ? "EFECTIVO" : null,
    source_key: executing ? "CAJA" : null,
    reference_key: executing ? "SALIDA-95" : null,
    paid_amount: executing ? "0.10" : null,
    paid_currency: executing ? "USD" : null,
    executed_on: executing ? "2026-11-14" : null,
    actor_id: actor,
    created_at: `2026-11-14T16:${String(4 + revision).padStart(2, "0")}:00Z`,
  };
}
export const approval = refundEvent("APROBAR", 1, reviewerId),
  execution = refundEvent("DECLARAR_EJECUCION", 2, actorId),
  verification = refundEvent("VERIFICAR_DEVOLUCION", 3, reviewerId);
export const approved: CustomerRefund = {
  ...refund,
  revision: 1,
  state: "APROBADA",
  events: [approval],
  allowed_actions: ["DECLARAR_EJECUCION"],
};
export const declared: CustomerRefund = {
  ...refund,
  revision: 2,
  state: "EJECUCION_DECLARADA",
  events: [execution, approval],
  allowed_actions: ["VERIFICAR_DEVOLUCION", "OBSERVAR_EJECUCION"],
};
export const returned: CustomerRefund = {
  ...refund,
  revision: 3,
  state: "DEVUELTA",
  events: [verification, execution, approval],
  allowed_actions: [],
};
export const refundContext: RefundContext = {
  order_id: orderId,
  order_status: "CANCELADO",
  today: "2026-11-14",
  book_revision: 0,
  summary: {
    currency: "USD",
    gross_verified_usd: "0.20",
    refunded_usd: "0.00",
    in_progress_usd: "0.00",
    remaining_usd: "0.20",
    requestable_now_usd: "0.20",
  },
  collections: [
    {
      collection: reviewed,
      returned_usd: "0.00",
      returned_paid: "0.00",
      remaining_usd: "0.20",
      active_request: false,
      can_request: true,
      rate: "1.00000000",
    },
  ],
  refunds: [],
  has_more: false,
  policy: "ORIGINAL_RECEIVED",
  scope: "manual_customer_refunds",
  bank_integration_available: false,
};
export function withRefund(row: CustomerRefund): RefundContext {
  const done = row.state === "DEVUELTA",
    rejected = row.state === "RECHAZADA",
    active = !done && !rejected;
  return {
    ...refundContext,
    book_revision: row.revision + 1,
    summary: {
      ...refundContext.summary,
      refunded_usd: done ? "0.10" : "0.00",
      remaining_usd: done ? "0.10" : "0.20",
      in_progress_usd: active ? "0.10" : "0.00",
      requestable_now_usd: active ? "0.00" : done ? "0.10" : "0.20",
    },
    collections: [
      {
        ...refundContext.collections[0],
        returned_usd: done ? "0.10" : "0.00",
        returned_paid: done ? "0.10" : "0.00",
        remaining_usd: done ? "0.10" : "0.20",
        active_request: active,
        can_request: !active,
      },
    ],
    refunds: [row],
  };
}
export function eventCommand(
  kind: RefundAction,
  revision: number,
): RefundEventInput {
  const e = refundEvent(kind, revision + 1, reviewerId);
  return {
    request_key: nextId,
    expected_revision: revision,
    kind,
    note: e.note,
    verified_evidence: e.verified_evidence,
    confirmed_no_execution: e.confirmed_no_execution,
    confirmed_execution: e.confirmed_execution,
    ...(kind === "DECLARAR_EJECUCION"
      ? {
          method: e.method,
          source_key: e.source_key,
          reference_key: e.reference_key,
          paid_amount: e.paid_amount,
          paid_currency: e.paid_currency,
          executed_on: e.executed_on,
        }
      : {}),
  };
}
