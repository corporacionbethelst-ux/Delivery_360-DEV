import {
  getAccessTokenRevision,
  onAccessTokenRotated,
  captureAuthSession,
  clearStoredTokens,
  commitRefreshedTokens,
  getStoredTokens,
  isCurrentAuthSession,
  onCredentialsChanged,
  SessionChangedError,
  storeTokens,
  validRefreshPair,
} from '@/lib/auth-session';
const original = { access_token: 'owner-a-access', refresh_token: 'owner-a-refresh' };
const rotated = { access_token: 'owner-a-rotated', refresh_token: 'owner-a-refresh-rotated' };
beforeEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
  clearStoredTokens();
});
afterEach(() => {
  jest.restoreAllMocks();
  clearStoredTokens();
});
it('returns detached snapshots so a consumer cannot mutate active credentials', () => {
  storeTokens(original);
  const snapshot = getStoredTokens();
  snapshot.accessToken = 'forged';
  expect(getStoredTokens().accessToken).toBe(original.access_token);
});
it('fences logout and same-value login ABA even if credentials later match again', () => {
  storeTokens(original);
  const before = captureAuthSession();
  clearStoredTokens();
  storeTokens(original);
  expect(isCurrentAuthSession(before)).toBe(false);
  expect(captureAuthSession().generation).toBeGreaterThan(before.generation);
});
it('explicitly storing even the same pair establishes a new generation', () => {
  storeTokens(original);
  const before = captureAuthSession();
  storeTokens(original);
  expect(isCurrentAuthSession(before)).toBe(false);
});
it('rotation preserves the session but cannot be committed twice against an old pair', () => {
  storeTokens(original);
  const before = captureAuthSession();
  commitRefreshedTokens(before, rotated);
  expect(isCurrentAuthSession(before)).toBe(true);
  expect(getStoredTokens().accessToken).toBe(rotated.access_token);
  expect(() => commitRefreshedTokens(before, original)).toThrow(SessionChangedError);
});
it('a refresh from a prior owner cannot overwrite the replacement session', () => {
  storeTokens(original);
  const before = captureAuthSession();
  storeTokens({ access_token: 'b-access', refresh_token: 'b-refresh' });
  expect(() => commitRefreshedTokens(before, rotated)).toThrow(SessionChangedError);
  expect(getStoredTokens().accessToken).toBe('b-access');
});
it('observing an external storage change invalidates the captured generation', () => {
  storeTokens(original);
  const before = captureAuthSession();
  localStorage.setItem('access_token', 'external-access');
  expect(isCurrentAuthSession(before)).toBe(false);
  expect(getStoredTokens().accessToken).toBe('external-access');
});
it.each([
  null,
  {},
  { access_token: 'x' },
  { access_token: '', refresh_token: 'x' },
  { access_token: 'x', refresh_token: 'bad token' },
  { access_token: 'bad\nheader', refresh_token: 'x' },
  { access_token: 'x', refresh_token: 'x'.repeat(16385) },
  { access_token: 123, refresh_token: 'x' },
])('rejects malformed refresh payloads without changing the original pair: %p', (value) => {
  storeTokens(original);
  const before = captureAuthSession();
  expect(validRefreshPair(value)).toBe(false);
  expect(() => commitRefreshedTokens(before, value as typeof original)).toThrow();
  expect(getStoredTokens().accessToken).toBe(original.access_token);
});
it('supports a login without refresh but still validates bearer header characters', () => {
  storeTokens({ access_token: 'only-access', refresh_token: '' });
  expect(getStoredTokens().refreshToken).toBe('');
  expect(() => storeTokens({ access_token: 'bad token', refresh_token: '' })).toThrow('no válidas');
});
it('clears memory and cookies even when removal of persisted tokens is denied', () => {
  storeTokens(original);
  document.cookie = 'auth-token=old; path=/';
  document.cookie = 'user-data=private; path=/';
  const spy = jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('private storage diagnostic');
  });
  clearStoredTokens();
  expect(getStoredTokens()).toEqual({ accessToken: null, refreshToken: null });
  spy.mockRestore();
  expect(localStorage.getItem('access_token')).toBe(original.access_token);
  expect(getStoredTokens().accessToken).toBeNull();
  expect(document.cookie).not.toContain('auth-token=');
  expect(document.cookie).not.toContain('user-data=');
  storeTokens(rotated);
  expect(getStoredTokens().accessToken).toBe(rotated.access_token);
});
it('partial writes fail closed, clean remnants, and expose no private storage exception', () => {
  storeTokens(original);
  const before = captureAuthSession();
  const set = Storage.prototype.setItem;
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
    this: Storage,
    key: string,
    value: string
  ) {
    if (key === 'refresh_token') throw new Error('private storage path');
    set.call(this, key, value);
  });
  expect(() => storeTokens(rotated)).toThrow('No se pudieron guardar');
  expect(getStoredTokens().accessToken).toBeNull();
  expect(localStorage.getItem('access_token')).toBeNull();
  expect(isCurrentAuthSession(before)).toBe(false);
});
it('does not re-read residual disk tokens after a failed write and cleanup', () => {
  storeTokens(original);
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied');
  });
  jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('denied');
  });
  expect(() => storeTokens(rotated)).toThrow();
  jest.restoreAllMocks();
  expect(localStorage.getItem('access_token')).toBe(original.access_token);
  expect(getStoredTokens().accessToken).toBeNull();
});
it('only synchronizes an existing navigation cookie after a successful refresh', () => {
  storeTokens(original);
  const first = captureAuthSession();
  commitRefreshedTokens(first, rotated);
  expect(document.cookie).not.toContain('auth-token=');
  document.cookie = 'auth-token=old; path=/';
  const next = captureAuthSession();
  commitRefreshedTokens(next, original);
  expect(document.cookie).toContain('auth-token=owner-a-access');
});
it('notifies invalidation without sending credentials and permits unsubscribe', () => {
  const listener = jest.fn();
  const stop = onCredentialsChanged(listener);
  storeTokens(original);
  expect(listener).toHaveBeenCalledWith();
  stop();
  clearStoredTokens();
  expect(listener).toHaveBeenCalledTimes(1);
});

it('announces a complete token rotation without invalidating this user generation', () => {
  storeTokens(original);
  const before = captureAuthSession(),
    revision = getAccessTokenRevision();
  const invalidated = jest.fn(),
    rotated = jest.fn();
  const stop = onCredentialsChanged(invalidated),
    end = onAccessTokenRotated(rotated);
  try {
    commitRefreshedTokens(before, { access_token: 'new-access', refresh_token: 'new-refresh' });
    expect(isCurrentAuthSession(before)).toBe(true);
    expect(getAccessTokenRevision()).toBe(revision + 1);
    expect(invalidated).not.toHaveBeenCalled();
    expect(rotated).toHaveBeenCalledWith();
  } finally {
    stop();
    end();
  }
});
it('a failed rotation observer cannot block other transports or roll back a committed pair', () => {
  storeTokens(original);
  const before = captureAuthSession();
  const tail = jest.fn();
  const stop = onAccessTokenRotated(() => {
      throw new Error('observer failed');
    }),
    end = onAccessTokenRotated(tail);
  try {
    expect(() =>
      commitRefreshedTokens(before, { access_token: 'new-access', refresh_token: 'new-refresh' })
    ).not.toThrow();
    expect(tail).toHaveBeenCalledTimes(1);
    expect(getStoredTokens().accessToken).toBe('new-access');
  } finally {
    stop();
    end();
  }
});
