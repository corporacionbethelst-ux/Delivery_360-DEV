import { act, renderHook, waitFor } from '@testing-library/react';
import { useRiderAudit } from '@/hooks/useRiderAudit';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditHttpResponse, auditOrderResponse } from '../../test-fixtures/rider-audit';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
function deferred() { let resolve!: (v: unknown) => void, reject!: (e: Error) => void; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); get.mockImplementation(async url => auditHttpResponse(url)); });
afterEach(() => clearStoredTokens());
it.each(['orders', 'deliveries', 'transactions'] as const)('navigates %s independently and confirms all blocks together', async key => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull());
  await act(async () => { await h.result.current.navigate(key, 1); });
  expect(h.result.current.data?.offsets).toEqual({ orders: 0, deliveries: 0, transactions: 0, [key]: 50 });
  expect(h.result.current.data?.[key].rows).toHaveLength(23); expect(h.result.current.data?.[key].hasNext).toBe(false);
  expect(get).toHaveBeenCalledTimes(8);
  await act(async () => { await h.result.current.navigate(key, -1); }); expect(h.result.current.data?.[key].offset).toBe(0);
});
it('never navigates before the beginning or beyond the end', async () => {
  get.mockImplementation(async url => auditHttpResponse(url, 1)); const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull());
  await act(async () => { for (const key of ['orders', 'deliveries', 'transactions'] as const) { await h.result.current.navigate(key, -1); await h.result.current.navigate(key, 1); } }); expect(get).toHaveBeenCalledTimes(4);
});
it('keeps the entire previous set on a page failure and retries that exact set of offsets', async () => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const before = h.result.current.data;
  let fail = true; get.mockImplementation(async url => { if (url.startsWith('/deliveries') && fail) throw new Error('offline'); return auditHttpResponse(url); });
  await act(async () => { await h.result.current.navigate('orders', 1); }); expect(h.result.current.data).toBe(before); expect(h.result.current.error).toMatch(/conjunto/);
  fail = false; await act(async () => { await h.result.current.retry(); }); expect(h.result.current.data?.offsets.orders).toBe(50); expect(h.result.current.error).toBeNull();
  expect(get.mock.calls.slice(4).filter(([url]) => url.startsWith('/orders')).map(([url]) => url)).toEqual(['/orders?rider_id=rider-1&limit=51&offset=50', '/orders?rider_id=rider-1&limit=51&offset=50']);
});
it.each(['success', 'failure'])('keeps a newer refresh when an old request completes (%s)', async mode => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const old = deferred(); let oldCall = true;
  get.mockImplementation(async url => { if (url.startsWith('/orders') && oldCall) { oldCall = false; return old.promise; } return url.startsWith('/orders') ? [auditOrderResponse('new')] : auditHttpResponse(url); });
  let retired: Promise<void>; act(() => { retired = h.result.current.refresh(); }); await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.data?.orders.rows[0].id).toBe('new');
  await act(async () => { if (mode === 'success') old.resolve([auditOrderResponse('old')]); else old.reject(new Error('old')); await retired!; });
  expect(h.result.current.data?.orders.rows[0].id).toBe('new'); expect(h.result.current.error).toBeNull(); expect(h.result.current.isLoading).toBe(false);
});
it('rejects adjacent overlaps, preserves the set and permits an explicit restart from page two', async () => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull());
  await act(async () => { await h.result.current.navigate('orders', 1); }); const pageTwo = h.result.current.data;
  get.mockImplementation(async url => url.startsWith('/orders') ? [auditOrderResponse('o-50')] : auditHttpResponse(url));
  await act(async () => { await h.result.current.navigate('orders', -1); }); expect(h.result.current.data).toBe(pageTwo); expect(h.result.current.error).not.toBeNull();
  await act(async () => { await h.result.current.first(); }); expect(h.result.current.data?.orders.offset).toBe(0); expect(h.result.current.data?.orders.rows[0].id).toBe('o-50'); expect(h.result.current.error).toBeNull();
});
it('has a synchronous busy guard against duplicate next-page clicks', async () => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const pending = deferred(); get.mockImplementation(async url => url.startsWith('/orders') ? pending.promise : auditHttpResponse(url));
  let request: Promise<void> | undefined; act(() => { request = h.result.current.navigate('orders', 1); h.result.current.navigate('orders', 1); }); expect(get).toHaveBeenCalledTimes(8);
  await act(async () => { pending.resolve([auditOrderResponse('o-50')]); await request; }); expect(h.result.current.data?.orders.offset).toBe(50);
});
it('refreshes current offsets and retires continuations on unmount', async () => {
  const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.data).not.toBeNull()); await act(async () => { await h.result.current.navigate('transactions', 1); });
  await act(async () => { await h.result.current.refresh(); }); expect(get.mock.calls.filter(([url]) => url.startsWith('/financial')).slice(-2).map(([url]) => url)).toEqual(['/financial/transactions?rider_id=rider-1&limit=51&offset=50', '/financial/transactions?rider_id=rider-1&limit=51&offset=50']);
  const pending = deferred(); get.mockImplementation(async url => url.startsWith('/orders') ? pending.promise : auditHttpResponse(url)); let request: Promise<void>; act(() => { request = h.result.current.refresh(); }); h.unmount(); await act(async () => { pending.resolve([auditOrderResponse('late')]); await request!; });
});
it('ends missing credentials with an error and no business HTTP', async () => {
  clearStoredTokens(); const h = renderHook(() => useRiderAudit('rider-1')); await waitFor(() => expect(h.result.current.isLoading).toBe(false)); expect(h.result.current.error).not.toBeNull(); expect(get).not.toHaveBeenCalled();
});
