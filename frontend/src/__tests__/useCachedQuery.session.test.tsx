import React from 'react';
import { act, renderHook } from '@testing-library/react';
import { useCachedQuery, cacheUtils } from '@/hooks/useCachedQuery';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
const a = { access_token: 'a-access', refresh_token: 'a-refresh' },
  b = { access_token: 'b-access', refresh_token: 'b-refresh' };
function pending<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(a);
  cacheUtils.clear();
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
  clearStoredTokens();
});
it('does not query or reveal cached data without credentials', async () => {
  clearStoredTokens();
  const query = jest.fn();
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'private', queryFn: query }));
  await act(async () => {});
  expect(query).not.toHaveBeenCalled();
  expect(result.current.data).toBeNull();
  expect(result.current.isLoading).toBe(false);
  unmount();
});
it('uses a fresh memory entry without a request and supports falsy values', async () => {
  cacheUtils.set('private', 0, 60);
  const query = jest.fn().mockResolvedValue(1);
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'private', queryFn: query }));
  await act(async () => {});
  expect(result.current.data).toBe(0);
  expect(result.current.isFromCache).toBe(true);
  expect(query).not.toHaveBeenCalled();
  unmount();
});
it('a late response for owner A cannot populate owner B or its cache', async () => {
  const old = pending<string>();
  const query = jest.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce('owner-b');
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'same', queryFn: query }));
  act(() => storeTokens(b));
  await act(async () => {});
  expect(result.current.data).toBe('owner-b');
  await act(async () => {
    old.resolve('owner-a');
  });
  expect(result.current.data).toBe('owner-b');
  expect(cacheUtils.get('same')).toBe('owner-b');
  unmount();
});
it('logout hides data and late errors cannot revive the previous query', async () => {
  const old = pending<string>();
  const query = jest.fn().mockReturnValue(old.promise);
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'private', queryFn: query }));
  act(() => clearStoredTokens());
  await act(async () => {
    old.reject(new Error('private URL and bearer'));
  });
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBeNull();
  expect(result.current.isLoading).toBe(false);
  unmount();
});
it('key changes discard the old value before the new query completes', async () => {
  const next = pending<string>();
  const query = jest.fn().mockResolvedValueOnce('first').mockReturnValueOnce(next.promise);
  const { result, rerender, unmount } = renderHook(
    ({ key }) => useCachedQuery({ key, queryFn: query }),
    { initialProps: { key: 'first' } }
  );
  await act(async () => {});
  expect(result.current.data).toBe('first');
  rerender({ key: 'next' });
  expect(result.current.data).toBeNull();
  await act(async () => {
    next.resolve('next');
  });
  expect(result.current.data).toBe('next');
  unmount();
});
it('the latest explicit refetch wins when responses arrive backwards', async () => {
  const old = pending<string>();
  const query = jest.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce('latest');
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'same', queryFn: query }));
  await act(async () => {
    await result.current.refetch();
    old.resolve('old');
  });
  expect(result.current.data).toBe('latest');
  expect(cacheUtils.get('same')).toBe('latest');
  unmount();
});
it('disabled queries expose no data and manual refetch remains disabled', async () => {
  cacheUtils.set('k', 'private', 60);
  const query = jest.fn();
  const { result, unmount } = renderHook(() =>
    useCachedQuery({ key: 'k', queryFn: query, enabled: false })
  );
  await act(async () => {
    await result.current.refetch();
  });
  expect(result.current.data).toBeNull();
  expect(query).not.toHaveBeenCalled();
  unmount();
});
it('disable and re-enable reject the prior generation of component work', async () => {
  const old = pending<string>();
  const query = jest.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce('current');
  const { result, rerender, unmount } = renderHook(
    ({ enabled }) => useCachedQuery({ key: 'k', queryFn: query, enabled }),
    { initialProps: { enabled: true } }
  );
  rerender({ enabled: false });
  rerender({ enabled: true });
  await act(async () => {
    old.resolve('obsolete');
  });
  expect(result.current.data).toBe('current');
  unmount();
});
it('unmounted work cannot refill shared cache', async () => {
  const old = pending<string>();
  const { unmount } = renderHook(() => useCachedQuery({ key: 'k', queryFn: () => old.promise }));
  unmount();
  await act(async () => {
    old.resolve('discarded');
  });
  expect(cacheUtils.get('k')).toBeNull();
});
it('inline query callbacks do not produce a request loop', async () => {
  const calls = jest.fn().mockResolvedValue('data');
  const { result, rerender, unmount } = renderHook(() =>
    useCachedQuery({ key: 'k', queryFn: () => calls() })
  );
  await act(async () => {});
  rerender();
  await act(async () => {});
  expect(calls).toHaveBeenCalledTimes(1);
  expect(result.current.data).toBe('data');
  unmount();
});
it('stale data is refreshed in the background', async () => {
  jest.useFakeTimers();
  cacheUtils.set('k', 'cached', 300);
  jest.advanceTimersByTime(61000);
  const current = pending<string>();
  const query = jest.fn().mockReturnValue(current.promise);
  const { result, unmount } = renderHook(() =>
    useCachedQuery({ key: 'k', queryFn: query, staleTime: 60 })
  );
  expect(result.current.data).toBe('cached');
  expect(result.current.isLoading).toBe(true);
  await act(async () => {
    current.resolve('fresh');
  });
  expect(result.current.data).toBe('fresh');
  unmount();
});
it('a failed refresh can use only this generation and key cached value', async () => {
  cacheUtils.set('k', 'cached', 60);
  const query = jest.fn().mockRejectedValue(new Error('private config'));
  const { result, unmount } = renderHook(() =>
    useCachedQuery({ key: 'k', queryFn: query, staleTime: 0 })
  );
  await act(async () => {});
  expect(result.current.data).toBe('cached');
  expect(result.current.isError).toBe(false);
  expect(result.current.error).toBeNull();
  unmount();
});
it('returns a generic error when this session has no fallback value', async () => {
  const { result, unmount } = renderHook(() =>
    useCachedQuery({
      key: 'k',
      queryFn: async () => {
        throw new Error('private config');
      },
    })
  );
  await act(async () => {});
  expect(result.current.error?.message).toBe('No se pudieron cargar los datos');
  expect(result.current.isError).toBe(true);
  unmount();
});
it('React StrictMode cannot revive the discarded first setup', async () => {
  const old = pending<string>();
  const query = jest.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce('current');
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <React.StrictMode>{children}</React.StrictMode>
  );
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'k', queryFn: query }), {
    wrapper,
  });
  await act(async () => {
    old.resolve('old');
  });
  expect(result.current.data).toBe('current');
  expect(cacheUtils.get('k')).toBe('current');
  unmount();
});

it('observes an external storage replacement before dispatching a query for the old render scope', async () => {
  localStorage.setItem('access_token', 'external-b');
  localStorage.setItem('refresh_token', 'external-refresh-b');
  const query = jest.fn(async () => localStorage.getItem('access_token'));
  const { result, unmount } = renderHook(() => useCachedQuery({ key: 'private', queryFn: query }));
  await act(async () => {});
  expect(query).toHaveBeenCalledTimes(1);
  expect(result.current.data).toBe('external-b');
  expect(cacheUtils.get('private')).toBe('external-b');
  unmount();
});
