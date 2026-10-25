import { AxiosError, AxiosHeaders } from 'axios';
import { api } from '@/lib/api';
import { riderService } from '@/services/rider.service';
import { isDocumentRevisionConflict } from '@/lib/document-revision';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
const get = jest.mocked(api.get);
const patch = jest.mocked(api.patch);
const remove = jest.mocked(api.delete);
const id = '123e4567-e89b-42d3-a456-426614174000';
const revision = 'a'.repeat(64);
beforeEach(() => jest.clearAllMocks());

it('approves exactly the revision supplied by the reviewer', async () => {
  patch.mockResolvedValueOnce({ doc_id: id, status: 'APROBADO', revision: 'b'.repeat(64) });
  await riderService.approveDocument(id, revision);
  expect(patch).toHaveBeenCalledWith(`/riders/documents/${id}/status`, { status: 'APROBADO', expected_revision: revision });
});
it('rejects the supplied revision and trims its reason', async () => {
  patch.mockResolvedValueOnce({ doc_id: id, status: 'RECHAZADO', revision: 'b'.repeat(64) });
  await riderService.rejectDocument(id, '  Ilegible  ', revision);
  expect(patch).toHaveBeenCalledWith(`/riders/documents/${id}/status`, { status: 'RECHAZADO', rejection_reason: 'Ilegible', expected_revision: revision });
});
it('uses a quoted If-Match precondition for deletion', async () => {
  remove.mockResolvedValueOnce({ doc_id: id });
  await riderService.deleteDocument(id, revision);
  expect(remove).toHaveBeenCalledWith(`/riders/documents/${id}`, { headers: { 'If-Match': `"${revision}"` } });
});
it('binds conditional download to the same revision', async () => {
  const blob = new Blob(['file']);
  get.mockResolvedValueOnce(blob);
  await riderService.getDocumentFile(id, undefined, revision);
  expect(get).toHaveBeenCalledWith(`/riders/documents/${id}/download`, { responseType: 'blob', signal: undefined, headers: { 'If-Match': `"${revision}"` } });
});
it.each([undefined, '', 'invalid', 'A'.repeat(64)])('never submits mutations without a valid revision: %s', async (value) => {
  await expect(riderService.approveDocument(id, value)).rejects.toThrow('Recarga');
  await expect(riderService.rejectDocument(id, 'Reason', value)).rejects.toThrow('Recarga');
  await expect(riderService.deleteDocument(id, value)).rejects.toThrow('Recarga');
  expect(patch).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});
it('does not retry a failed decision with a fresh revision', async () => {
  patch.mockRejectedValueOnce(new Error('Document changed'));
  await expect(riderService.approveDocument(id, revision)).rejects.toThrow();
  expect(patch).toHaveBeenCalledTimes(1);
  expect(get).not.toHaveBeenCalled();
});
it.each([409, 412])('identifies revision conflict %s', (status) => {
  expect(isDocumentRevisionConflict(Object.assign(new Error('Changed'), { status }))).toBe(true);
});
it.each([null, new Error('network'), { status: 403 }])('does not relabel another failure as a revision conflict', (error) => {
  expect(isDocumentRevisionConflict(error)).toBe(false);
});


it('does not log authorization headers from an Axios error', async () => {
  const log = jest.spyOn(console, 'error').mockImplementation(() => undefined);
  const error = new AxiosError('Request failed', 'ERR_NETWORK', { headers: new AxiosHeaders({ Authorization: 'Bearer sensitive-unit-test-value' }) });
  patch.mockRejectedValueOnce(error);
  await expect(riderService.approveDocument(id, revision)).rejects.toThrow();
  expect(JSON.stringify(log.mock.calls)).not.toContain('sensitive-unit-test-value');
  log.mockRestore();
});
