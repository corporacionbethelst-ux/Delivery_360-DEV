import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import { orderQuoteId } from "@/lib/order-currency-quote";
import { payoutKey } from "@/lib/payout-contract";
import { payoutHttpStatus } from "@/services/payout.service";
import { confirmExactWithdrawal, intentAmount } from "@/lib/withdrawal-exact";
import type { WithdrawalIntent } from "@/lib/withdrawal-intent";

function payload(intent: WithdrawalIntent) {
  orderQuoteId(intent.userId);
  payoutKey(intent.key);
  if (intent.version !== 1 || !/^(?:[0-9]{4})?$/.test(intent.bankLast4))
    throw new Error("Datos de solicitud inválidos");
  return {
    currency: "USD",
    amount: intentAmount(intent),
    method: "TRANSFERENCIA",
    bank_account_last4: intent.bankLast4 || undefined,
    idempotency_key: intent.key,
  };
}
export const withdrawalExactService = {
  request: async (saved: WithdrawalIntent, riderId?: string) => {
    const intent = { ...saved },
      body = payload(intent),
      task = capturePrivateTask();
    if (riderId !== undefined) orderQuoteId(riderId);
    try {
      const response = await api.post<unknown>("/payouts/request", body);
      task.assertCurrent();
      return confirmExactWithdrawal(response, intent, riderId);
    } catch (e) {
      task.assertCurrent();
      throw e;
    }
  },
  find: async (saved: WithdrawalIntent, riderId?: string) => {
    const intent = { ...saved };
    payload(intent);
    if (riderId !== undefined) orderQuoteId(riderId);
    const task = capturePrivateTask();
    try {
      const response = await api.get<unknown>(
        `/payouts/request-status?idempotency_key=${encodeURIComponent(intent.key)}`,
      );
      task.assertCurrent();
      return confirmExactWithdrawal(response, intent, riderId);
    } catch (e) {
      task.assertCurrent();
      if (payoutHttpStatus(e) === 404) return null;
      throw e;
    }
  },
};
