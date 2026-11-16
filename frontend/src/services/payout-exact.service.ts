import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import { transactionId } from "@/lib/transaction-contract";
import {
  normalizeExactPayoutPage,
  prepareExactPayoutQuery,
} from "@/lib/payout-exact";
import type { PayoutPageFilters } from "@/services/payout.service";
export const exactPayoutService = {
  getPage: async (
    input?: Readonly<PayoutPageFilters & { audience?: "STAFF" | "OWNER" }>,
  ) => {
    const task = capturePrivateTask(),
      q = prepareExactPayoutQuery(input),
      params = new URLSearchParams();
    if (q.audience !== null) params.set("audience", q.audience);
    if (q.rider_id !== null) params.set("rider_id", q.rider_id);
    if (q.status !== null) params.set("status", q.status);
    params.set("limit", String(q.limit));
    if (q.cursor !== null) params.set("cursor", q.cursor);
    try {
      const raw = await api.get<unknown>(`/payouts/exact/page?${params}`);
      task.assertCurrent();
      return normalizeExactPayoutPage(raw, q);
    } catch (e) {
      task.assertCurrent();
      throw e;
    }
  },
  getDetail: async (value: string, audience?: "STAFF" | "OWNER") => {
    const task = capturePrivateTask(),
      id = transactionId(typeof value === "string" ? value.trim() : value);
    try {
      const raw = await api.get<unknown>(
        `/payouts/exact/${encodeURIComponent(id)}${audience ? "?audience=" + audience : ""}`,
      );
      task.assertCurrent();
      const p = normalizeExactPayoutPage(
        raw,
        prepareExactPayoutQuery({ limit: 1, audience }),
        id,
      );
      return {
        payout: p.items[0],
        history: p.history,
        read_context: p.read_context,
      };
    } catch (e) {
      task.assertCurrent();
      throw e;
    }
  },
};
