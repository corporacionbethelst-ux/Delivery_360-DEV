import { api } from '@/lib/api';
import { orderServiceWithCache as orders } from '@/services/order-cache.service';
import { cacheUtils } from '@/lib/private-cache';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
const a = { access_token: 'a-access', refresh_token: 'a-refresh' },
  b = { access_token: 'b-access', refresh_token: 'b-refresh' };
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(a);
  cacheUtils.clear();
  jest.clearAllMocks();
});
afterEach(() => clearStoredTokens());
it('uses one configured API prefix and reuses a list only within its session', async () => {
  jest.mocked(api.get).mockResolvedValue([{ id: 'a' }]);
  expect(await orders.getAllOrders({ skip: 0, limit: 10 })).toEqual([{ id: 'a' }]);
  await orders.getAllOrders({ skip: 0, limit: 10 });
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(api.get).toHaveBeenCalledWith('/orders?skip=0&limit=10');
  storeTokens(b);
  await orders.getAllOrders({ skip: 0, limit: 10 });
  expect(api.get).toHaveBeenCalledTimes(2);
});
it('a delayed old list cannot enter the new account cache', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.get).mockReturnValueOnce(
    new Promise((yes) => {
      resolve = yes;
    })
  );
  const work = orders.getAllOrders().catch((error) => error);
  storeTokens(b);
  resolve([{ id: 'old-a' }]);
  expect(await work).toBeInstanceOf(SessionChangedError);
  expect(cacheUtils.get('orders:list:{}')).toBeNull();
});
it('a delayed detail cannot be returned or cached after logout', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.get).mockReturnValueOnce(
    new Promise((yes) => {
      resolve = yes;
    })
  );
  const work = orders.getOrderById('a').catch((error) => error);
  clearStoredTokens();
  resolve({ id: 'old-a' });
  expect(await work).toBeInstanceOf(SessionChangedError);
  expect(cacheUtils.get('order:a')).toBeNull();
});
it('encodes detail IDs and caches the accepted current-session object', async () => {
  jest.mocked(api.get).mockResolvedValueOnce({ id: 'a/b' });
  await orders.getOrderById('a/b');
  await orders.getOrderById('a/b');
  expect(api.get).toHaveBeenCalledWith('/orders/a%2Fb');
  expect(api.get).toHaveBeenCalledTimes(1);
});
it.each(['updateOrder', 'cancelOrder', 'assignRider'] as const)(
  '%s uses PATCH and invalidates the current account caches',
  async (method) => {
    cacheUtils.set('order:o', { id: 'o' }, 60);
    cacheUtils.set('orders:list:{}', [{ id: 'o' }], 60);
    jest.mocked(api.patch).mockResolvedValue({ id: 'o' });
    if (method === 'updateOrder') await orders.updateOrder('o', {});
    if (method === 'cancelOrder') await orders.cancelOrder('o', 'reason');
    if (method === 'assignRider') await orders.assignRider('o', 'r');
    expect(api.patch).toHaveBeenCalledTimes(1);
    expect(String(jest.mocked(api.patch).mock.calls[0][0])).toMatch(/^\/orders\/o/);
    expect(cacheUtils.get('order:o')).toBeNull();
    expect(cacheUtils.get('orders:list:{}')).toBeNull();
  }
);
it('creation invalidates lists and an explicit refresh bypasses the old cached list', async () => {
  cacheUtils.set('orders:list:{}', [{ id: 'old' }], 60);
  jest.mocked(api.post).mockResolvedValueOnce({ id: 'new' });
  await orders.createOrder({});
  expect(api.post).toHaveBeenCalledWith('/orders', {});
  expect(cacheUtils.get('orders:list:{}')).toBeNull();
  cacheUtils.set('orders:list:{}', [{ id: 'cached' }], 60);
  jest.mocked(api.get).mockResolvedValueOnce([{ id: 'fresh' }]);
  expect(await orders.refreshOrdersCache()).toEqual([{ id: 'fresh' }]);
});
it('no request or cache read is offered to an anonymous caller', async () => {
  clearStoredTokens();
  await expect(orders.getOrderById('o')).rejects.toBeInstanceOf(SessionChangedError);
  expect(api.get).not.toHaveBeenCalled();
});
