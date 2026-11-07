import { act, renderHook, waitFor } from '@testing-library/react';
import { useRiderAuditCatalog } from '@/hooks/useRiderAuditCatalog';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditCatalogHttpResponse, auditCatalogResponse } from '../../test-fixtures/rider-audit-catalog';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
function deferred() { let resolve!: (v: unknown) => void, reject!: (e: Error) => void; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); get.mockImplementation(async url => auditCatalogHttpResponse(url)); download.mockReturnValue(true); });
afterEach(() => clearStoredTokens());
it.each([0, 1, 50, 51])('keeps bounded visible rows and a lookahead signal for %s records', async count => { get.mockResolvedValue(auditCatalogResponse(0, count)); const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); expect(h.result.current.visibleRows).toHaveLength(Math.min(50, count)); expect(h.result.current.data?.hasNext).toBe(count === 51); });
it('navigates both ways, accepts the previous hidden lookahead and stops at the end', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); await act(async () => { await h.result.current.navigate(-1); await h.result.current.navigate(1); }); expect(h.result.current.data?.query.offset).toBe(50); expect(h.result.current.data?.hasNext).toBe(false);
  await act(async () => { await h.result.current.navigate(1); await h.result.current.navigate(-1); }); expect(h.result.current.data?.query.offset).toBe(0); expect(get).toHaveBeenCalledTimes(3);
});
it('preserves data/filters on a later failure, blocks CSV and retries the exact page', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const initial = h.result.current.data; get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await h.result.current.navigate(1); }); expect(h.result.current.data).toBe(initial); expect(h.result.current.error).not.toBeNull(); act(() => h.result.current.exportPage()); expect(download).not.toHaveBeenCalled();
  await act(async () => { await h.result.current.retry(); }); expect(h.result.current.data?.query.offset).toBe(50); expect(get.mock.calls.slice(-2).map(([url]) => url)).toEqual(['/riders/audit/summary?limit=51&offset=50', '/riders/audit/summary?limit=51&offset=50']);
});
it.each(['success', 'failure'])('combines rapid filters, resets offset and retires the older %s', async mode => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); await act(async () => { await h.result.current.navigate(1); }); const old = deferred(); get.mockReturnValueOnce(old.promise);
  let retired: Promise<void> | undefined; act(() => { retired = h.result.current.setFilter('status', 'SUSPENDIDO'); }); await act(async () => { await h.result.current.setFilter('online', 'false'); }); expect(h.result.current.data?.query).toEqual({ status: 'SUSPENDIDO', online: 'false', offset: 0 });
  await act(async () => { if (mode === 'success') old.resolve(auditCatalogResponse(0, 1, { status: 'SUSPENDIDO' })); else old.reject(new Error('old')); await retired; }); expect(h.result.current.error).toBeNull(); expect(h.result.current.data?.query.online).toBe('false');
});
it('reverts a failed filter selector to the confirmed query and keeps the failed attempt for retry', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await h.result.current.setFilter('status', 'INACTIVO'); }); expect(h.result.current.selected.status).toBe('ALL');
  await act(async () => { await h.result.current.retry(); }); expect(h.result.current.selected.status).toBe('INACTIVO');
});
it.each(['rider', 'user'])('rejects adjacent %s overlap without discarding the previous page', async kind => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const previous = h.result.current.data;
  get.mockResolvedValueOnce(auditCatalogResponse(50, 1, kind === 'rider' ? { rider_id: 'rider-0' } : { user_id: 'user-rider-0' })); await act(async () => { await h.result.current.navigate(1); }); expect(h.result.current.data).toBe(previous); expect(h.result.current.error).not.toBeNull();
});
it('preserves the explicit restart semantics even if restarting fails once and is retried', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); await act(async () => { await h.result.current.navigate(1); }); get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await h.result.current.first(); }); expect(h.result.current.data?.query.offset).toBe(50);
  get.mockResolvedValueOnce(auditCatalogResponse(0, 1, { rider_id: 'rider-50' })); await act(async () => { await h.result.current.retry(); }); expect(h.result.current.data?.query.offset).toBe(0); expect(h.result.current.error).toBeNull();
});
it('blocks duplicate navigation synchronously and lets a newer refresh supersede a pending page', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const old = deferred(); get.mockReturnValueOnce(old.promise); let pending: Promise<void> | undefined;
  act(() => { pending = h.result.current.navigate(1); h.result.current.navigate(1); }); expect(get).toHaveBeenCalledTimes(2);
  await act(async () => { await h.result.current.refresh(); }); await act(async () => { old.resolve(auditCatalogResponse(50, 1)); await pending; }); expect(h.result.current.data?.query.offset).toBe(0); expect(h.result.current.error).toBeNull();
});
it('exports only current-page search matches and captured context, excludes lookahead, without more HTTP', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull());
  act(() => { h.result.current.setSearch('rider-49'); h.result.current.exportPage(); }); expect(download).toHaveBeenCalledWith([expect.objectContaining({ id_rider: 'rider-49', moneda: '', busqueda_local: 'rider-49', desplazamiento_consulta: 0 })], 'auditoria_riders_pagina_1_1_filas'); expect(get).toHaveBeenCalledTimes(1);
  act(() => { h.result.current.setSearch('rider-50'); h.result.current.exportPage(); }); expect(download).toHaveBeenCalledTimes(1); await act(async () => { await h.result.current.navigate(1); }); act(() => h.result.current.exportPage()); expect(download).toHaveBeenLastCalledWith([expect.objectContaining({ id_rider: 'rider-50', desplazamiento_consulta: 50 })], 'auditoria_riders_pagina_2_1_filas');
});
it.each(['throw', 'false'])('keeps data and recovers from CSV failure (%s)', async kind => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); if (kind === 'throw') download.mockImplementationOnce(() => { throw new Error('blocked'); }); else download.mockReturnValueOnce(false);
  act(() => h.result.current.exportPage()); expect(h.result.current.exportError).toMatch(/CSV/); expect(h.result.current.data).not.toBeNull(); act(() => h.result.current.exportPage()); expect(h.result.current.exportError).toBeNull();
});
it('does not export while reading or after unmount, and retires late read completions', async () => {
  const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.data).not.toBeNull()); const old = deferred(); get.mockReturnValueOnce(old.promise); let pending: Promise<void>;
  act(() => { pending = h.result.current.refresh(); h.result.current.exportPage(); }); expect(download).not.toHaveBeenCalled(); h.unmount(); await act(async () => { old.resolve(auditCatalogResponse()); await pending!; }); act(() => h.result.current.exportPage()); expect(download).not.toHaveBeenCalled();
});
it('ends missing credentials without HTTP or a stuck spinner', async () => { clearStoredTokens(); const h = renderHook(useRiderAuditCatalog); await waitFor(() => expect(h.result.current.isLoading).toBe(false)); expect(h.result.current.error).not.toBeNull(); expect(get).not.toHaveBeenCalled(); });
