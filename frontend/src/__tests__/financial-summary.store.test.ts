import { api } from '@/lib/api';
import { useFinancialStore } from '@/stores/financialStore';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { summaryResponse, zeroSummary } from '../../test-fixtures/financial-summary';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));
const get = jest.mocked(api.get), state = () => useFinancialStore.getState();
function deferred() { let resolve!: (value: unknown) => void, reject!: (error: Error) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it('leaves an unavailable initial summary unknown rather than storing all-zero metrics', async () => {
  get.mockRejectedValue(new Error('unavailable')); await state().fetchSummary();
  expect(state()).toMatchObject({ summary: null, isLoading: false }); expect(state().error).toBeTruthy();
});
it('preserves a valid snapshot after a failed or malformed refresh', async () => {
  get.mockResolvedValueOnce(summaryResponse()).mockRejectedValueOnce(new Error('refresh')).mockResolvedValueOnce({});
  await state().fetchSummary(); const confirmed = state().summary;
  await state().fetchSummary(); expect(state().summary).toBe(confirmed); expect(state().error).toBeTruthy();
  await state().fetchSummary(); expect(state().summary).toBe(confirmed); expect(state().isLoading).toBe(false);
});
it('adapts the actual summary contract and leaves metrics not supplied by it unknown', async () => {
  get.mockResolvedValue(summaryResponse('week')); const result = await state().getDailySummary('week');
  expect(get).toHaveBeenCalledWith('/financial/summary?period=week');
  expect(result).toMatchObject({ period: 'week', totalRevenue: 100, totalCosts: 40, netProfit: 60, riderPayments: 30, netCommission: null, pendingPayouts: null, activeDeliveries: null, pendingPayments: null });
});
it('keeps measured zeros distinct from unavailable data', async () => {
  get.mockResolvedValue(summaryResponse('today', zeroSummary)); await state().fetchSummary();
  expect(state().summary).toMatchObject({ totalRevenue: 0, netProfit: 0 }); expect(state().error).toBeNull();
});
it.each(['success', 'error'])('ignores an older completion while another summary entry point wins (%s)', async mode => {
  const old = deferred(); get.mockReturnValueOnce(old.promise).mockResolvedValueOnce(summaryResponse('month'));
  const pending = state().fetchSummary(); await state().getDailySummary('month');
  if (mode === 'success') old.resolve(summaryResponse()); else old.reject(new Error('old'));
  await pending; expect(state().summary?.period).toBe('month'); expect(state().error).toBeNull(); expect(state().isLoading).toBe(false);
});
it('does not stop a newer spinner when an older summary completes', async () => {
  const old = deferred(), newer = deferred(); get.mockReturnValueOnce(old.promise).mockReturnValueOnce(newer.promise);
  const a = state().fetchSummary(), b = state().getDailySummary('month');
  old.resolve(summaryResponse()); await a; expect(state().isLoading).toBe(true);
  newer.resolve(summaryResponse('month')); await b; expect(state().isLoading).toBe(false);
});
it('rejects a period unsupported by the server without sending an ignored parameter', async () => {
  expect(await state().getDailySummary('year')).toBeNull(); expect(get).not.toHaveBeenCalled(); expect(state().error).toBeTruthy();
});
it('does not restore private summary data after changing account', async () => {
  const old = deferred(); get.mockReturnValueOnce(old.promise);
  const pending = state().fetchSummary(); storeTokens({ access_token: 'b', refresh_token: 'rb' }); old.resolve(summaryResponse());
  await expect(pending).rejects.toBeInstanceOf(SessionChangedError); expect(state().summary).toBeNull(); expect(state().isLoading).toBe(false);
});
