import { cacheUtils, readPrivateCache } from '@/lib/private-cache';
import {
  storeTokens,
  clearStoredTokens,
  captureAuthSession,
  onCredentialsChanged,
} from '@/lib/auth-session';
const first = { access_token: 'cache-owner-a', refresh_token: 'cache-refresh-a' },
  next = { access_token: 'cache-owner-b', refresh_token: 'cache-refresh-b' };
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(first);
  cacheUtils.clear();
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
  clearStoredTokens();
});
it('never caches private values without credentials', () => {
  clearStoredTokens();
  cacheUtils.set('private', { secret: 'value' }, 60);
  expect(cacheUtils.get('private')).toBeNull();
});
it.each([0, false, ''])('preserves a falsy cached value %p', (value) => {
  cacheUtils.set('k', value, 60);
  expect(cacheUtils.get('k')).toBe(value);
});
it('expires exactly at TTL and reports the age of an unexpired value', () => {
  jest.useFakeTimers();
  cacheUtils.set('k', 'private', 2);
  jest.advanceTimersByTime(1500);
  expect(readPrivateCache('k')).toMatchObject({ data: 'private', ageMs: 1500 });
  jest.advanceTimersByTime(500);
  expect(cacheUtils.get('k')).toBeNull();
});
it('clears cached values synchronously on logout, new login and identical token ABA', () => {
  cacheUtils.set('k', 'a', 60);
  storeTokens(next);
  expect(cacheUtils.get('k')).toBeNull();
  cacheUtils.set('k', 'b', 60);
  clearStoredTokens();
  storeTokens(next);
  expect(cacheUtils.get('k')).toBeNull();
});
it('discards a cache value when external credentials are observed', () => {
  cacheUtils.set('k', 'a', 60);
  localStorage.setItem('access_token', 'external');
  expect(cacheUtils.get('k')).toBeNull();
});
it('cannot commit an explicitly scoped result into another generation', () => {
  const before = captureAuthSession();
  storeTokens(next);
  expect(() => cacheUtils.set('k', 'old', 60, before.generation)).toThrow('sesión cambió');
  expect(cacheUtils.get('k')).toBeNull();
});
it('retires persisted plaintext without reading, parsing, restoring or rewriting it', () => {
  localStorage.setItem(
    'delivery360_cache',
    JSON.stringify({ private: { data: 'old-owner', timestamp: Date.now(), ttl: 999999 } })
  );
  localStorage.setItem('theme', 'dark');
  cacheUtils.restore();
  expect(cacheUtils.get('private')).toBeNull();
  cacheUtils.set('current', 'private', 60);
  cacheUtils.persist();
  expect(localStorage.getItem('delivery360_cache')).toBeNull();
  expect(localStorage.getItem('theme')).toBe('dark');
});
it('storage denial does not prevent memory cleanup or credential invalidation', () => {
  cacheUtils.set('k', 'a', 60);
  jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('private disk path');
  });
  expect(() => cacheUtils.clear()).not.toThrow();
  expect(cacheUtils.get('k')).toBeNull();
});
it('bounds memory to 500 entries and retains recently read entries', () => {
  for (let i = 0; i < 500; i++) cacheUtils.set(String(i), i, 60);
  expect(cacheUtils.get('0')).toBe(0);
  cacheUtils.set('next', 'next', 60);
  expect(cacheUtils.get('1')).toBeNull();
  expect(cacheUtils.get('0')).toBe(0);
  expect(cacheUtils.get('next')).toBe('next');
});
it.each([-1, NaN, Infinity])('rejects invalid TTL %p without replacing a cached value', (ttl) => {
  cacheUtils.set('k', 'existing', 60);
  expect(() => cacheUtils.set('k', 'invalid', ttl)).toThrow('caché');
  expect(cacheUtils.get('k')).toBe('existing');
});
it('supports targeted invalidation and ttl zero without affecting unrelated values', () => {
  cacheUtils.set('order:1', 'o1', 60);
  cacheUtils.set('orders:list', 'list', 60);
  cacheUtils.set('other', 'other', 60);
  cacheUtils.remove('order:1');
  cacheUtils.removePattern('orders:');
  expect(cacheUtils.get('order:1')).toBeNull();
  expect(cacheUtils.get('orders:list')).toBeNull();
  cacheUtils.set('other', 'disabled', 0);
  expect(cacheUtils.get('other')).toBeNull();
});
it('a failing invalidation subscriber cannot block other subscribers or cleanup', () => {
  const stop = onCredentialsChanged(() => {
    throw new Error('subscriber error');
  });
  const tail = jest.fn(),
    end = onCredentialsChanged(tail);
  cacheUtils.set('k', 'a', 60);
  expect(() => storeTokens(next)).not.toThrow();
  expect(tail).toHaveBeenCalledTimes(1);
  expect(cacheUtils.get('k')).toBeNull();
  stop();
  end();
});
