import { act, renderHook, waitFor } from '@testing-library/react';
import { useFinancialReports } from '@/hooks/useFinancialReports';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { emptyOrders, ordersResponse, reconciliationResponse, reportRow } from '../../test-fixtures/financial-reports';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
const rangeFrom = (url: string) => { const q = new URL(url, 'https://test.invalid').searchParams; return { date_from: q.get('date_from') ?? undefined, date_to: q.get('date_to') ?? undefined }; };
const isOrders = (url: string) => url.includes('/reports/orders');
function deferred() { let resolve!: (value: unknown) => void, reject!: (error: Error) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
const pageRows = (count: number, total = count) => ({ total_orders: total, completed_orders: total, total_revenue: total * 10, gross_order_value: total * 100, status_counts: { ENTREGADO: total }, rows: Array.from({ length: count }, (_, i) => reportRow(`order-${i}`)) });
const ready = async (h: ReturnType<typeof renderHook<ReturnType<typeof useFinancialReports>, unknown>>) => waitFor(() => expect(h.result.current.snapshot).not.toBeNull());
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); download.mockReturnValue(true);
  get.mockImplementation(async url => isOrders(url) ? ordersResponse(rangeFrom(url)) : reconciliationResponse(rangeFrom(url)));
});
afterEach(() => clearStoredTokens());

it('commits both reads together instead of displaying a new order report beside an older reconciliation', async () => {
  const recon = deferred(); get.mockResolvedValueOnce(ordersResponse()).mockReturnValueOnce(recon.promise);
  const h = renderHook(() => useFinancialReports()); await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  expect(h.result.current.snapshot).toBeNull(); expect(h.result.current.pending).toBe('preview');
  await act(async () => { recon.resolve(reconciliationResponse()); }); await ready(h);
  expect(h.result.current.snapshot?.orders.total_orders).toBe(1); expect(h.result.current.snapshot?.reconciliation.currency).toBe('COP');
});
it.each(['orders', 'reconciliation'])('retains the last complete pair when %s fails and retries the applied range', async failed => {
  const h = renderHook(() => useFinancialReports()); await ready(h); const confirmed = h.result.current.snapshot;
  act(() => h.result.current.setDraft('start', '2026-11-01'));
  get.mockImplementation(async url => { if (failed === (isOrders(url) ? 'orders' : 'reconciliation')) throw new Error('failed'); return isOrders(url) ? ordersResponse(rangeFrom(url)) : reconciliationResponse(rangeFrom(url)); });
  await act(async () => { await h.result.current.apply(); });
  expect(h.result.current.snapshot).toBe(confirmed); expect(h.result.current.error).toBeTruthy(); expect(h.result.current.dirty).toBe(true);
  get.mockImplementation(async url => isOrders(url) ? ordersResponse(rangeFrom(url)) : reconciliationResponse(rangeFrom(url)));
  await act(async () => { await h.result.current.retry(); }); expect(h.result.current.snapshot?.range.date_from).toBe('2026-11-01');
});
it('treats editing dates as a draft without requesting or exporting a different range', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h);
  act(() => h.result.current.setDraft('start', '2026-11-01'));
  expect(get).toHaveBeenCalledTimes(2); expect(h.result.current.canExport).toBe(false);
  await act(async () => { await h.result.current.exportCsv(); }); expect(download).not.toHaveBeenCalled(); expect(get).toHaveBeenCalledTimes(2);
});
it('rejects reversed dates without clearing confirmed data or starting HTTP', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h); const snapshot = h.result.current.snapshot;
  act(() => { h.result.current.setDraft('start', '2026-11-07'); h.result.current.setDraft('end', '2026-11-01'); });
  await act(async () => { await h.result.current.apply(); }); expect(get).toHaveBeenCalledTimes(2);
  expect(h.result.current.snapshot).toBe(snapshot); expect(h.result.current.error?.message).toMatch(/inicio/); expect(h.result.current.pending).toBeNull();
});
it.each(['success', 'failure'])('does not publish an older range completion after a newer applied range (%s)', async mode => {
  const old = deferred(); const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(url => isOrders(url) && url.includes('2026-11-01') ? old.promise : Promise.resolve(isOrders(url) ? ordersResponse(rangeFrom(url)) : reconciliationResponse(rangeFrom(url))));
  act(() => h.result.current.setDraft('start', '2026-11-01'));
  let pending: Promise<void> | undefined; act(() => { pending = h.result.current.apply(); });
  act(() => h.result.current.setDraft('start', '2026-11-02')); await act(async () => { await h.result.current.apply(); });
  await act(async () => { if (mode === 'success') old.resolve(ordersResponse({ date_from: '2026-11-01' })); else old.reject(new Error('old')); await pending; });
  expect(h.result.current.snapshot?.range.date_from).toBe('2026-11-02'); expect(h.result.current.error).toBeNull();
});
it('does not stop a newer loading indicator when the old pair completes first', async () => {
  const first = deferred(), second = deferred(); const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(url => isOrders(url) ? url.includes('2026-11-01') ? first.promise : second.promise : Promise.resolve(reconciliationResponse(rangeFrom(url))));
  act(() => h.result.current.setDraft('start', '2026-11-01')); let a: Promise<void> | undefined, b: Promise<void> | undefined;
  act(() => { a = h.result.current.apply(); }); act(() => h.result.current.setDraft('start', '2026-11-02')); act(() => { b = h.result.current.apply(); });
  await act(async () => { first.resolve(ordersResponse({ date_from: '2026-11-01' })); await a; }); expect(h.result.current.pending).toBe('preview');
  await act(async () => { second.resolve(ordersResponse({ date_from: '2026-11-02' })); await b; }); expect(h.result.current.pending).toBeNull();
});
it('prepares a complete bounded export and updates both metrics atomically, without treating a preview as the complete CSV', async () => {
  get.mockImplementation(async url => isOrders(url) ? ordersResponse({}, pageRows(url.includes('limit=5000') ? 1200 : 1000, 1200)) : reconciliationResponse());
  const h = renderHook(() => useFinancialReports()); await ready(h); expect(h.result.current.snapshot?.orders.rows).toHaveLength(1000);
  await act(async () => { await h.result.current.exportCsv(); });
  expect(download.mock.calls[0][0]).toHaveLength(1200); expect(download.mock.calls[0][1]).toContain('sin_inicio_sin_fin_1200_filas');
  expect(h.result.current.snapshot?.orders.rows).toHaveLength(1200); expect(h.result.current.notice).toMatch(/CSV generado/);
});
it('guards export synchronously against repeated clicks', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h);
  await act(async () => { const first = h.result.current.exportCsv(); const second = h.result.current.exportCsv(); await Promise.all([first, second]); });
  expect(get).toHaveBeenCalledTimes(4); expect(download).toHaveBeenCalledTimes(1);
});
it('cancels an in-flight export when the draft changes', async () => {
  const pending = deferred(); const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(url => isOrders(url) ? pending.promise : Promise.resolve(reconciliationResponse()));
  let work: Promise<void> | undefined; act(() => { work = h.result.current.exportCsv(); });
  act(() => h.result.current.setDraft('end', '2026-11-07'));
  await act(async () => { pending.resolve(ordersResponse()); await work; });
  expect(download).not.toHaveBeenCalled(); expect(h.result.current.error?.message).toMatch(/canceló/); expect(h.result.current.pending).toBeNull();
});
it('does not cancel an export for a change event that leaves the dates unchanged', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h);
  await act(async () => { const work = h.result.current.exportCsv(); h.result.current.setDraft('start', ''); await work; }); expect(download).toHaveBeenCalledTimes(1);
});
it('retires export work when a newer applied read supersedes it', async () => {
  const pending = deferred(); const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(url => isOrders(url) && url.includes('limit=5000') ? pending.promise : Promise.resolve(isOrders(url) ? ordersResponse() : reconciliationResponse()));
  let work: Promise<void> | undefined; act(() => { work = h.result.current.exportCsv(); }); await act(async () => { await h.result.current.apply(); });
  await act(async () => { pending.resolve(ordersResponse()); await work; }); expect(download).not.toHaveBeenCalled();
});
it('refuses a now-oversized export after the count grows between preview and download', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h); const old = h.result.current.snapshot;
  get.mockImplementation(async url => isOrders(url) ? ordersResponse({}, pageRows(5000, 5001)) : reconciliationResponse());
  await act(async () => { await h.result.current.exportCsv(); });
  expect(download).not.toHaveBeenCalled(); expect(h.result.current.error?.message).toMatch(/5001/); expect(h.result.current.canExport).toBe(false); expect(h.result.current.snapshot).toBe(old);
});
it('does not offer exporting a known oversized range', async () => {
  get.mockImplementation(async url => isOrders(url) ? ordersResponse({}, pageRows(1000, 5001)) : reconciliationResponse());
  const h = renderHook(() => useFinancialReports()); await ready(h); expect(h.result.current.canExport).toBe(false);
});
it('retains a valid empty response without creating an empty CSV after rows disappear', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(async url => isOrders(url) ? ordersResponse({}, emptyOrders) : reconciliationResponse());
  await act(async () => { await h.result.current.exportCsv(); }); expect(download).not.toHaveBeenCalled(); expect(h.result.current.snapshot?.orders.total_orders).toBe(0); expect(h.result.current.notice).toMatch(/No hay órdenes/);
});
it('keeps the valid pair and allows a deliberate retry when the browser download fails', async () => {
  const h = renderHook(() => useFinancialReports()); await ready(h); download.mockImplementationOnce(() => { throw new Error('blocked'); });
  await act(async () => { await h.result.current.exportCsv(); }); expect(h.result.current.snapshot).not.toBeNull(); expect(h.result.current.notice).toBeNull(); expect(h.result.current.error?.message).toMatch(/descarga CSV/);
  await act(async () => { await h.result.current.retry(); }); expect(download).toHaveBeenCalledTimes(2); expect(h.result.current.notice).toMatch(/CSV generado/);
});
it('does not create a file after unmounting with an export pending', async () => {
  const pending = deferred(); const h = renderHook(() => useFinancialReports()); await ready(h);
  get.mockImplementation(url => isOrders(url) ? pending.promise : Promise.resolve(reconciliationResponse()));
  let work: Promise<void> | undefined; act(() => { work = h.result.current.exportCsv(); }); h.unmount();
  await act(async () => { pending.resolve(ordersResponse()); await work; }); expect(download).not.toHaveBeenCalled();
});
it('ends a missing-credentials read without sending HTTP or showing fake metrics', async () => {
  clearStoredTokens(); const h = renderHook(() => useFinancialReports()); await waitFor(() => expect(h.result.current.pending).toBeNull());
  expect(get).not.toHaveBeenCalled(); expect(h.result.current.snapshot).toBeNull(); expect(h.result.current.error).toBeTruthy();
});
