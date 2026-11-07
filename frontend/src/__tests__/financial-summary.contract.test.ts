import { api } from '@/lib/api';
import { financialService } from '@/services/financial.service';
import { normalizeFinancialSummary, prepareSummaryQuery } from '@/lib/financial-summary-contract';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { summaryResponse, zeroSummary } from '../../test-fixtures/financial-summary';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it('retains measured zeros, optional absences and an explicit unknown currency', () => {
  const result = normalizeFinancialSummary(summaryResponse('today', { ...zeroSummary, other_costs: undefined, cash_payouts_processed: undefined }), {});
  expect(result).toMatchObject({ total_revenue: 0, total_transactions: 0, net_margin: 0, other_costs: null, cash_payouts_processed: null, currency: null });
});
it('preserves negative margins and decimal wire amounts without coercing them to positive values', () => {
  const result = normalizeFinancialSummary(summaryResponse('today', { total_revenue: '10.25', total_costs: '40.00', net_margin: '-29.75' }), {});
  expect(result).toMatchObject({ total_revenue: 10.25, total_costs: 40, net_margin: -29.75 });
});
it.each(['total_revenue', 'total_costs', 'net_margin', 'total_rider_payouts', 'total_transactions', 'avg_per_delivery', 'period'])('does not invent missing required field %s', field => {
  expect(() => normalizeFinancialSummary(summaryResponse('today', { [field]: undefined }), {})).toThrow();
});
it.each([true, false, null, undefined, '', ' ', NaN, Infinity, '-1', '1.001', '1e3', '90071992547410'])('rejects malformed/unsafe nonnegative money (%j)', value => {
  expect(() => normalizeFinancialSummary(summaryResponse('today', { total_revenue: value }), {})).toThrow();
});
it.each([-1, 1.5, '8', false, NaN, Number.MAX_SAFE_INTEGER + 1])('requires measured nonnegative integer counts (%j)', value => {
  expect(() => normalizeFinancialSummary(summaryResponse('today', { total_transactions: value }), {})).toThrow();
});
it.each([
  { net_margin: 59 }, { total_rider_payouts: 41 }, { other_costs: 11 },
  { cash_payouts_processed: 31 }, { rider_earnings_accrued: 36 }, { degraded: true },
  { period: 'month' }, { currency: 'usd' }, { currency: 0 },
  { period_start: '2026-02-30T00:00:00' }, { period_end: 'not-a-date' },
  { period_end: '2026-11-05T00:00:00' }, { period_start: '2026-11-06T01:00:00' },
])('rejects contradictions instead of publishing a misleading summary (%j)', changes => {
  expect(() => normalizeFinancialSummary(summaryResponse('today', changes), {})).toThrow();
});
it('preserves a genuinely supplied currency and ignores unrelated payload fields', () => {
  const result = normalizeFinancialSummary(summaryResponse('today', { currency: 'COP', internal_metadata: 'unused' }), {});
  expect(result.currency).toBe('COP'); expect(result).not.toHaveProperty('internal_metadata');
});
it('keeps omitted range dates unknown instead of substituting today', () => {
  expect(normalizeFinancialSummary(summaryResponse('today', { period_start: null, period_end: undefined }), {})).toMatchObject({ period_start: null, period_end: null });
});
it.each(['today', 'week', 'month'] as const)('checks UTC calendar boundaries for %s', period => {
  const result = normalizeFinancialSummary(summaryResponse(period), { period });
  expect(result.period).toBe(period); expect(result.period_end).toBe('2026-11-06T18:00:00Z');
  expect(() => normalizeFinancialSummary(summaryResponse(period, { period_start: '2026-11-05T00:00:00' }), { period })).toThrow();
});
it('normalizes timezone offsets before the server strips them and validates the returned custom interval', async () => {
  get.mockResolvedValue(summaryResponse('custom', { period_end: '2026-10-24T18:00:00' }));
  const result = await financialService.getSummary({ start_date: '2026-10-01T04:00:00+04:00', end_date: '2026-10-24T14:00:00-04:00' });
  expect(get).toHaveBeenCalledWith('/financial/summary?start_date=2026-10-01T00%3A00%3A00.000Z&end_date=2026-10-24T18%3A00%3A00.000Z');
  expect(result.period).toBe('custom');
});
it.each([{ period_start: '2026-10-02T00:00:00' }, { period_end: '2026-10-24T00:00:00' }, { period_start: null }])('rejects an ignored custom boundary (%j)', changes => {
  expect(() => normalizeFinancialSummary(summaryResponse('custom', changes), { start_date: '2026-10-01', end_date: '2026-10-24' })).toThrow();
});
it.each([
  { period: 'year' }, { start_date: '' }, { start_date: '2026-11-31' }, { start_date: false },
  { start_date: '2026-11-06T24:00:00' }, { start_date: '2026-11-06', end_date: '2026-11-05' },
])('rejects unsupported queries before HTTP (%j)', async query => {
  await expect(financialService.getSummary(query as never)).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
it('accepts a same-day date range and custom end without assuming the server current date', () => {
  expect(prepareSummaryQuery({ start_date: '2026-11-06T10:00:00', end_date: '2026-11-06' })).toMatchObject({ start_date: '2026-11-06T10:00:00.000Z', end_date: '2026-11-06' });
  expect(normalizeFinancialSummary(summaryResponse('month', { period_end: '2026-12-01T00:00:00' }), { period: 'month', end_date: '2026-12-01T00:00:00Z' }).period).toBe('month');
});
it('validates the captured query after the caller mutates its input', async () => {
  let resolve!: (value: unknown) => void;
  get.mockReturnValue(new Promise(done => { resolve = done; }));
  const query = { period: 'week' as const };
  const pending = financialService.getSummary(query); Object.assign(query, { period: 'month' });
  resolve(summaryResponse('week'));
  expect((await pending).period).toBe('week'); expect(get).toHaveBeenCalledWith('/financial/summary?period=week');
});
it.each(['success', 'error'])('retires summary continuations across credential changes (%s)', async mode => {
  let resolve!: (value: unknown) => void, reject!: (error: Error) => void;
  get.mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
  const pending = financialService.getSummary(); storeTokens({ access_token: 'b', refresh_token: 'rb' });
  if (mode === 'success') resolve(summaryResponse()); else reject(new Error('retired request'));
  await expect(pending).rejects.toBeInstanceOf(SessionChangedError);
});
it('does not request summary data without credentials', async () => {
  clearStoredTokens(); await expect(financialService.getSummary()).rejects.toBeInstanceOf(SessionChangedError);
  expect(get).not.toHaveBeenCalled();
});
