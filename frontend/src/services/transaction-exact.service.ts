import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  prepareTransactionQuery,
  transactionId,
} from "@/lib/transaction-contract";
import { normalizeExactTransactionPage } from "@/lib/transaction-exact";
import type { TransactionFilters } from "@/services/transaction.service";
export const exactTransactionService = {
  getAll: async (input?: Readonly<TransactionFilters>) => {
    const task = capturePrivateTask(),
      query = prepareTransactionQuery(input),
      params = new URLSearchParams();
    for (const name of [
      "type",
      "status",
      "rider_id",
      "date_from",
      "date_to",
    ] as const)
      if (query[name] !== undefined) params.set(name, query[name]!);
    params.set("limit", String(query.limit));
    params.set("offset", String(query.offset));
    try {
      const raw = await api.get<unknown>(
        `/financial/transactions/exact/page?${params}`,
      );
      task.assertCurrent();
      return normalizeExactTransactionPage(raw, query);
    } catch (e) {
      task.assertCurrent();
      throw e;
    }
  },
  getById: async (value: string) => {
    const task = capturePrivateTask(),
      id = transactionId(typeof value === "string" ? value.trim() : value);
    try {
      const raw = await api.get<unknown>(
        `/financial/transactions/exact/${encodeURIComponent(id)}`,
      );
      task.assertCurrent();
      const page = normalizeExactTransactionPage(
        raw,
        prepareTransactionQuery({ limit: 1, offset: 0 }),
        id,
      );
      return { ...page.items[0], read_context: page.read_context };
    } catch (e) {
      task.assertCurrent();
      throw e;
    }
  },
};
export type ExactTransactionDetail = Awaited<
  ReturnType<typeof exactTransactionService.getById>
>;
