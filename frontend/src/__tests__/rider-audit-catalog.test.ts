import { prepareAuditCatalogQuery, initialAuditCatalogQuery as initial, normalizeAuditCatalogPage, searchAuditCatalog, auditCatalogMetrics, auditCatalogCsv } from '@/lib/rider-audit-catalog';
import { normalizeAuditSummary, normalizeSummaryPage } from '@/lib/rider-audit-contract';
import { serializeCSV } from '@/lib/csv-export';
import { auditCatalogResponse } from '../../test-fixtures/rider-audit-catalog';
import { auditSummaryResponse } from '../../test-fixtures/rider-audit';
const row = (changes: Record<string, unknown> = {}) => normalizeAuditSummary(auditSummaryResponse('rider-1', changes));
it.each([{ status: 'INVALID' }, { status: null }, { online: true }, { online: false }, { online: 'FALSE' }, { offset: -50 }, { offset: 1 }, { offset: 1.5 }, { offset: Infinity }, { offset: Number.MAX_SAFE_INTEGER }, { offset: '50' }, { limit: 500 }, { rider_id: 'other' }, { search: 'name' }])('rejects unsupported or malformed query inputs rather than widening the search: %j', changes => expect(() => prepareAuditCatalogQuery({ ...initial, ...changes } as never)).toThrow());
it('captures a query by value without mutating the caller', () => { const source = { ...initial, offset: 50 }; const result = prepareAuditCatalogQuery(source); source.offset = 100; expect(result.offset).toBe(50); });
it.each([0, 1, 50, 51])('keeps a bounded page and no global total for %s reported rows', count => {
  const result = normalizeAuditCatalogPage(auditCatalogResponse(0, count), initial); expect(result.rows).toHaveLength(Math.min(50, count)); expect(result.hasNext).toBe(count === 51); expect(result).not.toHaveProperty('total');
});
it.each([null, [], { items: [] }, { ...auditCatalogResponse(), total: 900 }, { ...auditCatalogResponse(), total: -1 }, { ...auditCatalogResponse(), limit: 50 }, { ...auditCatalogResponse(), offset: 50 }, auditCatalogResponse(0, 52), { ...auditCatalogResponse(), items: [auditCatalogResponse().items[0], auditCatalogResponse().items[0]] }])('rejects malformed envelopes, false total and duplicate identities', value => expect(() => normalizeAuditCatalogPage(value, initial)).toThrow());
it('rejects two riders sharing a user identity', () => expect(() => normalizeAuditCatalogPage(auditCatalogResponse(0, 2, { user_id: 'same-user' }), initial)).toThrow());
it.each([{ status: 'SUSPENDIDO' }, { online: 'true' }])('rejects rows that do not match the confirmed server filter: %j', changes => expect(() => normalizeAuditCatalogPage(auditCatalogResponse(), { ...initial, ...changes } as never)).toThrow());
it('validates the configurable page limit without changing the detail lookup default of 100', () => {
  const response = auditCatalogResponse(); expect(normalizeSummaryPage(response, 0, 51)).toHaveLength(1); expect(() => normalizeSummaryPage(response, 0)).toThrow(); expect(() => normalizeSummaryPage(response, 0, 501)).toThrow(); expect(() => normalizeSummaryPage(response, 0, 1.5)).toThrow();
});
it.each([{ vehicle_type: {} }, { vehicle_plate: 10 }, { operating_zone: false }, { zone_id: '' }, { current_order_id: 20 }])('validates the added searchable metadata: %j', changes => expect(() => row(changes)).toThrow());
it('keeps omitted metadata unknown without changing zeros and Offline', () => expect(row()).toMatchObject({ vehicle_type: null, vehicle_plate: null, operating_zone: null, zone_id: null, current_order_id: null, last_lat: 0, last_lng: 0, is_online: false }));
it.each(['rider-1', 'user-rider-1', 'JOSÉ', 'jose', 'EXAMPLE.TEST', '58412', 'PLACA', 'centro', 'ACTIVO'])('searches only the supplied page and preserves ID/name/metadata search (%s)', term => {
  const rows = [row({ full_name: 'José Pérez', email: 'rider@example.test', phone: '+58412', vehicle_plate: 'PLACA', operating_zone: 'Centro' })]; expect(searchAuditCatalog(rows, ` ${term} `)).toHaveLength(1); expect(searchAuditCatalog(rows, 'rider-999')).toHaveLength(0);
});
it('limits metrics to supplied matches, distinguishes unknown availability and refuses unsafe sums', () => {
  expect(auditCatalogMetrics([row({ is_online: true }), row({ is_online: null })])).toEqual({ online: 1, unknownOnline: 1, activeOrders: 8 });
  expect(auditCatalogMetrics([])).toEqual({ online: 0, unknownOnline: 0, activeOrders: 0 });
  const large = row({ orders_assigned: Number.MAX_SAFE_INTEGER, orders_active: Number.MAX_SAFE_INTEGER - 3 }); expect(auditCatalogMetrics([large, large]).activeOrders).toBeNull();
});
it('exports true IDs, scope, filters, zeros, missing currency/online and actual UTC without inventing balances', () => {
  const rows = [row({ full_name: '=SUM(1,1)', is_online: null, total_earned: 0, pending_payouts: 0, available_to_payout: 0, last_location_at: '2026-11-07T08:00:00-04:00' })];
  const exported = auditCatalogCsv(rows, { status: 'ALL', online: 'ALL', offset: 50, search: 'rider-1' });
  expect(exported[0]).toMatchObject({ id_rider: 'rider-1', id_usuario: 'user-rider-1', online: null, moneda: '', latitud: 0, creditos_procesado: 0, ubicacion_fecha_utc: '2026-11-07T12:00:00.000Z', desplazamiento_consulta: 50, busqueda_local: 'rider-1' });
  expect(exported[0].alcance).toMatch(/no es el catálogo completo/); expect(exported[0]).not.toHaveProperty('available_to_payout'); expect(serializeCSV(exported)).toContain('"\'=SUM(1,1)"');
});
