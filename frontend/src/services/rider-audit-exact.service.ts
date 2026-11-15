import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  normalizeExactAuditPage,
  normalizeExactAuditCatalog,
} from "@/lib/rider-audit-exact";
import {
  initialAuditCatalogQuery,
  prepareAuditCatalogQuery,
  type AuditCatalogQuery,
} from "@/lib/rider-audit-catalog";
import {
  AUDIT_PAGE_SIZE,
  auditId,
  prepareAuditOffsets,
  boundedAuditPage,
  normalizeAuditOrder,
  normalizeAuditDeliveries,
  type AuditOffsets,
} from "@/lib/rider-audit-contract";
import {
  normalizeTransactionPage,
  prepareTransactionQuery,
} from "@/lib/transaction-contract";
export async function readExactAuditCatalogPage(
  input: Readonly<AuditCatalogQuery> = initialAuditCatalogQuery,
) {
  const task = capturePrivateTask(),
    query = prepareAuditCatalogQuery(input),
    p = new URLSearchParams();
  if (query.status !== "ALL") p.set("status_filter", query.status);
  if (query.online !== "ALL") p.set("is_online", query.online);
  p.set("limit", String(AUDIT_PAGE_SIZE + 1));
  p.set("offset", String(query.offset));
  try {
    const raw = await api.get<unknown>(`/riders/audit/summary/exact?${p}`);
    task.assertCurrent();
    return normalizeExactAuditCatalog(raw, query);
  } catch (e) {
    task.assertCurrent();
    throw e;
  }
}
export async function readExactRiderAudit(
  value: string,
  offsets: Readonly<AuditOffsets>,
  assertActive: () => void = () => {},
) {
  const task = capturePrivateTask(),
    riderId = auditId(value),
    query = prepareAuditOffsets(offsets);
  let stopped = false;
  const assertCurrent = () => {
    task.assertCurrent();
    assertActive();
    if (stopped) throw new Error("Lectura retirada");
  };
  const get = async (url: string) => {
    assertCurrent();
    const raw = await api.get<unknown>(url);
    assertCurrent();
    return raw;
  };
  const params = (offset: number) =>
    new URLSearchParams({
      rider_id: riderId,
      limit: String(AUDIT_PAGE_SIZE + 1),
      offset: String(offset),
    });
  try {
    const [exact, orders, deliveries, transactions] = await Promise.all([
      get(
        `/riders/audit/summary/exact?rider_id=${encodeURIComponent(riderId)}&limit=1&offset=0`,
      ).then((raw) =>
        normalizeExactAuditPage(raw, {
          rider_id: riderId,
          status: null,
          online: null,
          limit: 1,
          offset: 0,
        }),
      ),
      get(`/orders?${params(query.orders)}`).then((raw) =>
        boundedAuditPage(raw, query.orders, (row) =>
          normalizeAuditOrder(row, riderId),
        ),
      ),
      get(`/deliveries?${params(query.deliveries)}&include_total=true`).then(
        (raw) => normalizeAuditDeliveries(raw, riderId, query.deliveries),
      ),
      get(`/financial/transactions?${params(query.transactions)}`).then((raw) =>
        boundedAuditPage(
          normalizeTransactionPage(
            raw,
            prepareTransactionQuery({
              rider_id: riderId,
              limit: AUDIT_PAGE_SIZE + 1,
              offset: query.transactions,
            }),
          ),
          query.transactions,
          (row) => row as ReturnType<typeof normalizeTransactionPage>[number],
        ),
      ),
    ]);
    assertCurrent();
    return {
      riderId,
      offsets: query,
      summary: {
        row: exact.items[0] ?? null,
        scanned: exact.items.length,
        limitReached: false,
        generated_at: exact.generated_at,
        content_sha256: exact.content_sha256,
      },
      orders,
      deliveries,
      transactions,
    };
  } catch (e) {
    stopped = true;
    task.assertCurrent();
    assertActive();
    throw e;
  }
}
export type ExactRiderAuditSnapshot = Awaited<
  ReturnType<typeof readExactRiderAudit>
>;
