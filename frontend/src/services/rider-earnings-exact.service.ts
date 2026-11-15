import { orderQuoteId } from "@/lib/order-currency-quote";
import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  validateRiderReport,
  validateRiderBalance,
} from "@/lib/rider-earnings-exact";
export const riderExactService = {
  report: async (userId: string) => {
    orderQuoteId(userId);
    const task = capturePrivateTask();
    const raw = await api.get<unknown>("/financial/riders/me/report");
    task.assertCurrent();
    return validateRiderReport(raw, userId);
  },
  balance: async (userId: string) => {
    orderQuoteId(userId);
    const task = capturePrivateTask();
    const raw = await api.get<unknown>("/payouts/balance/exact");
    task.assertCurrent();
    return validateRiderBalance(raw, userId);
  },
};
