import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import { payoutService } from '@/services/payout.service';
import Page from '@/app/(dashboard)/rider/earnings/withdraw/page';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { loadWithdrawalIntent } from '@/lib/withdrawal-intent';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const original = client.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
const record = { currency: 'USD', id: 'p', rider_id: 'r', amount: 60, total_amount: 60, method: 'TRANSFERENCIA', payment_method: 'TRANSFERENCIA', status: 'PENDIENTE', requested_by_user_id: 'a' };
beforeEach(() => { clearStoredTokens(); sessionStorage.clear(); mockUser = { id: 'a', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-a', refresh_token: 'refresh-a' }); });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; });

it('fences the gap after the actual Axios interceptor accepts a response and before the service publishes', async () => {
  client.defaults.adapter = async config => reply(config, record);
  const hook = client.interceptors.response.use(response => { storeTokens({ access_token: 'access-b', refresh_token: 'refresh-b' }); return response; });
  try { await expect(payoutService.getById('p')).rejects.toBeInstanceOf(SessionChangedError); }
  finally { client.interceptors.response.eject(hook); }
});
it('preserves the durable key when the actual HTTP wrapper receives a contradictory 200 confirmation', async () => {
  client.defaults.adapter = async config => reply(config, config.url?.includes('/balance') ? { available: 100, pending: 0, currency: 'USD' } : { ...record, idempotency_key: 'not-the-sent-key' });
  render(<Page />);
  fireEvent.change(await screen.findByLabelText('Monto a Retirar'), { target: { value: '60' } });
  fireEvent.submit(screen.getByLabelText('Monto a Retirar').closest('form')!);
  await screen.findByText('Error al procesar. Intenta más tarde.');
  expect(loadWithdrawalIntent('a')?.amountCents).toBe(6000); expect(screen.queryByText('¡Solicitud Enviada!')).not.toBeInTheDocument();
});
it('retains the initiating account key after a real HTTP continuation is retired', async () => {
  client.defaults.adapter = async config => {
    if (config.url?.includes('/balance')) return reply(config, { available: 100, pending: 0, currency: 'USD' });
    const data = JSON.parse(String(config.data));
    return reply(config, { ...record, idempotency_key: data.idempotency_key });
  };
  const hook = client.interceptors.response.use(response => {
    if (response.config.url?.includes('/request')) { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-b', refresh_token: 'refresh-b' }); }
    return response;
  });
  try {
    render(<Page />); fireEvent.change(await screen.findByLabelText('Monto a Retirar'), { target: { value: '60' } });
    await act(async () => { fireEvent.submit(screen.getByLabelText('Monto a Retirar').closest('form')!); });
    expect(loadWithdrawalIntent('a')?.amountCents).toBe(6000); expect(loadWithdrawalIntent('b')).toBeNull();
    expect(screen.queryByText('¡Solicitud Enviada!')).not.toBeInTheDocument();
  } finally { client.interceptors.response.eject(hook); }
});
it('rejects a degraded balance through the actual HTTP wrapper without showing a normal zero', async () => {
  client.defaults.adapter = async config => reply(config, { available: 0, pending: 0, degraded: true, currency: 'USD' });
  render(<Page />); await screen.findByText('No se pudo cargar tu saldo disponible. Puedes volver a consultarlo.');
  expect(screen.getAllByText('No disponible').length).toBeGreaterThan(0); expect(screen.getByRole('button', { name: 'Enviar solicitud de retiro' })).toBeDisabled();
});
