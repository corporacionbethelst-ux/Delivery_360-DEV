import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
const cursor50 = `c50.${'a'.repeat(64)}`;
const page = (items: unknown[], next_cursor: string | null = null) => ({ items, next_cursor });
const rows = (start: number, count: number, status = 'PENDIENTE', prefix = 'p') => Array.from({ length: count }, (_, i) => ({ id: `${prefix}${start + i}`, rider_id: 'r', amount: 10, total_amount: 10, status, method: 'EFECTIVO' }));
beforeEach(() => { clearStoredTokens(); mockUser = { id: 'a', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-a', refresh_token: 'refresh-a' }); });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = originalAdapter; });

it('navigates and filters through the actual Axios/API/service chain with opaque server continuations', async () => {
  const requests: Array<Record<string, string>> = [];
  client.defaults.adapter = async config => {
    const query = new URL(String(config.url), 'https://test.invalid').searchParams;
    requests.push(Object.fromEntries(query));
    expect(config.method).toBe('get'); expect(config.url).toContain('/payouts/page?'); expect(query.has('offset')).toBe(false);
    expect(config.headers.get('Authorization')).toBe('Bearer access-a');
    return reply(config, query.get('status') === 'COMPLETADO' ? page(rows(100, 1, 'COMPLETADO')) : query.get('cursor') === cursor50 ? page(rows(50, 1)) : page(rows(0, 50), cursor50));
  };
  render(<Page />); await screen.findByText('#p0'); expect(screen.queryByText('#p50')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('#p50');
  fireEvent.change(screen.getByLabelText('Estado del retiro'), { target: { value: 'COMPLETADO' } }); await screen.findByText('#p100');
  expect(requests).toEqual([{ limit: '50' }, { limit: '50', cursor: cursor50 }, { status: 'COMPLETADO', limit: '50' }]);
});
it.each(['envelope', 'duplicate', 'ignored-filter'])('keeps the previously confirmed page after a malformed/contradictory HTTP page (%s)', async mode => {
  let calls = 0;
  client.defaults.adapter = async config => {
    calls++;
    if (calls === 1) return reply(config, page(rows(0, 50), cursor50));
    return reply(config, mode === 'envelope' ? { items: rows(50, 1) } : mode === 'duplicate' ? page([rows(50, 1)[0], rows(50, 1)[0]]) : page(rows(50, 1, 'PENDIENTE')));
  };
  render(<Page />); await screen.findByText('#p0');
  if (mode === 'ignored-filter') fireEvent.change(screen.getByLabelText('Estado del retiro'), { target: { value: 'COMPLETADO' } });
  else fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByRole('alert'); expect(screen.getByText('#p0')).toBeInTheDocument(); expect(screen.getByText('Página 1')).toBeInTheDocument();
  expect(screen.getByLabelText('Estado del retiro')).toHaveValue('ALL');
});
it('detects an overlapping adjacent page even when the page itself is a valid unique HTTP page', async () => {
  client.defaults.adapter = async config => reply(config, new URL(String(config.url), 'https://test.invalid').searchParams.get('cursor') === cursor50 ? page(rows(49, 50), `c99.${'a'.repeat(64)}`) : page(rows(0, 50), cursor50));
  render(<Page />); await screen.findByText('#p0'); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('cambió entre páginas'); expect(screen.getByText('#p0')).toBeInTheDocument();
});
it('retires the continuation between the actual HTTP interceptor and the page after changing accounts', async () => {
  const requests: Array<{ token: string; cursor: string | null }> = [];
  client.defaults.adapter = async config => {
    const cursor = new URL(String(config.url), 'https://test.invalid').searchParams.get('cursor');
    const token = String(config.headers.get('Authorization')); requests.push({ token, cursor });
    return reply(config, token === 'Bearer access-b' ? page(rows(0, 1, 'PENDIENTE', 'b')) : cursor === cursor50 ? page(rows(50, 1)) : page(rows(0, 50), cursor50));
  };
  const hook = client.interceptors.response.use(response => {
    if (new URL(String(response.config.url), 'https://test.invalid').searchParams.get('cursor') === cursor50) {
      mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'access-b', refresh_token: 'refresh-b' });
    }
    return response;
  });
  try {
    render(<Page />); await screen.findByText('#p0'); await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); });
    await screen.findByText('#b0'); expect(screen.queryByText('#p50')).not.toBeInTheDocument(); expect(screen.getByText('Página 1')).toBeInTheDocument();
    expect(requests).toEqual([{ token: 'Bearer access-a', cursor: null }, { token: 'Bearer access-a', cursor: cursor50 }, { token: 'Bearer access-b', cursor: null }]);
  } finally { client.interceptors.response.eject(hook); }
});

it('retains a rejected continuation until an explicit retry or return to the beginning', async () => {
  const requests: Array<string | null> = [];
  client.defaults.adapter = async config => {
    const cursor = new URL(String(config.url), 'https://test.invalid').searchParams.get('cursor');
    requests.push(cursor);
    if (cursor) throw Object.assign(new Error('cursor no longer valid'), { response: { status: 400, data: { detail: 'Vuelve al inicio' } } });
    return reply(config, page(rows(0, 50), cursor50));
  };
  render(<Page />); await screen.findByText('#p0');
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByRole('alert');
  expect(screen.getByText('#p0')).toBeInTheDocument(); expect(requests).toEqual([null, cursor50]);
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' }));
  await screen.findByRole('alert'); expect(requests).toEqual([null, cursor50, cursor50]);
  fireEvent.click(screen.getByRole('button', { name: 'Volver al inicio' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Siguiente' })).toBeEnabled());
  expect(screen.getByText('#p0')).toBeInTheDocument(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(requests).toEqual([null, cursor50, cursor50, null]);
});
