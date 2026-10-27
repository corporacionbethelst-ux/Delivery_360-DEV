import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
let loaded: typeof import('@/lib/api');
let requests: InternalAxiosRequestConfig[];
beforeEach(() => {
  localStorage.clear();
  requests = [];
  const old = process.env.NEXT_PUBLIC_API_URL;
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000/api/v1';
  jest.isolateModules(() => {
    loaded = require('@/lib/api');
  });
  process.env.NEXT_PUBLIC_API_URL = old;
  loaded.storeTokens({ access_token: 'origin-test-access', refresh_token: 'origin-test-refresh' });
  loaded.default.defaults.adapter = async (config) => {
    requests.push(config);
    return {
      config,
      status: 200,
      statusText: 'OK',
      data: { ok: true },
      headers: {},
    } as AxiosResponse;
  };
});
afterEach(() => loaded.clearStoredTokens());
it.each(['/users/me', 'http://localhost:8000/api/v1/users/me'])(
  'allows a route inside the configured API: %s',
  async (url) => {
    await expect(loaded.api.get(url)).resolves.toEqual({ ok: true });
    expect(requests[0].headers.get('Authorization')).toBe('Bearer origin-test-access');
  }
);
it.each([
  'http://localhost:8000/api/v1-unrelated/private',
  'http://localhost:8000/private',
  '../../outside',
  'http://localhost:8000/api/v1/%2e%2e/private',
])('blocks same-origin paths outside the API prefix: %s', async (url) => {
  await expect(loaded.api.get(url)).rejects.toThrow('API configurada');
  expect(requests).toHaveLength(0);
});
it('cannot override baseURL to forward credentials to another origin', async () => {
  await expect(
    loaded.api.get('/users/me', { baseURL: 'https://unrelated.example/api/v1' })
  ).rejects.toThrow('API configurada');
  expect(requests).toHaveLength(0);
});
it('recognizes query strings and trailing slashes on public authentication paths', async () => {
  await loaded.api.post('/auth/login/?source=test', { test: true });
  expect(requests[0].headers.get('Authorization')).toBeUndefined();
});
