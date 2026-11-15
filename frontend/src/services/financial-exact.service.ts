import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  exactRange,
  validateExactReport,
  type ExactRange,
} from "@/lib/financial-exact";
export const exactFinancialService = {
  report: async (input: ExactRange = {}) => {
    const task = capturePrivateTask(),
      range = exactRange({ ...input });
    const params = new URLSearchParams(range as Record<string, string>);
    const value = await api.get<unknown>(`/financial/reports/exact?${params}`);
    task.assertCurrent();
    return validateExactReport(value, range);
  },
};
