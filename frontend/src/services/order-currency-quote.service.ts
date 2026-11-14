import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  orderQuoteId,
  validateOrderQuote,
  validateOrderQuoteContext,
  type OrderQuoteInput,
} from "@/lib/order-currency-quote";

export const orderCurrencyQuoteService = {
  context: async (orderId: string) => {
    orderQuoteId(orderId);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(
      `/currency/orders/${encodeURIComponent(orderId)}/quotes`,
    );
    task.assertCurrent();
    return validateOrderQuoteContext(value, orderId);
  },
  create: async (orderId: string, body: Readonly<OrderQuoteInput>) => {
    orderQuoteId(orderId);
    orderQuoteId(body.request_key);
    orderQuoteId(body.rate_id);
    if (
      !Number.isSafeInteger(body.expected_pricing_revision) ||
      body.expected_pricing_revision < 1 ||
      body.expected_pricing_revision > 2147483647
    )
      throw new Error("Revisión de precio inválida.");
    const input = {
      request_key: body.request_key,
      rate_id: body.rate_id,
      expected_pricing_revision: body.expected_pricing_revision,
    };
    const task = capturePrivateTask();
    const value = await api.post<unknown>(
      `/currency/orders/${encodeURIComponent(orderId)}/quotes`,
      input,
    );
    task.assertCurrent();
    const result = validateOrderQuote(value, orderId);
    if (
      result.request_key !== input.request_key ||
      result.pricing.revision !== input.expected_pricing_revision ||
      result.rate.id !== input.rate_id
    )
      throw new Error(
        "El comprobante confirmado no corresponde al precio y tasa revisados.",
      );
    return result;
  },
  receipt: async (id: string, orderId: string) => {
    orderQuoteId(id);
    orderQuoteId(orderId);
    const task = capturePrivateTask();
    const value = await api.get<unknown>(
      `/currency/order-quotes/${encodeURIComponent(id)}`,
    );
    task.assertCurrent();
    const result = validateOrderQuote(value, orderId);
    if (result.id !== id)
      throw new Error("El comprobante recibido pertenece a otra referencia.");
    return result;
  },
};
