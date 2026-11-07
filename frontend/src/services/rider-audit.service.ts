import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { AUDIT_PAGE_SIZE, AUDIT_SUMMARY_MAX_PAGES, AUDIT_SUMMARY_PAGE_SIZE, auditId, boundedAuditPage, normalizeAuditDeliveries, normalizeAuditOrder, normalizeSummaryPage, prepareAuditOffsets, type AuditOffsets, type AuditSummary } from '@/lib/rider-audit-contract';
import { normalizeTransactionPage, prepareTransactionQuery } from '@/lib/transaction-contract';

async function findSummary(riderId: string, assertCurrent: () => void) {
  const riders = new Set<string>(), users = new Set<string>();
  for (let page = 0; page < AUDIT_SUMMARY_MAX_PAGES; page++) {
    assertCurrent();
    const offset = page * AUDIT_SUMMARY_PAGE_SIZE;
    const raw = await api.get<unknown>(`/riders/audit/summary?limit=${AUDIT_SUMMARY_PAGE_SIZE}&offset=${offset}`);
    assertCurrent();
    const rows = normalizeSummaryPage(raw, offset);
    for (const row of rows) {
      if (riders.has(row.rider_id) || users.has(row.user_id)) throw new Error('El catálogo de auditoría cambió entre páginas');
      riders.add(row.rider_id); users.add(row.user_id);
    }
    const summary = rows.find(row => row.rider_id === riderId);
    if (summary) return { row: summary as AuditSummary | null, scanned: riders.size, limitReached: false };
    if (rows.length < AUDIT_SUMMARY_PAGE_SIZE) return { row: null, scanned: riders.size, limitReached: false };
  }
  return { row: null, scanned: riders.size, limitReached: true };
}

/** A single confirmed UI set; independent server reads do not form a DB snapshot. */
export async function readRiderAudit(value: string, offsets: Readonly<AuditOffsets>, assertActive: () => void = () => {}) {
  const task = capturePrivateTask(), riderId = auditId(value), query = prepareAuditOffsets(offsets);
  let stopped = false;
  const assertCurrent = () => { task.assertCurrent(); assertActive(); if (stopped) throw new Error('Lectura retirada'); };
  const get = async (url: string) => { assertCurrent(); const raw = await api.get<unknown>(url); assertCurrent(); return raw; };
  const pageQuery = (offset: number) => new URLSearchParams({ rider_id: riderId, limit: String(AUDIT_PAGE_SIZE + 1), offset: String(offset) });
  try {
    const [summary, orders, deliveries, transactions] = await Promise.all([
      findSummary(riderId, assertCurrent),
      get(`/orders?${pageQuery(query.orders)}`).then(raw => boundedAuditPage(raw, query.orders, row => normalizeAuditOrder(row, riderId))),
      get(`/deliveries?${pageQuery(query.deliveries)}&include_total=true`).then(raw => normalizeAuditDeliveries(raw, riderId, query.deliveries)),
      get(`/financial/transactions?${pageQuery(query.transactions)}`).then(raw => {
        const captured = prepareTransactionQuery({ rider_id: riderId, limit: AUDIT_PAGE_SIZE + 1, offset: query.transactions });
        return boundedAuditPage(normalizeTransactionPage(raw, captured), query.transactions, row => row as ReturnType<typeof normalizeTransactionPage>[number]);
      }),
    ]);
    assertCurrent();
    return { riderId, offsets: query, summary, orders, deliveries, transactions };
  } catch (error) { stopped = true; task.assertCurrent(); assertActive(); throw error; }
}
export type RiderAuditSnapshot = Awaited<ReturnType<typeof readRiderAudit>>;
