import { api } from '@/lib/api';
import { payoutService, type PayoutRequestInput } from '@/services/payout.service';
import { normalizePayout, normalizePayoutBalance, normalizePayoutHistory, confirmWithdrawal, payoutCents, payoutDateLabel, payoutAmountLabel } from '@/lib/payout-contract';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import type { WithdrawalIntent } from '@/lib/withdrawal-intent';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
const row = { id: 'p', rider_id: 'r', amount: 60, total_amount: 60, status: 'PENDIENTE', method: 'TRANSFERENCIA', payment_method: 'TRANSFERENCIA', idempotency_key: 'key', requested_by_user_id: 'user', bank_account_last4: '1234' };
const request: PayoutRequestInput = { amount: 60, method: 'TRANSFERENCIA', idempotency_key: 'key', bank_account_last4: '1234' };
const intent: WithdrawalIntent = { version: 1, userId: 'user', key: 'key', amountCents: 6000, bankLast4: '1234' };
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());
function deferred() { let resolve!: (value: unknown) => void, reject!: (value: unknown) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }

it.each([
  { idempotency_key: 'other' }, { idempotency_key: null }, { amount: 61, total_amount: 61 },
  { method: 'EFECTIVO', payment_method: 'EFECTIVO' }, { bank_account_last4: '9999' }, { bank_account_last4: null },
])('does not confirm a different request payload (%j)', async invalid => {
  jest.mocked(api.post).mockResolvedValue({ ...row, ...invalid });
  await expect(payoutService.requestPayout(request)).rejects.toThrow();
});
it.each([{ requested_by_user_id: 'other' }, { requested_by_user_id: null }, { idempotency_key: 'wrong' }, { amount: 50, total_amount: 50 }, { method: 'EFECTIVO', payment_method: 'EFECTIVO' }, { bank_account_last4: '9876' }])('does not recover a response inconsistent with the persisted intent (%j)', change => {
  expect(() => confirmWithdrawal({ ...row, ...change }, intent)).toThrow();
});
it.each(['PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO'])('recovers the actual server state %s without interpreting it as money sent', status => {
  expect(confirmWithdrawal({ ...row, status }, intent).status).toBe(status);
});
it('compares aliases, preserves zero snapshots and does not manufacture dates/counts', () => {
  const result = normalizePayout({ ...row, amount: '60.00', balance_before: 0, balance_after: '0.00', requested_at: 'bad', updated_at: null });
  expect(result).toMatchObject({ amount: 60, balance_before: 0, balance_after: 0, requested_at: null, created_at: null, updated_at: null });
  expect(result.orders_count).toBeUndefined(); expect(result.period).toBeNull();
  expect(payoutDateLabel(result.requested_at)).toBe('Fecha no informada');
});
it('retains each reported audit date instead of replacing them with the request date', () => {
  const result = normalizePayout({ ...row, requested_at: '2026-10-01', created_at: '2026-10-02', updated_at: '2026-10-03' });
  expect(result).toMatchObject({ requested_at: '2026-10-01', created_at: '2026-10-02', updated_at: '2026-10-03' });
});
it.each([null, [], false, {}, { ...row, amount: 60, total_amount: 61 }, { ...row, payment_method: 'EFECTIVO' }, { ...row, method: undefined, payment_method: undefined }, { ...row, orders_count: -1 }, { ...row, bank_account_last4: '1' }])('rejects incomplete and contradictory records (%j)', raw => {
  expect(() => normalizePayout(raw)).toThrow();
});
it.each([true, false, '', ' ', null, undefined, '10.001', NaN, Infinity, '1e2', -10])('rejects malformed or negative unsigned amounts (%j)', value => {
  expect(() => payoutCents(value)).toThrow();
});
it('keeps amounts in cents and accepts a large actual balance without applying the per-request cap', () => {
  expect(payoutCents(0)).toBe(0); expect(payoutCents('10.01')).toBe(1001);
  expect(normalizePayoutBalance({ available: 1000000000, pending: 0 }).available).toBe(1000000000);
});
it.each([{ degraded: true, available: 0, pending: 0 }, { available: null, pending: 0 }, { available: false, pending: 0 }, { available: 0 }, { available: -1, pending: 0 }, { available: 0, pending: 0, currency: 'INVALID' }])('does not report an unavailable or malformed balance as zero (%j)', raw => {
  expect(() => normalizePayoutBalance(raw)).toThrow();
});
it('accepts measured zero balance and preserves its reported currency', async () => {
  jest.mocked(api.get).mockResolvedValue({ available: 0, pending: 0, processed: 0, total_earned: 0, currency: 'COP' });
  expect(await payoutService.getAvailableBalance()).toEqual({ available: 0, pending: 0, processed: 0, total_earned: 0, currency: 'COP' });
  expect(payoutAmountLabel(10, 'COP')).toContain('COP');
  expect(payoutAmountLabel(10)).toContain('moneda no informada');
  expect(payoutAmountLabel(10)).not.toContain('USD');
});
it.each([{ idempotency_key: undefined }, { idempotency_key: ' ' }, { idempotency_key: 'x'.repeat(101) }, { method: 'UNKNOWN' }, { amount: 9.99 }, { amount: 100000000 }, { amount: 10.001 }, { bank_account_last4: '12' }, { bank_account_id: 'ignored-by-backend' }])('rejects invalid requests before POST (%j)', async invalid => {
  await expect(payoutService.requestPayout({ ...request, ...invalid } as never)).rejects.toThrow();
  expect(api.post).not.toHaveBeenCalled();
});
it('posts the caller-retained key and validates the echo without mutating input', async () => {
  jest.mocked(api.post).mockResolvedValue(row);
  const frozen = Object.freeze({ ...request });
  expect((await payoutService.requestPayout(frozen)).id).toBe(row.id);
  expect(api.post).toHaveBeenCalledWith('/payouts/request', frozen);
});
it('does not accept a different idempotency key from request-status', async () => {
  jest.mocked(api.get).mockResolvedValue({ ...row, idempotency_key: 'other' });
  await expect(payoutService.findRequestByKey('key')).rejects.toThrow(/otra solicitud/);
});
it.each(['getById', 'approve', 'reject'])('checks the requested payout identity on %s', async method => {
  const value = { ...row, id: 'wrong', status: method === 'approve' ? 'EN_PROCESO' : method === 'reject' ? 'RECHAZADO' : 'PENDIENTE', rejection_reason: 'reason' };
  jest.mocked(api.get).mockResolvedValue(value); jest.mocked(api.patch).mockResolvedValue(value);
  await expect(method === 'getById' ? payoutService.getById('p') : method === 'approve' ? payoutService.approve('p') : payoutService.reject('p', 'reason')).rejects.toThrow();
});
it.each(['approve', 'reject'])('requires the transition to be confirmed on %s', async method => {
  jest.mocked(api.patch).mockResolvedValue(row);
  await expect(method === 'approve' ? payoutService.approve('p') : payoutService.reject('p', 'reason')).rejects.toThrow();
});
it('encodes path IDs before sending a detail query', async () => {
  jest.mocked(api.get).mockResolvedValue({ ...row, id: 'a/b' });
  await payoutService.getById('a/b'); expect(api.get).toHaveBeenCalledWith('/payouts/a%2Fb');
});
it.each([{}, [row, row], [{ ...row, rider_id: 'wrong' }]])('rejects malformed/duplicate/out-of-filter list pages (%j)', async raw => {
  jest.mocked(api.get).mockResolvedValue(raw);
  await expect(payoutService.getAll({ rider_id: 'r' })).rejects.toThrow();
});
it('rejects a silently ignored status filter and unsupported historical query states', async () => {
  jest.mocked(api.get).mockResolvedValue([row]);
  await expect(payoutService.getAll({ status: 'COMPLETADO' })).rejects.toThrow();
  jest.mocked(api.get).mockClear();
  await expect(payoutService.getAll({ status: 'PROCESADO' })).rejects.toThrow();
  expect(api.get).not.toHaveBeenCalled();
});
it('requires each audit row to belong to the requested payout and preserve zero balances', () => {
  const audit = { id: 'h', payout_id: 'p', old_status: null, new_status: 'PENDIENTE', balance_before: 0, balance_after: 0 };
  expect(normalizePayoutHistory([audit], 'p')).toMatchObject([{ balance_before: 0, balance_after: 0, created_at: null }]);
  expect(() => normalizePayoutHistory([audit], 'other')).toThrow();
  expect(() => normalizePayoutHistory([audit, audit], 'p')).toThrow();
  expect(() => normalizePayoutHistory([{ ...audit, new_status: 'PAID' }], 'p')).toThrow();
});
const actions = [
  ['list', () => payoutService.getAll(), [row]],
  ['balance', () => payoutService.getAvailableBalance(), { available: 0, pending: 0 }],
  ['detail', () => payoutService.getById('p'), row],
  ['history', () => payoutService.getHistory('p'), []],
  ['lookup', () => payoutService.findRequestByKey('key'), row],
  ['request', () => payoutService.requestPayout(request), row],
  ['approve', () => payoutService.approve('p'), { ...row, status: 'EN_PROCESO' }],
  ['reject', () => payoutService.reject('p', 'reason'), { ...row, status: 'RECHAZADO', rejection_reason: 'reason' }],
] as const;
it.each(actions)('sends nothing without a session: %s', async (_name, action) => {
  clearStoredTokens(); await expect(action()).rejects.toBeInstanceOf(SessionChangedError);
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled(); expect(api.patch).not.toHaveBeenCalled();
});
it.each(actions)('rejects a successful late response from a previous session: %s', async (_name, action, value) => {
  const old = deferred(); jest.mocked(api.get).mockReturnValue(old.promise); jest.mocked(api.post).mockReturnValue(old.promise); jest.mocked(api.patch).mockReturnValue(old.promise);
  const result = action().catch(e => e); storeTokens({ access_token: 'b', refresh_token: 'rb' }); old.resolve(value);
  expect(await result).toBeInstanceOf(SessionChangedError);
});
it('does not convert a late 404 from the previous session into permission to retry', async () => {
  const old = deferred(); jest.mocked(api.get).mockReturnValue(old.promise);
  const result = payoutService.findRequestByKey('key').catch(e => e);
  storeTokens({ access_token: 'b', refresh_token: 'rb' }); old.reject({ response: { status: 404 } });
  expect(await result).toBeInstanceOf(SessionChangedError);
});
it.each(['0', ' ', '2026-02-30', 'not-a-date', 0, undefined])('keeps malformed or absent dates unknown (%j)', created_at => {
  expect(normalizePayout({ ...row, created_at }).created_at).toBeNull();
});
it('does not label missing account balances as zero or invent USD', () => {
  expect(payoutAmountLabel(null)).toBe('Monto no informado');
  expect(payoutAmountLabel(undefined)).toBe('Monto no informado');
  expect(payoutAmountLabel(0)).toContain('0,00');
});
it('rejects an oversized server page rather than presenting it as the requested batch', async () => {
  jest.mocked(api.get).mockResolvedValue([row, { ...row, id: 'second' }]);
  await expect(payoutService.getAll({ limit: 1 })).rejects.toThrow(/página/);
});
