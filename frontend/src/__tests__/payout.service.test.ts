import { api } from '@/lib/api';
import { payoutService, PayoutStatus } from '@/services/payout.service';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
const get = jest.mocked(api.get);
const post = jest.mocked(api.post);
const patch = jest.mocked(api.patch);
const row = { id: 'payout-1', rider_id: 'rider-1', amount: 12.5, status: 'PENDIENTE', method: 'TRANSFERENCIA', created_at: '2026-10-24T10:00:00' };
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => jest.restoreAllMocks());

it.each<PayoutStatus>(['PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO', 'PROCESADO', 'CANCELADO'])('accepts %s without relabeling it as paid', async (status) => {
  get.mockResolvedValueOnce([{ ...row, status }]);
  const result = await payoutService.getAll();
  expect(result[0]).toMatchObject({ status, amount: 12.5, created_at: row.created_at });
});
it('normalizes aliases and clamps pagination without sending ALL', async () => {
  get.mockResolvedValueOnce([{ ...row, amount: undefined, total_amount: 15, method: undefined, payment_method: 'EFECTIVO' }]);
  const result = await payoutService.getAll({ rider_id: ' rider-1 ', status: 'ALL', limit: 999, offset: 2.9 });
  expect(get).toHaveBeenCalledWith('/payouts?rider_id=rider-1&limit=200&offset=2');
  expect(result[0]).toMatchObject({ amount: 15, total_amount: 15, method: 'EFECTIVO', processed_at: null });
});
it('sends canonical status filters', async () => {
  get.mockResolvedValueOnce([]);
  await payoutService.getAll({ status: 'EN_PROCESO', offset: -1, limit: 0 });
  expect(get).toHaveBeenCalledWith('/payouts?status=EN_PROCESO&limit=1');
});
it.each([{ id: '' }, { rider_id: '' }, { status: 'PAID' }, { method: 'UNKNOWN' }, { amount: NaN }, { amount: Infinity }, { amount: -1 }, { amount: 0 }])('rejects malformed backend data: %j', async (invalid) => {
  get.mockResolvedValueOnce([{ ...row, ...invalid }]);
  await expect(payoutService.getAll()).rejects.toThrow();
});
it.each([0, -1, NaN, Infinity])('does not submit invalid amounts: %s', async (amount) => {
  await expect(payoutService.requestPayout({ amount, method: 'TRANSFERENCIA' })).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it('preserves caller idempotency keys and bank details', async () => {
  post.mockResolvedValueOnce(row);
  const request = { amount: 12.5, method: 'TRANSFERENCIA' as const, bank_account_last4: '1234', idempotency_key: 'retry-1' };
  await payoutService.requestPayout(request);
  expect(post).toHaveBeenCalledWith('/payouts/request', request);
});
it('assigns a key for new requests', async () => {
  post.mockResolvedValueOnce(row);
  await payoutService.requestPayout({ amount: 12.5, method: 'TRANSFERENCIA' });
  expect(post).toHaveBeenCalledWith('/payouts/request', expect.objectContaining({ idempotency_key: expect.any(String) }));
});
it('approval preserves the backend in-process state', async () => {
  patch.mockResolvedValueOnce({ ...row, status: 'EN_PROCESO' });
  expect((await payoutService.approve(' payout-1 ')).status).toBe('EN_PROCESO');
  expect(patch).toHaveBeenCalledWith('/payouts/payout-1/approve');
});
it('trims rejection details', async () => {
  patch.mockResolvedValueOnce({ ...row, status: 'RECHAZADO' });
  expect((await payoutService.reject(' payout-1 ', ' no funds ')).status).toBe('RECHAZADO');
  expect(patch).toHaveBeenCalledWith('/payouts/payout-1/reject', { rejection_reason: 'no funds' });
});
it('rejects blank identifiers and reasons before making requests', async () => {
  await expect(payoutService.approve(' ')).rejects.toThrow();
  await expect(payoutService.reject('id', ' ')).rejects.toThrow();
  await expect(payoutService.getById(' ')).rejects.toThrow();
  await expect(payoutService.getHistory(' ')).rejects.toThrow();
  expect(patch).not.toHaveBeenCalled();
  expect(get).not.toHaveBeenCalled();
});
it('propagates server failures', async () => {
  const failure = new Error('Server unavailable');
  post.mockRejectedValueOnce(failure);
  await expect(payoutService.requestPayout({ amount: 12.5, method: 'EFECTIVO' })).rejects.toBe(failure);
});
it('retrieves balances, detail and audit history', async () => {
  get.mockResolvedValueOnce({ available: 10, pending: 2 }).mockResolvedValueOnce(row).mockResolvedValueOnce([]);
  expect(await payoutService.getAvailableBalance(' rider 1 ')).toEqual({ available: 10, pending: 2 });
  expect(get).toHaveBeenNthCalledWith(1, '/payouts/balance?rider_id=rider%201');
  expect((await payoutService.getById(' payout-1 ')).id).toBe('payout-1');
  expect(await payoutService.getHistory(' payout-1 ')).toEqual([]);
  expect(get).toHaveBeenNthCalledWith(3, '/payouts/payout-1/history');
});
