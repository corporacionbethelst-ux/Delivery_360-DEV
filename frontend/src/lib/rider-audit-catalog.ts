import { AUDIT_PAGE_SIZE, normalizeSummaryPage, RIDER_AUDIT_STATUSES, type AuditSummary } from '@/lib/rider-audit-contract';

export interface AuditCatalogQuery {
  status: typeof RIDER_AUDIT_STATUSES[number] | 'ALL';
  online: 'ALL' | 'true' | 'false';
  offset: number;
}
export const initialAuditCatalogQuery: AuditCatalogQuery = { status: 'ALL', online: 'ALL', offset: 0 };
export function prepareAuditCatalogQuery(input: Readonly<AuditCatalogQuery>): AuditCatalogQuery {
  const query = { ...input };
  if (Object.keys(query).length !== 3 || Object.keys(query).some(key => !['status', 'online', 'offset'].includes(key)) ||
      query.status !== 'ALL' && !RIDER_AUDIT_STATUSES.includes(query.status) || !['ALL', 'true', 'false'].includes(query.online) ||
      !Number.isSafeInteger(query.offset) || query.offset < 0 || query.offset % AUDIT_PAGE_SIZE !== 0) throw new Error('Consulta de auditoría inválida');
  return query;
}
export function normalizeAuditCatalogPage(value: unknown, query: Readonly<AuditCatalogQuery>) {
  const captured = prepareAuditCatalogQuery(query);
  const rows = normalizeSummaryPage(value, captured.offset, AUDIT_PAGE_SIZE + 1);
  if (rows.some(row => captured.status !== 'ALL' && row.status !== captured.status || captured.online !== 'ALL' && row.is_online !== (captured.online === 'true'))) throw new Error('El servidor devolvió repartidores fuera del filtro');
  return { query: captured, rows: rows.slice(0, AUDIT_PAGE_SIZE), hasNext: rows.length > AUDIT_PAGE_SIZE };
}
export type AuditCatalogSnapshot = ReturnType<typeof normalizeAuditCatalogPage>;
export const auditOnlineLabel = (value: AuditCatalogQuery['online']) => ({ ALL: 'Todos', true: 'Online', false: 'Offline' })[value];
export function searchAuditCatalog(rows: AuditSummary[], search: string) {
  const fold = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');
  const term = fold(search.trim());
  return rows.filter(row => [row.rider_id, row.user_id, row.full_name, row.email, row.phone, row.vehicle_plate, row.operating_zone, row.status].some(value => value != null && fold(value).includes(term)));
}
export function auditCatalogMetrics(rows: AuditSummary[]) {
  const active = rows.reduce((sum, row) => sum + row.orders_active, 0);
  return { online: rows.filter(row => row.is_online === true).length, unknownOnline: rows.filter(row => row.is_online === null).length,
    activeOrders: Number.isSafeInteger(active) ? active : null };
}
export function auditCatalogCsv(rows: AuditSummary[], context: AuditCatalogQuery & { search: string }) {
  return rows.map(row => ({
    id_rider: row.rider_id, id_usuario: row.user_id, nombre: row.full_name ?? '', email: row.email ?? '', telefono: row.phone ?? '',
    estado: row.status ?? '', online: row.is_online, tipo_vehiculo: row.vehicle_type ?? '', placa: row.vehicle_plate ?? '', zona: row.operating_zone ?? '',
    id_zona: row.zone_id ?? '', id_orden_actual: row.current_order_id ?? '', latitud: row.last_lat, longitud: row.last_lng,
    ubicacion_fecha_utc: row.last_location_at ? new Date(row.last_location_at).toISOString() : '',
    ordenes_asignadas: row.orders_assigned, ordenes_entregadas: row.orders_delivered, ordenes_activas: row.orders_active,
    entregas_total: row.deliveries_total, entregas_completadas: row.deliveries_completed, entregas_fallidas: row.deliveries_failed, entregas_en_curso: row.deliveries_in_progress,
    sla_cumplidas: row.sla_compliant, sla_denominador: row.deliveries_total, sla_porcentaje_informado: row.sla_compliance_rate,
    creditos_procesado: row.total_earned, retiros_pendiente: row.pending_payouts, moneda: row.currency ?? '',
    filtro_estado: context.status, filtro_online: context.online, desplazamiento_consulta: context.offset, busqueda_local: context.search,
    alcance: 'Solo coincidencias de la página cargada; no es el catálogo completo',
  }));
}
