import { retireLegacyPushDevice } from '@/lib/deviceRegistration';
const originalFetch = global.fetch;
const fetcher = jest.fn();
const key = 'd360_device_token',
  registered = 'd360_registered_device_token';
beforeEach(() => {
  localStorage.clear();
  fetcher.mockReset();
  fetcher.mockResolvedValue({ ok: true });
  global.fetch = fetcher;
});
afterEach(() => {
  global.fetch = originalFetch;
  jest.restoreAllMocks();
  jest.useRealTimers();
});
it('does not create or register a fabricated browser token', async () => {
  await retireLegacyPushDevice('jwt');
  expect(fetcher).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
});
it('does nothing without a bearer and preserves retryable legacy data', async () => {
  localStorage.setItem(key, 'web-test-old');
  await retireLegacyPushDevice(null);
  expect(fetcher).not.toHaveBeenCalled();
  expect(localStorage.getItem(key)).toBe('web-test-old');
});
it('retires an old UUID with authenticated DELETE and clears only its old markers', async () => {
  localStorage.setItem(key, 'web-test-old');
  localStorage.setItem(registered, 'web-test-old');
  localStorage.setItem('theme', 'dark');
  await retireLegacyPushDevice('captured-jwt');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining('/notifications/unregister-device'),
    expect.objectContaining({
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer captured-jwt' },
      body: JSON.stringify({ device_token: 'web-test-old' }),
      keepalive: true,
      signal: expect.any(AbortSignal),
    })
  );
  expect(localStorage.getItem(key)).toBeNull();
  expect(localStorage.getItem(registered)).toBeNull();
  expect(localStorage.getItem('theme')).toBe('dark');
});
it.each(['valid-provider-token:abc', 'web-bad token', 'web-\u0000', 'web-' + 'x'.repeat(260)])(
  'never interprets arbitrary data as a legacy UUID (%s)',
  async (token) => {
    localStorage.setItem(key, token);
    await retireLegacyPushDevice('jwt');
    expect(fetcher).not.toHaveBeenCalled();
    expect(localStorage.getItem(key)).toBe(token);
  }
);
it('cleans two distinct legacy markers independently', async () => {
  localStorage.setItem(key, 'web-first');
  localStorage.setItem(registered, 'web-second');
  await retireLegacyPushDevice('jwt');
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(localStorage.length).toBe(0);
});
it.each([401, 403, 503])(
  'preserves the old marker on HTTP %i to retry next session',
  async (status) => {
    localStorage.setItem(key, 'web-retry');
    fetcher.mockResolvedValueOnce({ ok: false, status });
    await retireLegacyPushDevice('jwt');
    expect(localStorage.getItem(key)).toBe('web-retry');
    await retireLegacyPushDevice('jwt');
    expect(fetcher).toHaveBeenCalledTimes(2);
  }
);
it('deduplicates simultaneous cleanup for the same captured bearer', async () => {
  let resolve!: (value: unknown) => void;
  fetcher.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    })
  );
  localStorage.setItem(key, 'web-same');
  const first = retireLegacyPushDevice('jwt'),
    second = retireLegacyPushDevice('jwt');
  expect(fetcher).toHaveBeenCalledTimes(1);
  resolve({ ok: true });
  await Promise.all([first, second]);
});
it('a late cleanup cannot erase a replacement marker', async () => {
  let resolve!: (value: unknown) => void;
  fetcher.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    })
  );
  localStorage.setItem(key, 'web-old-one');
  const first = retireLegacyPushDevice('old-jwt');
  localStorage.setItem(key, 'web-new-one');
  resolve({ ok: true });
  await first;
  expect(localStorage.getItem(key)).toBe('web-new-one');
});
it('aborts stalled network work after 1.5 seconds without exposing its error', async () => {
  jest.useFakeTimers();
  const log = jest.spyOn(console, 'warn').mockImplementation(() => {});
  fetcher.mockImplementationOnce(
    (_url, init: RequestInit) =>
      new Promise((_done, reject) => {
        init.signal?.addEventListener('abort', () => reject(new Error('private bearer and URL')));
      })
  );
  localStorage.setItem(key, 'web-timeout');
  const work = retireLegacyPushDevice('jwt');
  jest.advanceTimersByTime(1500);
  await work;
  expect(localStorage.getItem(key)).toBe('web-timeout');
  expect(log).not.toHaveBeenCalled();
  expect(jest.getTimerCount()).toBe(0);
});
it('storage denial does not block authentication', async () => {
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('Storage denied');
  });
  await expect(retireLegacyPushDevice('jwt')).resolves.toBeUndefined();
  expect(fetcher).not.toHaveBeenCalled();
});
