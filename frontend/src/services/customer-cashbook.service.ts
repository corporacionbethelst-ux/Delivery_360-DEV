import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  cashFilters,
  validateCashReport,
  type CashFilters,
} from "@/lib/customer-cashbook";
export const customerCashbookService = {
  report: async (input: CashFilters = {}) => {
    const filters = cashFilters({ ...input }),
      task = capturePrivateTask();
    const params = new URLSearchParams(filters as Record<string, string>);
    const value = await api.get<unknown>(`/customer-cashbook/report?${params}`);
    task.assertCurrent();
    return validateCashReport(value, filters);
  },
};
