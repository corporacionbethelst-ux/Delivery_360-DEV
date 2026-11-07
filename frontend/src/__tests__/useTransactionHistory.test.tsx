import { act, renderHook, waitFor } from '@testing-library/react';
import { useTransactionHistory } from '@/hooks/useTransactionHistory';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
import { transactionRows } from '../../test-fixtures/transactions';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
function deferred() { let resolve!: (value: unknown) => void, reject!: (error: Error) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); download.mockReturnValue(true); });
afterEach(() => clearStoredTokens());
it.each([0, 1, 50, 51])('uses one bounded lookahead page without a fabricated total (%s)', async n => {
  get.mockResolvedValue(transactionRows(0, n)); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  expect(get).toHaveBeenCalledWith('/financial/transactions?limit=51&offset=0'); expect(h.result.current.rows).toHaveLength(Math.min(n, 50)); expect(h.result.current.hasNext).toBe(n === 51); expect(h.result.current).not.toHaveProperty('total');
});
it('navigates both ways and permits the previously hidden lookahead row at the next page start', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 51)).mockResolvedValueOnce(transactionRows(0, 51));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); }); expect(h.result.current.rows[0].id).toBe('tx-50');
  await act(async () => { await h.result.current.previous(); }); expect(h.result.current.offset).toBe(0);
  expect(get.mock.calls.map(([url]) => new URL(url, 'https://test.invalid').searchParams.get('offset'))).toEqual(['0', '50', '0']);
});
it('does not navigate past the known beginning or end', async () => {
  get.mockResolvedValue(transactionRows(0, 50)); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); await h.result.current.previous(); }); expect(get).toHaveBeenCalledTimes(1);
});
it('preserves the confirmed page after a later failure and retries the exact offset', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(transactionRows(50, 1));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true)); const snapshot = h.result.current.rows;
  await act(async () => { await h.result.current.next(); }); expect(h.result.current.rows).toBe(snapshot);
  act(() => h.result.current.exportPage()); expect(download).not.toHaveBeenCalled();
  await act(async () => { await h.result.current.retry(); }); expect(h.result.current.offset).toBe(50); expect(get.mock.calls.slice(-2).map(([url]) => url)).toEqual(['/financial/transactions?limit=51&offset=50', '/financial/transactions?limit=51&offset=50']);
});
it('applies type and status on the server, resets the offset and combines rapid filter changes', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  get.mockImplementation(async url => { const q = new URL(url, 'https://test.invalid').searchParams; const type = q.get('type') ?? 'INGRESO'; return transactionRows(0, 1, { type, transaction_type: type, status: q.get('status') ?? 'PROCESADO' }); });
  await act(async () => { const a = h.result.current.setFilter('type', 'BANK_TRANSFER'); const b = h.result.current.setFilter('status', 'PENDIENTE'); await Promise.all([a, b]); });
  expect(h.result.current).toMatchObject({ type: 'BANK_TRANSFER', status: 'PENDIENTE', offset: 0 }); expect(get).toHaveBeenLastCalledWith('/financial/transactions?type=BANK_TRANSFER&status=PENDIENTE&limit=51&offset=0');
});
it('restores the filter labels of retained data when a new server filter fails', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 1)).mockRejectedValueOnce(new Error('filter failed'));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.setFilter('status', 'PAGADO'); }); expect(h.result.current.selected.status).toBe('ALL'); expect(h.result.current.status).toBe('ALL');
});
it.each(['success', 'failure'])('ignores an old completion after a newer filter response (%s)', async mode => {
  const old = deferred(); get.mockResolvedValueOnce(transactionRows(0, 1)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(transactionRows(20, 1, { status: 'PAGADO' }));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  let pending: Promise<void> | undefined; act(() => { pending = h.result.current.setFilter('status', 'PENDIENTE'); });
  await act(async () => { await h.result.current.setFilter('status', 'PAGADO'); });
  await act(async () => { if (mode === 'success') old.resolve(transactionRows(10, 1, { status: 'PENDIENTE' })); else old.reject(new Error('old')); await pending; });
  expect(h.result.current.status).toBe('PAGADO'); expect(h.result.current.error).toBeNull(); expect(h.result.current.isLoading).toBe(false);
});
it('detects adjacent page overlap and can start fresh from page two without repeating the overlap guard', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 51)).mockResolvedValueOnce(transactionRows(99, 51)).mockResolvedValueOnce(transactionRows(49, 51));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  await act(async () => { await h.result.current.next(); await h.result.current.next(); });
  expect(h.result.current.offset).toBe(50); expect(h.result.current.error).toMatch(/cambió/);
  await act(async () => { await h.result.current.first(); }); expect(h.result.current.offset).toBe(0); expect(h.result.current.error).toBeNull();
});
it('blocks repeated page navigation synchronously while permitting a newer refresh', async () => {
  const old = deferred(); get.mockResolvedValueOnce(transactionRows(0, 51)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(transactionRows(0, 51));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  let pending: Promise<void> | undefined; act(() => { pending = h.result.current.next(); void h.result.current.next(); void h.result.current.previous(); }); expect(get).toHaveBeenCalledTimes(2);
  await act(async () => { await h.result.current.refresh(); }); await act(async () => { old.resolve(transactionRows(50, 1)); await pending; }); expect(h.result.current.offset).toBe(0);
});
it('refreshes the current page instead of silently returning to the beginning', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 1)).mockResolvedValueOnce(transactionRows(50, 1));
  const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true)); await act(async () => { await h.result.current.next(); await h.result.current.refresh(); }); expect(get).toHaveBeenLastCalledWith('/financial/transactions?limit=51&offset=50');
});
it('exports only local matches from the visible confirmed page, excluding the lookahead', async () => {
  get.mockResolvedValue(transactionRows(0, 51)); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  act(() => h.result.current.setSearch('tx-4')); act(() => h.result.current.exportPage());
  expect(download.mock.calls[0][0]).toHaveLength(11); expect(download.mock.calls[0][0].every(row => row.id !== 'tx-50')).toBe(true);
  expect(download.mock.calls[0][0][0]).toMatchObject({ filtro_tipo: 'ALL', desplazamiento_consulta: 0, busqueda_local: 'tx-4' }); expect(get).toHaveBeenCalledTimes(1);
});
it('does not query globally for a local search or download zero matches', async () => {
  get.mockResolvedValue(transactionRows(0, 51)); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  act(() => h.result.current.setSearch('absent')); act(() => h.result.current.exportPage()); expect(download).not.toHaveBeenCalled(); expect(h.result.current.hasNext).toBe(true); expect(get).toHaveBeenCalledTimes(1);
});
it('retains loaded data and permits another deliberate CSV attempt after a browser failure', async () => {
  get.mockResolvedValue(transactionRows(0, 1)); download.mockImplementationOnce(() => { throw new Error('blocked'); }); const h = renderHook(() => useTransactionHistory()); await waitFor(() => expect(h.result.current.loaded).toBe(true));
  act(() => h.result.current.exportPage()); expect(h.result.current.exportError).toBeTruthy(); expect(h.result.current.rows).toHaveLength(1);
  act(() => h.result.current.exportPage()); expect(h.result.current.exportError).toBeNull(); expect(download).toHaveBeenCalledTimes(2);
});
it('discards a completion after unmount and does not leave a missing-credential spinner', async () => {
  const old = deferred(); get.mockReturnValue(old.promise); const h = renderHook(() => useTransactionHistory()); h.unmount(); await act(async () => { old.resolve(transactionRows(0, 51)); });
  clearStoredTokens(); const other = renderHook(() => useTransactionHistory()); await waitFor(() => expect(other.result.current.isLoading).toBe(false)); expect(other.result.current.loaded).toBe(false);
});
