import React from 'react';
import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import axios, {
  AxiosAdapter,
  AxiosError,
  AxiosHeaders,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import client, { api, getStoredTokens, clearStoredTokens, storeTokens } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { SessionGate } from '@/components/layout/SessionGate';
import { User } from '@/types/user';
const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: mockReplace }) }));
const profile: User = {
  id: 'owner-a',
  email: 'owner-a@example.test',
  first_name: 'Owner',
  last_name: 'A',
  role: 'OPERADOR',
  is_active: true,
  created_at: '',
  updated_at: '',
};
const old = { access_token: 'access-a', refresh_token: 'refresh-a' },
  rotated = { access_token: 'rotated-a', refresh_token: 'refresh-rotated-a' };
const other = { access_token: 'access-b', refresh_token: 'refresh-b' };
const originalAdapter = client.defaults.adapter,
  originalRefresh = axios.defaults.adapter;
let calls: InternalAxiosRequestConfig[], refreshCalls: InternalAxiosRequestConfig[];
let responder: AxiosAdapter, refresher: AxiosAdapter;
const success = (config: InternalAxiosRequestConfig, data: unknown): AxiosResponse => ({
  config,
  data,
  status: 200,
  statusText: 'OK',
  headers: new AxiosHeaders(),
});
const failure = (config: InternalAxiosRequestConfig, status = 401) =>
  new AxiosError('private URL and body', AxiosError.ERR_BAD_REQUEST, config, undefined, {
    config,
    data: { detail: 'Credenciales inválidas' },
    status,
    statusText: 'Failure',
    headers: new AxiosHeaders(),
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const flush = async () => {
  for (let i = 0; i < 25; ++i) await Promise.resolve();
};
const login = () =>
  useAuthStore.getState().login({ email: profile.email, password: 'test-only-password' });
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  useAuthStore.getState().forceLogout();
  localStorage.setItem('app_version', '1.2.1');
  mockReplace.mockClear();
  calls = [];
  refreshCalls = [];
  responder = async (config) =>
    success(
      config,
      config.url === '/auth/login' ? old : config.url === '/auth/me' ? profile : { ok: true }
    );
  refresher = async (config) => success(config, rotated);
  client.defaults.adapter = async (config) => {
    calls.push(config);
    return responder(config);
  };
  axios.defaults.adapter = async (config) => {
    refreshCalls.push(config);
    return refresher(config);
  };
});
afterEach(async () => {
  cleanup();
  jest.restoreAllMocks();
  useAuthStore.getState().forceLogout();
  await flush();
  client.defaults.adapter = originalAdapter;
  axios.defaults.adapter = originalRefresh;
});
it('uses OAuth form login, verifies a profile, and publishes only the live bearer in its cookie', async () => {
  responder = async (config) => {
    if (config.url === '/auth/login') return success(config, old);
    if (config.headers.get('Authorization') === 'Bearer access-a') throw failure(config);
    return success(config, profile);
  };
  await login();
  expect(refreshCalls).toHaveLength(1);
  expect(useAuthStore.getState().user?.id).toBe(profile.id);
  expect(document.cookie).toContain('auth-token=rotated-a');
  expect(getStoredTokens().accessToken).toBe('rotated-a');
  expect(String(calls[0].data)).toContain('username=owner-a%40example.test');
});
it('a delayed profile from login A cannot overwrite an already completed login B', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = async (config) => {
    if (config.url === '/auth/login')
      return success(
        config,
        calls.filter((c) => c.url === '/auth/login').length === 1 ? old : other
      );
    if (config.headers.get('Authorization') === 'Bearer access-a') return delayed.promise;
    return success(config, { ...profile, id: 'owner-b' });
  };
  const first = login().then(
    () => null,
    (error) => error
  );
  await flush();
  const firstProfile = calls.find((config) => config.url === '/auth/me')!;
  await login();
  delayed.resolve(success(firstProfile, profile));
  await first;
  expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: true, user: { id: 'owner-b' } });
  expect(getStoredTokens().accessToken).toBe(other.access_token);
});
it('an old login request failing after another token writer succeeds cannot clear its credentials', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const first = login().then(
    () => null,
    (error) => error
  );
  storeTokens(other);
  delayed.resolve(success(calls[0], old));
  await first;
  expect(getStoredTokens().accessToken).toBe(other.access_token);
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
});
it('terminal refresh expiry immediately unmounts protected content and clears cookies', async () => {
  await login();
  render(
    <SessionGate>
      <div>Verified private content</div>
    </SessionGate>
  );
  expect(await screen.findByText('Verified private content')).toBeInTheDocument();
  responder = async (config) => {
    throw failure(config);
  };
  refresher = async (config) => {
    throw failure(config, 401);
  };
  await act(async () => {
    await api.get('/private').catch(() => {});
  });
  expect(screen.queryByText('Verified private content')).toBeNull();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  expect(getStoredTokens().accessToken).toBeNull();
  expect(document.cookie).not.toContain('auth-token=');
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
});
it('force logout during renewal cannot be undone by the late adapter result', async () => {
  await login();
  const delayed = deferred<AxiosResponse>();
  responder = async (config) => {
    throw failure(config);
  };
  refresher = () => delayed.promise;
  const work = api.get('/private').then(
    () => null,
    (error) => error
  );
  await flush();
  useAuthStore.getState().forceLogout();
  await work;
  delayed.resolve(success(refreshCalls[0], rotated));
  await flush();
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
  expect(getStoredTokens().accessToken).toBeNull();
});
it('profile route fallback occurs only for 404 within the same verified credential generation', async () => {
  responder = async (config) => {
    if (config.url === '/auth/login') return success(config, old);
    if (config.url === '/auth/me') throw failure(config, 404);
    return success(config, profile);
  };
  await login();
  expect(calls.map((config) => config.url)).toEqual(['/auth/login', '/auth/me', '/users/me']);
  expect(useAuthStore.getState().isAuthenticated).toBe(true);
});
it('a profile server error does not issue an unrelated fallback request', async () => {
  responder = async (config) => {
    if (config.url === '/auth/login') return success(config, old);
    throw failure(config, 503);
  };
  await expect(login()).rejects.toThrow();
  expect(calls.map((config) => config.url)).toEqual(['/auth/login', '/auth/me']);
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
});
it('a transient renewal failure during checkAuth keeps credentials without granting verified content', async () => {
  await login();
  responder = async (config) => {
    throw failure(config);
  };
  refresher = async (config) => {
    throw failure(config, 503);
  };
  await useAuthStore.getState().checkAuth();
  expect(getStoredTokens().accessToken).toBe(old.access_token);
  expect(useAuthStore.getState()).toMatchObject({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  });
});
it('forceLogout remains immediate when browser storage reads, writes and removals are denied', async () => {
  await login();
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('private path');
  });
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('private path');
  });
  jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('private path');
  });
  expect(() => useAuthStore.getState().forceLogout()).not.toThrow();
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
  jest.restoreAllMocks();
  expect(getStoredTokens().accessToken).toBeNull();
  expect(document.cookie).not.toContain('auth-token=');
});
it('a partial credential write cannot authenticate the store or leave a usable pair', async () => {
  const set = Storage.prototype.setItem;
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
    this: Storage,
    key: string,
    value: string
  ) {
    if (key === 'refresh_token') throw new Error('private path');
    set.call(this, key, value);
  });
  await expect(login()).rejects.toThrow('No se pudieron guardar');
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  expect(getStoredTokens().accessToken).toBeNull();
});

it('a credential write failure during renewal removes verified content and closes locally', async () => {
  await login();
  render(
    <SessionGate>
      <div>Verified private content</div>
    </SessionGate>
  );
  await screen.findByText('Verified private content');
  const set = Storage.prototype.setItem;
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
    this: Storage,
    key: string,
    value: string
  ) {
    if (key === 'refresh_token') throw new Error('private disk diagnostic');
    set.call(this, key, value);
  });
  responder = async (config) => {
    throw failure(config);
  };
  await act(async () => {
    await api.get('/private').catch(() => {});
  });
  expect(screen.queryByText('Verified private content')).toBeNull();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  expect(getStoredTokens().accessToken).toBeNull();
});
it('revalidation from the previous generation cannot delete a replacement pair', async () => {
  await login();
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const check = useAuthStore.getState().checkAuth();
  const request = calls.at(-1)!;
  storeTokens(other);
  delayed.resolve(success(request, profile));
  await check;
  expect(getStoredTokens().accessToken).toBe(other.access_token);
  expect(useAuthStore.getState()).toMatchObject({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  });
});
