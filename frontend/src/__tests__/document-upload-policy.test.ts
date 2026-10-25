import { validateDocumentSelection, MAX_DOCUMENT_BYTES } from '@/lib/document-upload';
import { riderService } from '@/services/rider.service';
import { authService } from '@/services/auth.service';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
const post = jest.mocked(api.post);
const id = '123e4567-e89b-42d3-a456-426614174000';
const valid = () => new File(['%PDF-1.4 content'], 'document.pdf', { type: 'application/pdf' });
beforeEach(() => jest.clearAllMocks());

it.each([
  ['image.png', 'image/png'], ['image.JPG', 'image/jpeg'],
  ['image.jpeg', 'application/octet-stream'], ['document.pdf', ''],
])('accepts a permitted selection %s (%s)', (name, type) => {
  expect(() => validateDocumentSelection(new File(['bytes'], name, { type }))).not.toThrow();
});

it.each([
  new File([], 'empty.pdf', { type: 'application/pdf' }),
  new File(['<svg/>'], 'image.svg', { type: 'image/svg+xml' }),
  new File(['html'], 'file.pdf', { type: 'text/html' }),
  new File(['text'], 'missing-extension'),
  new File(['bytes'], 'pdf', { type: 'application/pdf' }),
  new File(['bytes'], '.pdf', { type: 'application/pdf' }),
])('rejects an invalid selection before upload: %s', (file) => {
  expect(() => validateDocumentSelection(file)).toThrow();
});

it('accepts the exact byte limit and rejects one byte more', () => {
  const file = valid();
  Object.defineProperty(file, 'size', { configurable: true, value: MAX_DOCUMENT_BYTES });
  expect(() => validateDocumentSelection(file)).not.toThrow();
  Object.defineProperty(file, 'size', { value: MAX_DOCUMENT_BYTES + 1 });
  expect(() => validateDocumentSelection(file)).toThrow('10 MiB');
});

it.each(['owner', 'admin'])('does not submit an invalid file for %s', async (who) => {
  const request = { type: 'LICENCIA', file: new File(['<svg/>'], 'image.svg', { type: 'image/svg+xml' }) };
  await expect(who === 'owner' ? riderService.uploadDocument(request) : riderService.uploadDocumentForRider(id, request)).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});

it.each(['owner', 'admin'])('sends a valid multipart document for %s', async (who) => {
  post.mockResolvedValueOnce({ id, status: 'PENDIENTE' });
  const file = valid();
  const request = { type: 'LICENCIA', file };
  if (who === 'owner') await riderService.uploadDocument(request);
  else await riderService.uploadDocumentForRider(id, request);
  const [path, body] = post.mock.calls[0];
  expect(path).toBe(who === 'owner' ? '/riders/me/documents/upload' : `/riders/${id}/documents/upload`);
  expect(body).toBeInstanceOf(FormData);
  expect((body as FormData).get('file')).toBe(file);
});

const fields = ['license_file', 'id_card_file', 'vehicle_registration_file', 'insurance_file'];
const form = () => {
  const data = new FormData();
  fields.forEach(key => data.set(key, valid()));
  return data;
};

it('validates all four registration files before submitting', async () => {
  const data = form();
  data.set('insurance_file', new File(['html'], 'bad.html', { type: 'text/html' }));
  await expect(authService.register(data)).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});

it('rejects missing registration files instead of sending a partial request', async () => {
  const data = form();
  data.delete('license_file');
  await expect(authService.register(data)).rejects.toThrow('cuatro documentos');
  expect(post).not.toHaveBeenCalled();
});

it('preserves a valid multipart registration payload', async () => {
  const data = form();
  post.mockResolvedValueOnce({ user_id: id });
  await authService.register(data);
  expect(post).toHaveBeenCalledWith('/auth/register-rider', data, expect.any(Object));
});
