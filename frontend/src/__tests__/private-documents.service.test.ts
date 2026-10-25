import { api } from '@/lib/api';
import { riderService } from '@/services/rider.service';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
const id = '123e4567-e89b-42d3-a456-426614174000';

beforeEach(() => jest.clearAllMocks());

it('uses the authenticated API client with a fixed relative endpoint and cancellation', async () => {
  const blob = new Blob(['document'], { type: 'application/pdf' });
  const signal = new AbortController().signal;
  get.mockResolvedValueOnce(blob);
  expect(await riderService.getDocumentFile(id, signal)).toBe(blob);
  expect(get).toHaveBeenCalledWith(`/riders/documents/${id}/download`, { responseType: 'blob', signal });
});

it.each(['', 'https://evil.test/file', '../secret', 'not-a-uuid'])('rejects an invalid document identifier: %s', async (value) => {
  await expect(riderService.getDocumentFile(value)).rejects.toThrow('ID de documento inválido');
  expect(get).not.toHaveBeenCalled();
});

it('propagates a download failure without falling back to a public URL', async () => {
  get.mockRejectedValueOnce(new Error('denied'));
  await expect(riderService.getDocumentFile(id)).rejects.toThrow();
  expect(get).toHaveBeenCalledTimes(1);
});
