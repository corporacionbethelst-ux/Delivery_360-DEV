import { auditSummaryResponse, exactAuditEnvelope } from './rider-audit';
export function auditCatalogResponse(start = 0, count = 1, changes: Record<string, unknown> = {}) {
  const items = Array.from({ length: count }, (_, index) => auditSummaryResponse(`rider-${start + index}`, {
    full_name: `José ${start + index}`, phone: '+584121234567', vehicle_type: 'MOTO', vehicle_plate: `PLACA-${start + index}`,
    operating_zone: 'Centro', zone_id: 'zone-1', current_order_id: null, ...changes,
  }));
  return exactAuditEnvelope(items, new URLSearchParams({limit:"51",offset:String(start)}));
}
export function auditCatalogHttpResponse(url: string, total = 73) {
  const query = new URL(url, 'https://test.invalid').searchParams;
  const offset = Number(query.get('offset') ?? 0), status = query.get('status_filter') ?? 'ACTIVO', online = query.get('is_online');
  const result = auditCatalogResponse(offset, Math.max(0, Math.min(51, total - offset)), { status, is_online: online === null ? false : online === 'true' });
  return exactAuditEnvelope(result.items, query);
}
