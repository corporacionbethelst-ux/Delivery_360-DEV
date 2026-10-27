import { authService } from '@/services/auth.service';
import { api, getStoredTokens } from '@/lib/api';
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() }, getStoredTokens: jest.fn() }));
const originalFetch = global.fetch;
const fetcher = jest.fn();
beforeEach(() => {
  jest.clearAllMocks();
  fetcher.mockReset();
  fetcher.mockResolvedValue({ ok: true });
  global.fetch = fetcher;
  jest
    .mocked(getStoredTokens)
    .mockReturnValue({ accessToken: 'new-account', refreshToken: 'new-refresh' });
});
afterEach(() => {
  global.fetch = originalFetch;
  jest.useRealTimers();
});
it('uses the captured logout bearer without entering the refresh interceptor', async () => {
  await authService.logout('old-account');
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining('/auth/logout'),
    expect.objectContaining({
      method: 'POST',
      headers: { Authorization: 'Bearer old-account' },
      keepalive: true,
    })
  );
  expect(api.post).not.toHaveBeenCalled();
  expect(getStoredTokens).not.toHaveBeenCalled();
});
it('does not substitute a new account bearer when the captured one is null', async () => {
  await authService.logout(null);
  expect(fetcher).not.toHaveBeenCalled();
  expect(getStoredTokens).not.toHaveBeenCalled();
});
it('supports callers that capture the currently stored bearer by default', async () => {
  await authService.logout();
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer new-account');
});
it.each([401, 500])('never retries or refreshes on logout HTTP %i', async (status) => {
  fetcher.mockResolvedValueOnce({ ok: false, status });
  await authService.logout('old');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(api.post).not.toHaveBeenCalled();
});
it('bounds logout network work and absorbs a private network error', async () => {
  jest.useFakeTimers();
  fetcher.mockImplementationOnce(
    (_url, init: RequestInit) =>
      new Promise((_yes, no) => {
        init.signal?.addEventListener('abort', () => no(new Error('private URL and token')));
      })
  );
  const work = authService.logout('old');
  jest.advanceTimersByTime(1500);
  await expect(work).resolves.toBeUndefined();
  expect(jest.getTimerCount()).toBe(0);
});
