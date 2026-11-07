import { act, renderHook, waitFor } from '@testing-library/react';
import { usePayoutPages, PAYOUT_PAGE_SIZE } from '@/hooks/usePayoutPages';
import { PayoutSessionBoundary } from '@/components/financial/PayoutSessionBoundary';
import { payoutService, type Payout } from '@/services/payout.service';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';

jest.mock('@/services/payout.service', () => ({ payoutService: { getAll: jest.fn() } }));
const get = jest.mocked(payoutService.getAll);
const rows = (start: number, count: number, status: Payout['status'] = 'PENDIENTE'): Payout[] => Array.from({ length: count }, (_, index) => ({ id: `p-${start + index}`, rider_id: 'r', amount: 10, total_amount: 10, method: 'EFECTIVO', status, requested_at: null, created_at: null, updated_at: null }));
function deferred() { let resolve!: (value: Payout[]) => void, reject!: (error: Error) => void; const promise = new Promise<Payout[]>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it.each([0, 1, 49, 50, 51])('requests one bounded page with lookahead and only displays 50 rows at most (%s)', async count => {
  get.mockResolvedValue(rows(0, count)); const h = renderHook(() => usePayoutPages());
  await waitFor(() => expect(h.result.current.loaded).toBe(true));
  expect(get).toHaveBeenCalledWith({ limit: 51, offset: 0, status: undefined });
  expect(get).toHaveBeenCalledTimes(1); expect(h.result.current.rows).toHaveLength(Math.min(count, 50));
  expect(h.result.current.hasNext).toBe(count === 51);
});
it('navigates forwards/backwards with server offsets and permits the previous lookahead as the next first row', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce(rows(50, 51)).mockResolvedValueOnce(rows(0, 51));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); });
  expect(h.result.current).toMatchObject({ offset: 50, hasNext: true }); expect(h.result.current.rows[0].id).toBe('p-50');
  await act(async () => { await h.result.current.previous(); });
  expect(h.result.current.offset).toBe(0); expect(get.mock.calls.map(([query]) => query?.offset)).toEqual([0, 50, 0]);
});
it('does not navigate before the first page or beyond an observed end', async () => {
  get.mockResolvedValue(rows(0, 50)); const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); await h.result.current.previous(); }); expect(get).toHaveBeenCalledTimes(1);
});
it('resets the offset for server status filters and commits the selection with its successful data', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce(rows(50, 51)).mockResolvedValueOnce(rows(100, 2, 'EN_PROCESO'));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); });
  await act(async () => { await h.result.current.setStatus('EN_PROCESO'); });
  expect(get).toHaveBeenLastCalledWith({ limit: 51, offset: 0, status: 'EN_PROCESO' });
  expect(h.result.current).toMatchObject({ offset: 0, status: 'EN_PROCESO', selectedStatus: 'EN_PROCESO', hasNext: false });
});
it('retains the confirmed page after a later-page failure and retries the same query', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockRejectedValueOnce(new Error('second page failed')).mockResolvedValueOnce(rows(50, 1));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  const original = h.result.current.rows;
  await act(async () => { await h.result.current.next(); });
  expect(h.result.current.rows).toBe(original); expect(h.result.current.offset).toBe(0); expect(h.result.current.error).toBeTruthy();
  await act(async () => { await h.result.current.retry(); }); expect(h.result.current.offset).toBe(50);
  expect(get.mock.calls.slice(-2).map(([query]) => query?.offset)).toEqual([50, 50]);
});
it('reverts a failed filter to the label of the retained data and retains the failed query for retry', async () => {
  get.mockResolvedValueOnce(rows(0, 1)).mockRejectedValueOnce(new Error('filter failed')).mockResolvedValueOnce(rows(100, 1, 'COMPLETADO'));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.setStatus('COMPLETADO'); });
  expect(h.result.current).toMatchObject({ status: 'ALL', selectedStatus: 'ALL', offset: 0 });
  await act(async () => { await h.result.current.retry(); }); expect(get).toHaveBeenLastCalledWith({ limit: 51, offset: 0, status: 'COMPLETADO' });
});
it.each(['success', 'failure'])('does not publish an earlier filter completion/error after the newer one (%s)', async mode => {
  const old = deferred(); get.mockResolvedValueOnce(rows(0, 1)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(rows(100, 1, 'COMPLETADO'));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  let first!: Promise<void> | undefined;
  act(() => { first = h.result.current.setStatus('PENDIENTE'); });
  expect(h.result.current.selectedStatus).toBe('PENDIENTE');
  await act(async () => { await h.result.current.setStatus('COMPLETADO'); });
  await act(async () => { if (mode === 'success') old.resolve(rows(0, 1)); else old.reject(new Error('old')); await first; });
  expect(h.result.current).toMatchObject({ status: 'COMPLETADO', selectedStatus: 'COMPLETADO', error: null, isLoading: false });
});
it('detects adjacent-page drift instead of deduplicating or advancing and allows a fresh first page', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce(rows(49, 51)).mockResolvedValueOnce(rows(100, 51));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); });
  expect(h.result.current.offset).toBe(0); expect(h.result.current.error).toMatch(/cambió entre páginas/); expect(h.result.current.rows[0].id).toBe('p-0');
  await act(async () => { await h.result.current.first(); }); expect(h.result.current.error).toBeNull(); expect(h.result.current.rows[0].id).toBe('p-100');
});
it('detects a contradictory adjacent page when navigating backwards too', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce(rows(50, 51)).mockResolvedValueOnce(rows(1, 51));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); }); await act(async () => { await h.result.current.previous(); });
  expect(h.result.current.offset).toBe(50); expect(h.result.current.error).toBeTruthy();
});
it('disables navigation synchronously during a pending page but allows a newer status to supersede it', async () => {
  const old = deferred(); get.mockResolvedValueOnce(rows(0, 51)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(rows(100, 1, 'FALLIDO'));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  let pending: Promise<void> | undefined;
  act(() => { pending = h.result.current.next(); void h.result.current.next(); void h.result.current.previous(); });
  expect(get).toHaveBeenCalledTimes(2);
  await act(async () => { await h.result.current.setStatus('FALLIDO'); }); await act(async () => { old.resolve(rows(50, 1)); await pending; });
  expect(h.result.current.status).toBe('FALLIDO');
});
it('refreshes the current offset instead of silently returning to the first page', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce(rows(50, 1)).mockResolvedValueOnce(rows(50, 1));
  const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); }); await act(async () => { await h.result.current.refresh(); });
  expect(get).toHaveBeenLastCalledWith({ limit: 51, offset: 50, status: undefined });
});
it('clears retired credentials and does not continue their navigation under the new account', async () => {
  const old = deferred(); get.mockResolvedValueOnce(rows(0, 51)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(rows(200, 1));
  const h = renderHook(() => usePayoutPages(), { wrapper: PayoutSessionBoundary }); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  let pending: Promise<void> | undefined;
  act(() => { pending = h.result.current.next(); });
  act(() => storeTokens({ access_token: 'b', refresh_token: 'rb' }));
  await waitFor(() => expect(h.result.current.rows[0]?.id).toBe('p-200'));
  await act(async () => { old.resolve(rows(50, 1)); await pending; });
  expect(h.result.current.offset).toBe(0); expect(h.result.current.rows[0].id).toBe('p-200');
  expect(get.mock.calls.map(([q]) => q?.offset)).toEqual([0, 50, 0]);
});
it('does not send requests when disabled and discards data when the scope is disabled', async () => {
  get.mockResolvedValue(rows(0, 1));
  const h = renderHook(({ enabled }) => usePayoutPages(enabled), { initialProps: { enabled: false } });
  expect(get).not.toHaveBeenCalled(); h.rerender({ enabled: true }); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  h.rerender({ enabled: false }); expect(h.result.current.rows).toEqual([]); expect(h.result.current.loaded).toBe(false);
});
it('reports missing credentials without making a request or leaving a permanent spinner', async () => {
  clearStoredTokens(); const h = renderHook(() => usePayoutPages());
  await waitFor(() => expect(h.result.current.isLoading).toBe(false)); expect(get).not.toHaveBeenCalled(); expect(h.result.current.error).toBeTruthy();
});
it('ignores unsupported historical filters without sending a silently ignored parameter', async () => {
  get.mockResolvedValue(rows(0, 1)); const h = renderHook(() => usePayoutPages()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.setStatus('CANCELADO'); }); expect(get).toHaveBeenCalledTimes(1);
});
it('discards a completion after unmount without starting another page', async () => {
  const old = deferred(); get.mockReturnValue(old.promise); const h = renderHook(() => usePayoutPages()); h.unmount();
  await act(async () => { old.resolve(rows(0, 51)); }); expect(get).toHaveBeenCalledTimes(1);
});
it('accepts a now-empty later page without inventing a global zero total', async () => {
  get.mockResolvedValueOnce(rows(0, 51)).mockResolvedValueOnce([]); const h = renderHook(() => usePayoutPages());
  await waitFor(() => expect(h.result.current.loaded).toBe(true)); await act(async () => { await h.result.current.next(); });
  expect(h.result.current).toMatchObject({ offset: PAYOUT_PAGE_SIZE, rows: [], hasNext: false, loaded: true });
  expect(h.result.current).not.toHaveProperty('total');
});
