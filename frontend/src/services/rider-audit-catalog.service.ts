import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { AUDIT_PAGE_SIZE } from '@/lib/rider-audit-contract';
import { initialAuditCatalogQuery, normalizeAuditCatalogPage, prepareAuditCatalogQuery, type AuditCatalogQuery } from '@/lib/rider-audit-catalog';

export async function readAuditCatalogPage(input: Readonly<AuditCatalogQuery> = initialAuditCatalogQuery) {
  const task = capturePrivateTask(), captured = prepareAuditCatalogQuery(input);
  const query = new URLSearchParams();
  if (captured.status !== 'ALL') query.set('status_filter', captured.status);
  if (captured.online !== 'ALL') query.set('is_online', captured.online);
  query.set('limit', String(AUDIT_PAGE_SIZE + 1)); query.set('offset', String(captured.offset));
  try {
    const raw = await api.get<unknown>(`/riders/audit/summary?${query}`);
    task.assertCurrent(); return normalizeAuditCatalogPage(raw, captured);
  } catch (error) { task.assertCurrent(); throw error; }
}
