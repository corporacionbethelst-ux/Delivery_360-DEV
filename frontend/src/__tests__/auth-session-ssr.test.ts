/** @jest-environment node */
import {
  captureAuthSession,
  clearStoredTokens,
  getStoredTokens,
  storeTokens,
} from '@/lib/auth-session';
it('does not persist browser credentials in a server rendering process', () => {
  expect(typeof window).toBe('undefined');
  storeTokens({ access_token: 'never-global', refresh_token: 'never-global-refresh' });
  expect(getStoredTokens()).toEqual({ accessToken: null, refreshToken: null });
  clearStoredTokens();
  expect(captureAuthSession().accessToken).toBeNull();
});
