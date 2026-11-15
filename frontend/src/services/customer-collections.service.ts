import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import { orderQuoteId } from "@/lib/order-currency-quote";
import {
  validateCollection,
  validateCollectionContext,
  type CollectionInput,
  type CollectionReviewInput,
} from "@/lib/customer-collections";

export const customerCollectionsService = {
  receipt: async (orderId: string, id: string) => {
    orderQuoteId(orderId);
    orderQuoteId(id);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(`/customer-collections/${id}`);
    task.assertCurrent();
    const result = validateCollection(value, orderId);
    if (result.id !== id)
      throw new Error("El cobro corresponde a otro registro.");
    return result;
  },
  context: async (orderId: string) => {
    orderQuoteId(orderId);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(
      `/customer-collections/orders/${orderId}`,
    );
    task.assertCurrent();
    return validateCollectionContext(value, orderId);
  },
  declare: async (orderId: string, body: Readonly<CollectionInput>) => {
    orderQuoteId(orderId);
    orderQuoteId(body.request_key);
    const input = { ...body },
      task = capturePrivateTask();
    const value = await api.post<unknown>(
      `/customer-collections/orders/${orderId}`,
      input,
    );
    task.assertCurrent();
    const result = validateCollection(value, orderId);
    if (
      result.request_key !== input.request_key ||
      result.pricing.revision !== input.expected_pricing_revision ||
      result.amount_usd !== input.amount_usd ||
      result.paid_amount !== input.paid_amount ||
      result.paid_currency !== input.paid_currency ||
      result.method !== input.method ||
      result.source_key !== input.source_key ||
      result.reference_key !== input.reference_key ||
      result.received_on !== input.received_on ||
      (result.quote?.id ?? null) !== input.quote_id
    )
      throw new Error(
        "El cobro recibido no corresponde a la declaración. Reintenta la misma solicitud.",
      );
    return result;
  },
  review: async (
    orderId: string,
    id: string,
    body: Readonly<CollectionReviewInput>,
  ) => {
    orderQuoteId(orderId);
    orderQuoteId(id);
    orderQuoteId(body.request_key);
    const input = { ...body },
      task = capturePrivateTask();
    const value = await api.post<unknown>(
      `/customer-collections/${id}/review`,
      input,
    );
    task.assertCurrent();
    const result = validateCollection(value, orderId),
      review = result.review;
    if (
      result.id !== id ||
      !review ||
      review.request_key !== input.request_key ||
      review.decision !== input.decision ||
      review.note !== input.note ||
      review.verified_evidence !== input.verified_evidence ||
      review.acknowledge_refund_due !== input.acknowledge_refund_due
    )
      throw new Error(
        "La revisión recibida no corresponde a la decisión. Reintenta la misma solicitud.",
      );
    return result;
  },
};
