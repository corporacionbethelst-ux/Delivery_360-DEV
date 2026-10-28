import axios, { AxiosError, AxiosHeaders, InternalAxiosRequestConfig } from 'axios';
import client, { getStoredTokens } from '@/lib/api';
import { storeTokens, clearStoredTokens, SessionChangedError } from '@/lib/auth-session';
import { useAuthStore } from '@/stores/authStore';
import { useOrdersStore } from '@/stores/ordersStore';
import { useFinancialStore } from '@/stores/financialStore';
import { cacheUtils } from '@/lib/private-cache';
const a = { access_token: 'a-access', refresh_token: 'a-refresh' },
  b = { access_token: 'b-access', refresh_token: 'b-refresh' };
const oldAdapter = client.defaults.adapter,
  oldRefresh = axios.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({
  config,
  data,
  status: 200,
  statusText: 'OK',
  headers: new AxiosHeaders(),
});
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(a);
  cacheUtils.clear();
});
afterEach(() => {
  clearStoredTokens();
  client.defaults.adapter = oldAdapter;
  axios.defaults.adapter = oldRefresh;
});
it('fences the continuation gap after the HTTP interceptor has accepted a successful response', async () => {
  client.defaults.adapter = async (config) =>
    reply(config, { items: [{ id: 'private-a' }], total: 1 });
  const interceptor = client.interceptors.response.use((response) => {
    storeTokens(b);
    useOrdersStore.getState().setOrders([{ id: 'private-b' } as never]);
    return response;
  });
  try {
    await expect(useOrdersStore.getState().fetchOrders()).rejects.toBeInstanceOf(
      SessionChangedError
    );
    expect(useOrdersStore.getState().orders.map((o) => o.id)).toEqual(['private-b']);
    expect(getStoredTokens().accessToken).toBe('b-access');
  } finally {
    client.interceptors.response.eject(interceptor);
  }
});
it('logout through the real authStore clears received business data and query cache', async () => {
  client.defaults.adapter = async (config) =>
    reply(
      config,
      config.url?.startsWith('/orders') ? { items: [{ id: 'a' }], total: 1 } : { totalRevenue: 99 }
    );
  await useOrdersStore.getState().fetchOrders();
  await useFinancialStore.getState().fetchSummary();
  cacheUtils.set('private', 'a', 60);
  useAuthStore.getState().forceLogout();
  expect(useOrdersStore.getState().orders).toEqual([]);
  expect(useFinancialStore.getState().summary).toBeNull();
  expect(cacheUtils.get('private')).toBeNull();
});
it('an ordinary refresh keeps the same account stores and cache while completing a read', async () => {
  const summary = { totalRevenue: 9 };
  useFinancialStore.setState({ summary: summary as never });
  cacheUtils.set('stable', 'same-owner', 60);
  client.defaults.adapter = async (config) => {
    if (config.headers.get('Authorization') === 'Bearer a-access')
      throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, {
        ...reply(config, {}),
        status: 401,
      });
    return reply(config, { items: [{ id: 'active' }], total: 1 });
  };
  axios.defaults.adapter = async (config) =>
    reply(config, { access_token: 'rotated-a', refresh_token: 'rotated-refresh-a' });
  await useOrdersStore.getState().fetchOrders();
  expect(useOrdersStore.getState().orders[0].id).toBe('active');
  expect(useFinancialStore.getState().summary).toBe(summary);
  expect(cacheUtils.get('stable')).toBe('same-owner');
});
