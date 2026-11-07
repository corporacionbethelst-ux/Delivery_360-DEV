import { api } from '@/lib/api';
import { payoutService } from '@/services/payout.service';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
const cursor = `c50.${'a'.repeat(64)}`, next = `c100.${'b'.repeat(64)}`;
const row = { id: 'p', rider_id: 'r', amount: 10, status: 'PENDIENTE', method: 'EFECTIVO' };
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it('uses a bounded envelope without offset, and returns the opaque continuation unchanged', async () => {
  get.mockResolvedValue({ items: [row], next_cursor: next });
  const result = await payoutService.getPage({ rider_id: ' r ', status: 'PENDIENTE', limit: 1, cursor });
  expect(get).toHaveBeenCalledWith(`/payouts/page?rider_id=r&status=PENDIENTE&limit=1&cursor=${cursor}`);
  expect(result).toMatchObject({ items: [row], next_cursor: next });
});
it.each([{ items: [] }, { items: [row] }])('accepts a terminal page with an explicit null continuation (%j)', async ({ items }) => {
  get.mockResolvedValue({ items, next_cursor: null });
  expect((await payoutService.getPage()).next_cursor).toBeNull();
  expect(get).toHaveBeenCalledWith('/payouts/page?limit=50');
});
it.each([
  null, [], { items: [] }, { items: [], next_cursor: false },
  { items: [], next_cursor: '' }, { items: [], next_cursor: 'anything' },
  { items: [], next_cursor: next }, { items: [row], next_cursor: cursor },
  { items: [row, row], next_cursor: null }, { items: [{ ...row, rider_id: 'other' }], next_cursor: null },
  { items: [{ ...row, status: 'COMPLETADO' }], next_cursor: null },
  { items: [{ ...row, amount: false }], next_cursor: null },
])('rejects malformed, duplicated or contradictory pages (%j)', async response => {
  get.mockResolvedValue(response);
  await expect(payoutService.getPage({ rider_id: 'r', status: 'PENDIENTE', limit: 1, cursor })).rejects.toThrow();
});
it.each(['', 'not-a-cursor', `x.${'z'.repeat(64)}`, `${'x'.repeat(2048)}.${'a'.repeat(64)}`, false])('rejects malformed query cursors before HTTP (%j)', async value => {
  await expect(payoutService.getPage({ cursor: value } as never)).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it('rejects offset instead of silently ignoring it', async () => {
  await expect(payoutService.getPage({ offset: 50 } as never)).rejects.toThrow(/offset/);
  expect(get).not.toHaveBeenCalled();
});
it('rejects historical statuses instead of sending ignored filters', async () => {
  await expect(payoutService.getPage({ status: 'CANCELADO' })).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
it('validates the copied query rather than a mutated caller object', async () => {
  let resolve!: (value: unknown) => void;
  get.mockReturnValue(new Promise(done => { resolve = done; }));
  const query = { limit: 1, status: 'PENDIENTE' as const, cursor };
  const pending = payoutService.getPage(query);
  Object.assign(query, { status: 'COMPLETADO', limit: 200, cursor: next });
  resolve({ items: [row], next_cursor: next });
  expect((await pending).items[0].status).toBe('PENDIENTE');
  expect(get).toHaveBeenCalledWith(`/payouts/page?status=PENDIENTE&limit=1&cursor=${cursor}`);
});
it.each(['success', 'error'])('retires a page completion after credentials change (%s)', async mode => {
  let resolve!: (value: unknown) => void, reject!: (value: Error) => void;
  get.mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
  const pending = payoutService.getPage();
  storeTokens({ access_token: 'b', refresh_token: 'rb' });
  if (mode === 'success') resolve({ items: [row], next_cursor: null }); else reject(new Error('old request'));
  await expect(pending).rejects.toBeInstanceOf(SessionChangedError);
});
it('does not request a fallback page after a rejected continuation', async () => {
  get.mockRejectedValue(Object.assign(new Error('invalid cursor'), { response: { status: 400 } }));
  await expect(payoutService.getPage({ cursor })).rejects.toThrow('invalid cursor');
  expect(get).toHaveBeenCalledTimes(1);
  expect(get).toHaveBeenCalledWith(`/payouts/page?limit=50&cursor=${cursor}`);
});
