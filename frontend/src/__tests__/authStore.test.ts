import { useAuthStore } from '@/stores/authStore';
import { authService } from '@/services/auth.service';
import { clearStoredTokens, getStoredTokens, storeTokens } from '@/lib/api';
import { User } from '@/types/user';

jest.mock('@/services/auth.service', () => ({ authService: { login: jest.fn(), getProfile: jest.fn(), logout: jest.fn(), register: jest.fn() } }));
jest.mock('@/lib/api', () => ({ getStoredTokens: jest.fn(), storeTokens: jest.fn(), clearStoredTokens: jest.fn() }));
const profile: User = { id: 'user-1', email: 'user@example.test', first_name: 'Test', last_name: 'User', role: 'OPERADOR', is_active: true, created_at: '2026-10-24', updated_at: '2026-10-24' };
const credentials = { email: profile.email, password: 'unused-test' };
const tokens = { access_token: 'access-test', refresh_token: 'refresh-test', token_type: 'bearer' };
const service = jest.mocked(authService);
beforeEach(() => {
  jest.mocked(getStoredTokens).mockReturnValue({ accessToken: 'access-test', refreshToken: 'refresh-test' });
  useAuthStore.getState().forceLogout();
  localStorage.clear();
  localStorage.setItem('app_version', '1.2.1');
  jest.clearAllMocks();
  jest.mocked(getStoredTokens).mockReturnValue({ accessToken: 'access-test', refreshToken: 'refresh-test' });
  service.login.mockResolvedValue(tokens);
  service.getProfile.mockResolvedValue(profile);
  service.logout.mockResolvedValue();
});

it('authenticates only after a valid server profile', async () => {
  await useAuthStore.getState().login(credentials);
  expect(storeTokens).toHaveBeenCalledWith({ access_token: tokens.access_token, refresh_token: tokens.refresh_token });
  expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: true, isLoading: false, user: expect.objectContaining({ id: profile.id }) });
});
it('does not authenticate from a cached profile while verification is pending', async () => {
  localStorage.setItem('user', JSON.stringify({ ...profile, role: 'SUPERADMIN' }));
  let resolve!: (user: User) => void;
  service.getProfile.mockReturnValueOnce(new Promise<User>(done => { resolve = done; }));
  const pending = useAuthStore.getState().checkAuth();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  expect(useAuthStore.getState().isLoading).toBe(true);
  resolve(profile);
  await pending;
  expect(useAuthStore.getState().user?.role).toBe('OPERADOR');
});
it('late login responses cannot restore tokens after force logout', async () => {
  let resolve!: (value: typeof tokens) => void;
  service.login.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const pending = useAuthStore.getState().login(credentials);
  useAuthStore.getState().forceLogout();
  resolve(tokens);
  await expect(pending).rejects.toThrow('cancelado');
  expect(storeTokens).not.toHaveBeenCalled();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
});
it('late profile responses cannot restore a logged out session', async () => {
  let resolve!: (user: User) => void;
  service.getProfile.mockReturnValueOnce(new Promise<User>(done => { resolve = done; }));
  const pending = useAuthStore.getState().checkAuth();
  useAuthStore.getState().forceLogout();
  resolve(profile);
  await pending;
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
  expect(localStorage.getItem('user')).toBeNull();
});
it('version changes clear authentication without deleting unrelated preferences', async () => {
  localStorage.setItem('app_version', 'old');
  localStorage.setItem('theme', 'dark');
  localStorage.setItem('delivery360-auth-v0', 'stale');
  await useAuthStore.getState().checkAuth();
  expect(localStorage.getItem('theme')).toBe('dark');
  expect(localStorage.getItem('delivery360-auth-v0')).toBeNull();
  expect(clearStoredTokens).toHaveBeenCalled();
  expect(service.getProfile).not.toHaveBeenCalled();
});
it('missing tokens clear stale cookies and profiles', async () => {
  jest.mocked(getStoredTokens).mockReturnValueOnce({ accessToken: null, refreshToken: null });
  localStorage.setItem('user', JSON.stringify(profile));
  await useAuthStore.getState().checkAuth();
  expect(localStorage.getItem('user')).toBeNull();
  expect(clearStoredTokens).toHaveBeenCalled();
});
it('inactive profiles fail closed', async () => {
  service.getProfile.mockResolvedValueOnce({ ...profile, is_active: false });
  await expect(useAuthStore.getState().login(credentials)).rejects.toThrow('no habilitado');
  expect(clearStoredTokens).toHaveBeenCalled();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
});
it('failed profile verification clears the session', async () => {
  service.getProfile.mockRejectedValueOnce(new Error('Unauthorized'));
  await useAuthStore.getState().checkAuth();
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false, isLoading: false });
});
it('logout is immediate even if the server has not responded', async () => {
  await useAuthStore.getState().login(credentials);
  let resolve!: () => void;
  service.logout.mockReturnValueOnce(new Promise<void>(done => { resolve = done; }));
  const pending = useAuthStore.getState().logout();
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  resolve();
  await pending;
});
it('persisted state contains no user or authenticated flag', async () => {
  await useAuthStore.getState().login(credentials);
  const persisted = JSON.parse(localStorage.getItem('delivery360-auth-v1.2.1') || '{}');
  expect(persisted.state).toEqual({});
});
it('a fresh login records the app version so validation does not erase it', async () => {
  localStorage.removeItem('app_version');
  await useAuthStore.getState().login(credentials);
  expect(localStorage.getItem('app_version')).toBe('1.2.1');
  await useAuthStore.getState().checkAuth();
  expect(useAuthStore.getState().isAuthenticated).toBe(true);
});
it('a token rotated during profile lookup is used in the navigation cookie', async () => {
  jest.mocked(getStoredTokens)
    .mockReturnValueOnce({ accessToken: 'old-access', refreshToken: 'old-refresh' })
    .mockReturnValueOnce({ accessToken: 'rotated-access', refreshToken: 'rotated-refresh' });
  await useAuthStore.getState().checkAuth();
  expect(document.cookie).toContain('auth-token=rotated-access');
});
it('rehydrating a forged authenticated flag does not bypass server verification', async () => {
  localStorage.setItem('delivery360-auth-v1.2.1', JSON.stringify({ state: { user: { ...profile, role: 'SUPERADMIN' }, isAuthenticated: true }, version: 0 }));
  await useAuthStore.persist.rehydrate();
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
});
it('an old failed login cannot clear a newer successful login', async () => {
  let reject!: (reason: Error) => void;
  service.login.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
  const old = useAuthStore.getState().login(credentials);
  await useAuthStore.getState().login(credentials);
  const clearsBeforeLateFailure = jest.mocked(clearStoredTokens).mock.calls.length;
  reject(new Error('Late failure'));
  await expect(old).rejects.toThrow('Late failure');
  expect(useAuthStore.getState().isAuthenticated).toBe(true);
  expect(clearStoredTokens).toHaveBeenCalledTimes(clearsBeforeLateFailure);
});

it('captures the logout bearer before erasing it and clears private alerts immediately', async () => {
  const { useNotificationStore } = await import('@/stores/notificationStore');
  await useAuthStore.getState().login(credentials);
  useNotificationStore.getState().addNotification({ type: 'SYSTEM', title: 'Private', message: 'Owner only' });
  expect(useNotificationStore.getState().notifications).toHaveLength(1);
  let resolve!: () => void;
  service.logout.mockReturnValueOnce(new Promise<void>(done => { resolve = done; }));
  const pending = useAuthStore.getState().logout();
  expect(service.logout).toHaveBeenCalledWith('access-test');
  expect(useNotificationStore.getState()).toMatchObject({ notifications: [], sessionUserId: null });
  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  resolve(); await pending;
});
it('a new login discards the previous profile and alert scope before the server responds', async () => {
  const { useNotificationStore } = await import('@/stores/notificationStore');
  await useAuthStore.getState().login(credentials);
  const previousRevision = useAuthStore.getState().sessionRevision;
  useNotificationStore.getState().addNotification({ type: 'SYSTEM', title: 'Private', message: 'Owner only' });
  let resolve!: (value: typeof tokens) => void;
  service.login.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const pending = useAuthStore.getState().login(credentials);
  expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
  expect(useAuthStore.getState().sessionRevision).toBeGreaterThan(previousRevision);
  expect(useNotificationStore.getState()).toMatchObject({ notifications: [], sessionUserId: null });
  resolve(tokens); await pending; expect(useNotificationStore.getState().sessionUserId).toBe(profile.id);
});
it('profile revalidation clears stale alerts until the account is verified again', async () => {
  const { useNotificationStore } = await import('@/stores/notificationStore');
  await useAuthStore.getState().login(credentials);
  useNotificationStore.getState().addNotification({ type: 'SYSTEM', title: 'Private', message: 'Owner only' });
  let resolve!: (value: User) => void;
  service.getProfile.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const pending = useAuthStore.getState().checkAuth();
  expect(useNotificationStore.getState().sessionUserId).toBeNull();
  resolve(profile); await pending; expect(useNotificationStore.getState().sessionUserId).toBe(profile.id);
});

it('retires legacy web identifiers only after the server profile is verified', async () => {
  const original = global.fetch;
  const fetcher = jest.fn().mockResolvedValue({ ok: true });
  global.fetch = fetcher;
  try {
    localStorage.setItem('d360_device_token', 'web-verified-browser');
    let resolve!: (value: User) => void;
    service.getProfile.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const login = useAuthStore.getState().login(credentials);
    await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
    resolve(profile); await login;
    const { retireLegacyPushDevice } = await import('@/lib/deviceRegistration');
    await retireLegacyPushDevice('access-test');
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'DELETE', headers: { Authorization: 'Bearer access-test' } });
    expect(localStorage.getItem('d360_device_token')).toBeNull();
  } finally { global.fetch = original; }
});
it('forceLogout starts legacy cleanup with its captured bearer before any new login', async () => {
  const original = global.fetch;
  let resolve!: (value: unknown) => void;
  const fetcher = jest.fn().mockReturnValue(new Promise(done => { resolve = done; }));
  global.fetch = fetcher;
  try {
    localStorage.setItem('d360_device_token', 'web-logout-browser');
    useAuthStore.getState().forceLogout();
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'DELETE', headers: { Authorization: 'Bearer access-test' } });
    expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
    resolve({ ok: true });
    const { retireLegacyPushDevice } = await import('@/lib/deviceRegistration');
    await retireLegacyPushDevice('access-test');
    expect(fetcher).toHaveBeenCalledTimes(1);
  } finally { global.fetch = original; }
});
