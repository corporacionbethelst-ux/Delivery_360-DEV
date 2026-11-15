import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import { orderQuoteId } from "@/lib/order-currency-quote";
import {
  validateRefund,
  validateRefundContext,
  validateRefundEvent,
  type RefundRequestInput,
  type RefundEventInput,
  type CustomerRefund,
  type RefundEventPage,
} from "@/lib/customer-refunds";
const executionFields = [
  "method",
  "source_key",
  "reference_key",
  "paid_amount",
  "paid_currency",
  "executed_on",
] as const;
export const customerRefundsService = {
  context: async (orderId: string) => {
    orderQuoteId(orderId);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(`/customer-refunds/orders/${orderId}`);
    task.assertCurrent();
    return validateRefundContext(value, orderId);
  },
  receipt: async (orderId: string, id: string) => {
    orderQuoteId(orderId);
    orderQuoteId(id);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(`/customer-refunds/${id}`);
    task.assertCurrent();
    const result = validateRefund(value, orderId);
    if (result.id !== id)
      throw new Error("La devolución recibida pertenece a otra solicitud.");
    return result;
  },
  request: async (orderId: string, body: Readonly<RefundRequestInput>) => {
    orderQuoteId(orderId);
    orderQuoteId(body.request_key);
    orderQuoteId(body.collection_id);
    const input = { ...body },
      task = capturePrivateTask();
    const value = await api.post<unknown>(
      `/customer-refunds/orders/${orderId}`,
      input,
    );
    task.assertCurrent();
    const result = validateRefund(value, orderId);
    if (
      result.request_key !== input.request_key ||
      result.collection_id !== input.collection_id ||
      result.amount_usd !== input.amount_usd ||
      result.reason !== input.reason
    )
      throw new Error(
        "La devolución no corresponde a la solicitud revisada. Reintenta la misma clave.",
      );
    return result;
  },
  event: async (
    orderId: string,
    id: string,
    body: Readonly<RefundEventInput>,
  ) => {
    orderQuoteId(orderId);
    orderQuoteId(id);
    orderQuoteId(body.request_key);
    const input = { ...body },
      task = capturePrivateTask();
    const raw = await api.post<unknown>(
      `/customer-refunds/${id}/events`,
      input,
    );
    task.assertCurrent();
    if (!raw || typeof raw !== "object" || Array.isArray(raw))
      throw new Error("La acción no contiene un registro de devolución.");
    const value = raw as { refund: unknown; applied_event: unknown },
      refund = validateRefund(value.refund, orderId),
      event = validateRefundEvent(value.applied_event, refund);
    if (
      refund.id !== id ||
      event.request_key !== input.request_key ||
      event.revision !== input.expected_revision + 1 ||
      event.kind !== input.kind ||
      event.note !== input.note ||
      event.verified_evidence !== input.verified_evidence ||
      event.confirmed_no_execution !== input.confirmed_no_execution ||
      event.confirmed_execution !== input.confirmed_execution ||
      executionFields.some((k) => event[k] !== (input[k] ?? null))
    )
      throw new Error(
        "La acción recibida no corresponde a la revisión. Reintenta la misma clave.",
      );
    return { refund, applied_event: event };
  },
  events: async (refund: CustomerRefund, before: number) => {
    orderQuoteId(refund.id);
    if (!Number.isSafeInteger(before) || before < 1 || before > refund.revision)
      throw new Error("Revisión de historial inválida.");
    const task = capturePrivateTask();
    const raw = await api.get<unknown>(
      `/customer-refunds/${refund.id}/events?before_revision=${before}`,
    );
    task.assertCurrent();
    if (!raw || typeof raw !== "object" || Array.isArray(raw))
      throw new Error("Historial inválido.");
    const value = raw as RefundEventPage;
    if (
      value.refund_id !== refund.id ||
      !Array.isArray(value.events) ||
      value.events.length > 50 ||
      typeof value.has_more !== "boolean"
    )
      throw new Error("Historial inválido.");
    const events = value.events.map((e) => validateRefundEvent(e, refund));
    if (
      events.some((e, i) => e.revision !== before - 1 - i) ||
      (value.has_more
        ? events.length !== 50 ||
          value.next_before_revision !== events[49].revision
        : value.next_before_revision !== null ||
          (events.length > 0 && events[events.length - 1].revision !== 1))
    )
      throw new Error("El historial no es continuo.");
    return { ...value, events };
  },
};
