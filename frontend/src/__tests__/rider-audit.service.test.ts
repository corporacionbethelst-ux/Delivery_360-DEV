import { api } from '@/lib/api';
import { readRiderAudit } from '@/services/rider-audit.service';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { initialAuditOffsets } from '@/lib/rider-audit-contract';
import { auditSummaryResponse as summary, auditSummaryPage, auditOrderResponse as order, auditDeliveryPage, auditTransactionResponse as transaction } from '../../test-fixtures/rider-audit';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
let summaryReply: (offset: number) => unknown;
const baseline = (url: string) => url.startsWith('/riders/') ? summaryReply(Number(new URL(url, 'https://test.invalid').searchParams.get('offset'))) : url.startsWith('/orders?') ? [order()] : url.startsWith('/deliveries?') ? auditDeliveryPage() : [transaction()];
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); summaryReply = () => auditSummaryPage(); get.mockImplementation(async url => baseline(url)); });
afterEach(() => clearStoredTokens());
it('makes bounded real GET queries with explicit rider identity, offset and include_total', async () => {
  const result = await readRiderAudit('rider-1', initialAuditOffsets);
  expect(get.mock.calls.map(([url]) => url)).toEqual(['/riders/audit/summary?limit=100&offset=0', '/orders?rider_id=rider-1&limit=51&offset=0', '/deliveries?rider_id=rider-1&limit=51&offset=0&include_total=true', '/financial/transactions?rider_id=rider-1&limit=51&offset=0']);
  expect(result.summary.row?.rider_id).toBe('rider-1'); expect(result.orders.rows[0].amount).toBe(0);
});
it('continues past a full summary page despite its misleading total of 100', async () => {
  summaryReply = offset => auditSummaryPage(offset === 0 ? Array.from({ length: 100 }, (_, i) => summary(`other-${i}`)) : [summary()], offset);
  const result = await readRiderAudit('rider-1', initialAuditOffsets);
  expect(result.summary).toMatchObject({ scanned: 101, limitReached: false, row: { rider_id: 'rider-1' } }); expect(get).toHaveBeenCalledTimes(5);
});
it('stops after at most 500 scanned summaries and returns explicit absence within the bound', async () => {
  summaryReply = offset => auditSummaryPage(Array.from({ length: 100 }, (_, i) => summary(`r-${offset + i}`)), offset);
  const result = await readRiderAudit('rider-1', initialAuditOffsets);
  expect(result.summary).toEqual({ row: null, scanned: 500, limitReached: true }); expect(get).toHaveBeenCalledTimes(8);
});
it('allows a missing summary after an exhausted short page without pretending the rider does not exist', async () => {
  summaryReply = () => auditSummaryPage([]); expect((await readRiderAudit('rider-1', initialAuditOffsets)).summary).toEqual({ row: null, scanned: 0, limitReached: false });
});
it('rejects changing/duplicated summary identities on later pages', async () => {
  summaryReply = offset => auditSummaryPage(offset === 0 ? Array.from({ length: 100 }, (_, i) => summary(`other-${i}`)) : [summary('other-0'), summary()], offset);
  await expect(readRiderAudit('rider-1', initialAuditOffsets)).rejects.toThrow();
});
it.each(['/orders?', '/deliveries?', '/financial/transactions?', '/riders/'])('does not publish a partial set when %s fails', async prefix => {
  get.mockImplementation(async url => { if (url.startsWith(prefix)) throw new Error('failure'); return baseline(url); }); await expect(readRiderAudit('rider-1', initialAuditOffsets)).rejects.toThrow('failure');
});
it.each(['success', 'failure'])('retires old credentials after HTTP %s and stops further summary pages', async mode => {
  get.mockImplementation(async url => { if (url.startsWith('/riders/')) { storeTokens({ access_token: 'b', refresh_token: 'rb' }); if (mode === 'failure') throw new Error('old error'); return auditSummaryPage(Array.from({ length: 100 }, (_, i) => summary(`r-${i}`))); } return baseline(url); });
  await expect(readRiderAudit('rider-1', initialAuditOffsets)).rejects.toThrow(/sesión cambió/); expect(get.mock.calls.filter(([url]) => url.startsWith('/riders/'))).toHaveLength(1);
});
it('checks route/request ownership before another summary page with the same credentials', async () => {
  let active = true;
  get.mockImplementation(async url => { const result = url.startsWith('/riders/') ? auditSummaryPage(Array.from({ length: 100 }, (_, i) => summary(`r-${i}`))) : baseline(url); if (url.startsWith('/riders/')) active = false; return result; });
  await expect(readRiderAudit('rider-1', initialAuditOffsets, () => { if (!active) throw new Error('retired route'); })).rejects.toThrow('retired route'); expect(get.mock.calls.filter(([url]) => url.startsWith('/riders/'))).toHaveLength(1);
});
it('captures caller offsets before awaiting HTTP', async () => {
  const offsets = { ...initialAuditOffsets }; const pending = readRiderAudit('rider-1', offsets); offsets.orders = 50; const result = await pending; expect(result.offsets.orders).toBe(0);
});
it('rejects unknown routes/offsets before any business reads', async () => {
  await expect(readRiderAudit('', initialAuditOffsets)).rejects.toThrow(); await expect(readRiderAudit('rider-1', { ...initialAuditOffsets, orders: -1 })).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
