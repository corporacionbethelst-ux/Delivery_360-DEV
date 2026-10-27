import axios, {
  AxiosAdapter,
  AxiosError,
  AxiosHeaders,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import client, { api, authApi, clearStoredTokens, getStoredTokens, storeTokens } from '@/lib/api';
import {
  captureAuthSession,
  SessionChangedError,
  SessionExpiredError,
  RefreshUnavailableError,
} from '@/lib/auth-session';
const old = { access_token: 'access-a', refresh_token: 'refresh-a' };
const rotated = { access_token: 'rotated-a', refresh_token: 'rotated-refresh-a' };
const other = { access_token: 'access-b', refresh_token: 'refresh-b' };
const savedAdapter = client.defaults.adapter,
  savedRefreshAdapter = axios.defaults.adapter;
let calls: InternalAxiosRequestConfig[], refreshCalls: InternalAxiosRequestConfig[];
let responder: AxiosAdapter, refresher: AxiosAdapter;
const success = (
  config: InternalAxiosRequestConfig,
  data: unknown = { ok: true }
): AxiosResponse => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
function failure(config: InternalAxiosRequestConfig, status = 401): AxiosError {
  return new AxiosError(
    'private transport body and URL',
    AxiosError.ERR_BAD_REQUEST,
    config,
    undefined,
    {
      config,
      data: { detail: 'private diagnostic' },
      status,
      statusText: 'Failure',
      headers: new AxiosHeaders(),
    }
  );
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const flush = async () => {
  for (let i = 0; i < 15; ++i) await Promise.resolve();
};
const outcome = <T>(promise: Promise<T>) =>
  promise.then(
    (value) => ({ value, error: undefined }),
    (error) => ({ error, value: undefined })
  );
const auth = (config: InternalAxiosRequestConfig) => config.headers.get('Authorization');
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(old);
  calls = [];
  refreshCalls = [];
  responder = async (config) => {
    if (auth(config) === 'Bearer access-a') throw failure(config);
    return success(config);
  };
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
  clearStoredTokens();
  await flush();
  client.defaults.adapter = savedAdapter;
  axios.defaults.adapter = savedRefreshAdapter;
  jest.restoreAllMocks();
  jest.useRealTimers();
});

it('shares one real Axios refresh pipeline across simultaneous GET and POST failures', async () => {
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const requests = [api.get('/orders'), api.post('/orders', { value: 1 }), api.get('/alerts')];
  await flush();
  expect(refreshCalls).toHaveLength(1);
  expect(calls).toHaveLength(3);
  delayed.resolve(success(refreshCalls[0], rotated));
  await expect(Promise.all(requests)).resolves.toEqual([{ ok: true }, { ok: true }, { ok: true }]);
  expect(calls).toHaveLength(6);
  expect(calls.slice(3).every((config) => auth(config) === 'Bearer rotated-a')).toBe(true);
  expect(JSON.parse(String(refreshCalls[0].data))).toEqual({ refresh_token: 'refresh-a' });
  expect(refreshCalls[0].timeout).toBe(15000);
  expect(getStoredTokens().refreshToken).toBe(rotated.refresh_token);
});
it('captures generation synchronously before a request can yield to another login', async () => {
  const first = outcome(api.get('/orders'));
  storeTokens(other);
  const result = await first;
  expect(result.error).toBeInstanceOf(SessionChangedError);
  expect(calls).toHaveLength(1);
  expect(auth(calls[0])).toBe('Bearer access-a');
  expect(refreshCalls).toHaveLength(0);
});
it('rejects all refresh waiters immediately on logout even if an adapter ignores abort', async () => {
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const first = outcome(api.get('/orders')),
    second = outcome(api.post('/orders', { value: 1 }));
  await flush();
  clearStoredTokens();
  expect((await first).error).toBeInstanceOf(SessionChangedError);
  expect((await second).error).toBeInstanceOf(SessionChangedError);
  expect(refreshCalls[0].signal?.aborted).toBe(true);
  delayed.resolve(success(refreshCalls[0], rotated));
  await flush();
  expect(getStoredTokens().accessToken).toBeNull();
  expect(calls).toHaveLength(2);
});
it.each(['success', 'failure'])(
  'a late old refresh %s cannot modify or clear owner B',
  async (ending) => {
    const delayed = deferred<AxiosResponse>();
    refresher = () => delayed.promise;
    const first = outcome(api.get('/orders'));
    await flush();
    storeTokens(other);
    expect((await first).error).toBeInstanceOf(SessionChangedError);
    if (ending === 'success') delayed.resolve(success(refreshCalls[0], rotated));
    else delayed.reject(failure(refreshCalls[0], 401));
    await flush();
    expect(getStoredTokens().accessToken).toBe(other.access_token);
    expect(calls).toHaveLength(1);
  }
);
it('an old finally cannot remove a new session refresh in progress', async () => {
  const first = deferred<AxiosResponse>(),
    next = deferred<AxiosResponse>();
  refresher = (config) => (refreshCalls.length === 1 ? first.promise : next.promise);
  const a = outcome(api.get('/a'));
  await flush();
  storeTokens(other);
  await a;
  responder = async (config) => {
    if (auth(config) === 'Bearer access-b') throw failure(config);
    return success(config);
  };
  const b = api.get('/b');
  await flush();
  first.resolve(success(refreshCalls[0], rotated));
  await flush();
  const c = api.get('/c');
  await flush();
  expect(refreshCalls).toHaveLength(2);
  next.resolve(
    success(refreshCalls[1], { access_token: 'rotated-b', refresh_token: 'refresh-b-next' })
  );
  await Promise.all([b, c]);
  expect(getStoredTokens().accessToken).toBe('rotated-b');
});
it('a delayed 401 from the previous access token reuses this session rotation', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = async (config) => {
    if (config.url === '/slow' && auth(config) === 'Bearer access-a') return delayed.promise;
    if (auth(config) === 'Bearer access-a') throw failure(config);
    return success(config);
  };
  const slow = api.get('/slow');
  await api.get('/fast');
  delayed.reject(failure(calls[0]));
  await slow;
  expect(refreshCalls).toHaveLength(1);
  expect(getStoredTokens().accessToken).toBe('rotated-a');
});
it('fences successful old responses as well as old 401 responses', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const first = outcome(api.get('/private'));
  storeTokens(other);
  delayed.resolve(success(calls[0], { private: 'owner-a' }));
  expect((await first).error).toBeInstanceOf(SessionChangedError);
  expect(refreshCalls).toHaveLength(0);
});
it('only retries once per queued request even if the renewed bearer is rejected', async () => {
  responder = async (config) => {
    throw failure(config);
  };
  const first = outcome(api.get('/a')),
    second = outcome(api.get('/b'));
  const results = await Promise.all([first, second]);
  expect(
    results.every(
      (result) =>
        result.error instanceof SessionExpiredError || result.error instanceof SessionChangedError
    )
  ).toBe(true);
  expect(refreshCalls).toHaveLength(1);
  expect(calls.length).toBeLessThanOrEqual(4);
  expect(getStoredTokens().accessToken).toBeNull();
});
it.each([401, 403])(
  'a terminal refresh HTTP %i clears only the current credentials and emits expiry once',
  async (status) => {
    const listener = jest.fn();
    window.addEventListener('delivery360-session-expired', listener);
    try {
      refresher = async (config) => {
        throw failure(config, status);
      };
      const results = await Promise.all([outcome(api.get('/a')), outcome(api.get('/b'))]);
      expect(results[0].error).toBeInstanceOf(SessionExpiredError);
      expect(getStoredTokens().accessToken).toBeNull();
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('delivery360-session-expired', listener);
    }
  }
);
it.each([429, 500, 503])(
  'refresh HTTP %i preserves credentials and allows a later fresh attempt',
  async (status) => {
    refresher = async (config) => {
      throw failure(config, status);
    };
    await expect(api.get('/a')).rejects.toBeInstanceOf(RefreshUnavailableError);
    expect(getStoredTokens().accessToken).toBe(old.access_token);
    refresher = async (config) => success(config, rotated);
    await expect(api.get('/b')).resolves.toEqual({ ok: true });
    expect(refreshCalls).toHaveLength(2);
  }
);
it('network errors are generic and do not log passwords, bearer or provider diagnostics', async () => {
  const errorLog = jest.spyOn(console, 'error').mockImplementation(() => {}),
    warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  refresher = async () => {
    throw new Error('secret-token and private URL');
  };
  await expect(api.get('/a')).rejects.toThrow('No se pudo renovar');
  expect(errorLog).not.toHaveBeenCalled();
  expect(warn).not.toHaveBeenCalled();
  expect(getStoredTokens().accessToken).toBe(old.access_token);
});
it.each([
  {},
  { access_token: 'only' },
  { access_token: 'bad token', refresh_token: 'valid' },
  { access_token: 'valid', refresh_token: '' },
])('rejects an invalid refresh response without overwriting credentials: %p', async (value) => {
  refresher = async (config) => success(config, value);
  await expect(api.get('/a')).rejects.toBeInstanceOf(RefreshUnavailableError);
  expect(getStoredTokens().accessToken).toBe(old.access_token);
  expect(calls).toHaveLength(1);
});
it('bounds a refresh even when its adapter ignores Axios timeout and cancellation', async () => {
  jest.useFakeTimers();
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const first = outcome(api.get('/a')),
    second = outcome(api.get('/b'));
  await flush();
  jest.advanceTimersByTime(15000);
  expect((await first).error).toBeInstanceOf(RefreshUnavailableError);
  expect((await second).error).toBeInstanceOf(RefreshUnavailableError);
  expect(refreshCalls[0].signal?.aborted).toBe(true);
  expect(getStoredTokens().accessToken).toBe(old.access_token);
  delayed.resolve(success(refreshCalls[0], rotated));
  await flush();
  expect(getStoredTokens().accessToken).toBe(old.access_token);
  expect(jest.getTimerCount()).toBe(0);
});
it('a cancelled caller stops waiting without cancelling renewal for the other caller', async () => {
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const controller = new AbortController();
  const first = outcome(api.get('/a', { signal: controller.signal })),
    second = api.get('/b');
  await flush();
  controller.abort();
  expect(axios.isCancel((await first).error)).toBe(true);
  expect(refreshCalls[0].signal?.aborted).toBe(false);
  delayed.resolve(success(refreshCalls[0], rotated));
  await second;
  expect(calls.filter((config) => config.url === '/a')).toHaveLength(1);
});
it('explicit refresh shares the automatic flight and refuses another account token', async () => {
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const request = api.get('/a');
  await flush();
  const explicit = authApi.refresh(old.refresh_token);
  await expect(authApi.refresh(other.refresh_token)).rejects.toBeInstanceOf(SessionChangedError);
  expect(refreshCalls).toHaveLength(1);
  delayed.resolve(success(refreshCalls[0], rotated));
  await request;
  await expect(explicit).resolves.toEqual(rotated);
});
it.each([
  '/auth/login',
  '/auth/register-rider',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/refresh',
])('never attaches bearer or auto-refreshes a public auth request %s', async (url) => {
  responder = async (config) => {
    throw failure(config);
  };
  await expect(api.post(url, { private: 'test-only' })).rejects.toBeInstanceOf(AxiosError);
  expect(refreshCalls).toHaveLength(0);
  expect(auth(calls[0])).toBeUndefined();
  expect(getStoredTokens().accessToken).toBe(old.access_token);
});
it('handles Axios errors without config and ordinary non-401 failures safely', async () => {
  responder = async () => {
    throw new AxiosError('transport', AxiosError.ERR_NETWORK);
  };
  await expect(api.get('/a')).rejects.toThrow('transport');
  expect(refreshCalls).toHaveLength(0);
  responder = async (config) => {
    throw failure(config, 403);
  };
  await expect(api.get('/a')).rejects.toBeInstanceOf(AxiosError);
  expect(getStoredTokens().accessToken).toBe(old.access_token);
});
it('missing refresh expires the current bearer without requesting a refresh', async () => {
  storeTokens({ access_token: 'access-a', refresh_token: '' });
  await expect(api.get('/a')).rejects.toBeInstanceOf(SessionExpiredError);
  expect(refreshCalls).toHaveLength(0);
  expect(getStoredTokens().accessToken).toBeNull();
});
it('does not redirect or enter refresh for an anonymous protected request', async () => {
  clearStoredTokens();
  responder = async (config) => {
    throw failure(config);
  };
  await expect(api.get('/a')).rejects.toBeInstanceOf(AxiosError);
  expect(refreshCalls).toHaveLength(0);
});
it.each(['https://unrelated.example/private', '//unrelated.example/private'])(
  'rejects forwarding credentials outside the configured API: %s',
  async (url) => {
    await expect(api.get(url)).rejects.toThrow('API configurada');
    expect(calls).toHaveLength(0);
    expect(refreshCalls).toHaveLength(0);
  }
);
it('never stores the refresh token in private request metadata', async () => {
  responder = async (config) => success(config);
  await api.get('/private');
  expect(JSON.stringify(calls[0])).not.toContain(old.refresh_token);
  expect(auth(calls[0])).toBe('Bearer access-a');
});
it('same-value logout/login cannot allow a pending request to rejoin the new session', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const request = outcome(api.get('/a'));
  clearStoredTokens();
  storeTokens(old);
  delayed.reject(failure(calls[0]));
  expect((await request).error).toBeInstanceOf(SessionChangedError);
  expect(refreshCalls).toHaveLength(0);
});
it('public login uses OAuth form data and cannot store its late response after logout', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const login = outcome(authApi.login('owner@example.test', 'test-only-password'));
  expect(String(calls[0].data)).toContain('username=owner%40example.test');
  expect(auth(calls[0])).toBeUndefined();
  clearStoredTokens();
  delayed.resolve(success(calls[0], other));
  expect((await login).error).toBeInstanceOf(SessionChangedError);
  expect(getStoredTokens().accessToken).toBeNull();
});

it('does not expire a newer rotation when an already-retried older bearer finally returns 401', async () => {
  const retried = deferred<AxiosResponse>();
  responder = async (config) => {
    if (auth(config) === 'Bearer access-a') throw failure(config);
    if (auth(config) === 'Bearer rotated-a') return retried.promise;
    return success(config);
  };
  const request = outcome(api.get('/slow-retry'));
  await flush();
  expect(calls).toHaveLength(2);
  refresher = async (config) =>
    success(config, { access_token: 'newer-rotation-a', refresh_token: 'newer-refresh-a' });
  await authApi.refresh(rotated.refresh_token);
  retried.reject(failure(calls[1]));
  expect((await request).error).toBeInstanceOf(SessionChangedError);
  expect(getStoredTokens().accessToken).toBe('newer-rotation-a');
  expect(calls).toHaveLength(2);
  expect(refreshCalls).toHaveLength(2);
});

it('observes another tab credential pair before allowing a late refresh commit', async () => {
  const delayed = deferred<AxiosResponse>();
  refresher = () => delayed.promise;
  const request = outcome(api.get('/a'));
  await flush();
  localStorage.setItem('access_token', other.access_token);
  localStorage.setItem('refresh_token', other.refresh_token);
  delayed.resolve(success(refreshCalls[0], rotated));
  expect((await request).error).toBeInstanceOf(SessionChangedError);
  expect(getStoredTokens().accessToken).toBe(other.access_token);
  expect(calls).toHaveLength(1);
});
it('never attaches a caller supplied Authorization header to a public auth route', async () => {
  responder = async (config) => success(config);
  await api.post('/auth/login', {}, { headers: { Authorization: 'Bearer must-not-forward' } });
  expect(auth(calls[0])).toBeUndefined();
});

it('the compatibility registration helper preserves a non-token response without clearing an active session', async () => {
  responder = async (config) => success(config, { message: 'Registration pending review' });
  await expect(authApi.registerRider({ first_name: 'Test', optional: null })).resolves.toEqual({
    message: 'Registration pending review',
  });
  expect(getStoredTokens().accessToken).toBe(old.access_token);
  expect(auth(calls[0])).toBeUndefined();
});
it('the compatibility registration helper cannot store tokens from an obsolete response', async () => {
  const delayed = deferred<AxiosResponse>();
  responder = () => delayed.promise;
  const request = outcome(authApi.registerRider({ first_name: 'Test' }));
  storeTokens(other);
  delayed.resolve(success(calls[0], old));
  expect((await request).error).toBeInstanceOf(SessionChangedError);
  expect(getStoredTokens().accessToken).toBe(other.access_token);
});
