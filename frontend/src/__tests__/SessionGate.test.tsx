import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { SessionGate } from '@/components/layout/SessionGate';
import { useAuthStore } from '@/stores/authStore';
import { authService } from '@/services/auth.service';
import { getStoredTokens } from '@/lib/api';
import { User } from '@/types/user';
const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: mockReplace }) }));
jest.mock('@/services/auth.service', () => ({ authService: { getProfile: jest.fn() } }));
jest.mock('@/lib/api', () => ({ getStoredTokens: jest.fn(), clearStoredTokens: jest.fn() }));
const profile: User = { id: 'user-1', email: 'user@example.test', first_name: 'Test', last_name: 'User', role: 'OPERADOR', is_active: true, created_at: '', updated_at: '' };
beforeEach(() => {
  jest.mocked(getStoredTokens).mockReturnValue({ accessToken: 'access-test', refreshToken: 'refresh-test' });
  useAuthStore.getState().forceLogout();
  localStorage.setItem('app_version', '1.2.1');
  jest.clearAllMocks();
  jest.mocked(getStoredTokens).mockReturnValue({ accessToken: 'test-access', refreshToken: 'test-refresh' });
});
it('does not mount protected children while the profile is pending', async () => {
  let resolve!: (user: User) => void;
  jest.mocked(authService.getProfile).mockReturnValueOnce(new Promise<User>(done => { resolve = done; }));
  render(<SessionGate><div>Protected content</div></SessionGate>);
  expect(screen.getByRole('status')).toHaveTextContent('Verificando');
  expect(screen.queryByText('Protected content')).toBeNull();
  await act(async () => { resolve(profile); });
  expect(await screen.findByText('Protected content')).toBeInTheDocument();
  expect(mockReplace).not.toHaveBeenCalled();
});
it('redirects an invalid session without mounting protected children', async () => {
  jest.mocked(authService.getProfile).mockRejectedValueOnce(new Error('Unauthorized'));
  render(<SessionGate><div>Protected content</div></SessionGate>);
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  expect(screen.queryByText('Protected content')).toBeNull();
});
it('redirects immediately after force logout from verified content', async () => {
  jest.mocked(authService.getProfile).mockResolvedValueOnce(profile);
  render(<SessionGate><div>Protected content</div></SessionGate>);
  await screen.findByText('Protected content');
  act(() => useAuthStore.getState().forceLogout());
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  expect(screen.queryByText('Protected content')).toBeNull();
});
