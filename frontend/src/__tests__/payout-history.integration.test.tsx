import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import Page from '@/app/(dashboard)/rider/earnings/payouts/page';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const originalAdapter = client.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
const rows = (start: number, count: number, status = 'PENDIENTE', prefix = 'p') => Array.from({ length: count }, (_, i) => ({ id: `${prefix}${start + i}`, rider_id: 'r', amount: 10, total_amount: 10, status, method: 'EFECTIVO' }));
beforeEach(() => { clearStoredTokens(); mockUser = { id: 'a', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-a', refresh_token: 'refresh-a' }); });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = originalAdapter; });

it('navigates and filters through the actual Axios/API/service chain with a bounded lookahead query', async () => {
  const requests: Array<Record<string, string>> = [];
  client.defaults.adapter = async config => {
    const query = new URL(String(config.url), 'https://test.invalid').searchParams;
    requests.push(Object.fromEntries(query));
    expect(config.method).toBe('get');
    expect(config.headers.get('Authorization')).toBe('Bearer access-a');
    return reply(config, query.get('status') === 'COMPLETADO' ? rows(100, 1, 'COMPLETADO') : query.get('offset') === '50' ? rows(50, 1) : rows(0, 51));
  };
  render(<Page />); await screen.findByText('#p0'); expect(screen.queryByText('#p50')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('#p50');
  fireEvent.change(screen.getByLabelText('Estado del retiro'), { target: { value: 'COMPLETADO' } }); await screen.findByText('#p100');
  expect(requests).toEqual([{ limit: '51', offset: '0' }, { limit: '51', offset: '50' }, { status: 'COMPLETADO', limit: '51', offset: '0' }]);
});
it.each(['envelope', 'duplicate', 'ignored-filter'])('keeps the previously confirmed page after a malformed/contradictory HTTP page (%s)', async mode => {
  let calls = 0;
  client.defaults.adapter = async config => {
    calls++;
    if (calls === 1) return reply(config, rows(0, 51));
    return reply(config, mode === 'envelope' ? { items: rows(50, 1) } : mode === 'duplicate' ? [rows(50, 1)[0], rows(50, 1)[0]] : rows(50, 1, 'PENDIENTE'));
  };
  render(<Page />); await screen.findByText('#p0');
  if (mode === 'ignored-filter') fireEvent.change(screen.getByLabelText('Estado del retiro'), { target: { value: 'COMPLETADO' } });
  else fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByRole('alert'); expect(screen.getByText('#p0')).toBeInTheDocument(); expect(screen.getByText('Página 1')).toBeInTheDocument();
  expect(screen.getByLabelText('Estado del retiro')).toHaveValue('ALL');
});
it('detects an overlapping adjacent page even when the page itself is a valid unique HTTP array', async () => {
  client.defaults.adapter = async config => reply(config, new URL(String(config.url), 'https://test.invalid').searchParams.get('offset') === '50' ? rows(49, 51) : rows(0, 51));
  render(<Page />); await screen.findByText('#p0'); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('cambió entre páginas'); expect(screen.getByText('#p0')).toBeInTheDocument();
});
it('retires the continuation between the actual HTTP interceptor and the page after changing accounts', async () => {
  const requests: Array<{ token: string; offset: string | null }> = [];
  client.defaults.adapter = async config => {
    const offset = new URL(String(config.url), 'https://test.invalid').searchParams.get('offset');
    const token = String(config.headers.get('Authorization')); requests.push({ token, offset });
    return reply(config, token === 'Bearer access-b' ? rows(0, 1, 'PENDIENTE', 'b') : offset === '50' ? rows(50, 1) : rows(0, 51));
  };
  const hook = client.interceptors.response.use(response => {
    if (new URL(String(response.config.url), 'https://test.invalid').searchParams.get('offset') === '50') {
      mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-b', refresh_token: 'refresh-b' });
    }
    return response;
  });
  try {
    render(<Page />); await screen.findByText('#p0'); await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); });
    await screen.findByText('#b0'); expect(screen.queryByText('#p50')).not.toBeInTheDocument(); expect(screen.getByText('Página 1')).toBeInTheDocument();
    expect(requests).toEqual([{ token: 'Bearer access-a', offset: '0' }, { token: 'Bearer access-a', offset: '50' }, { token: 'Bearer access-b', offset: '0' }]);
  } finally { client.interceptors.response.eject(hook); }
});
