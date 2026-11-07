import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import History from '@/app/(dashboard)/manager/financial/transactions/page';
import Detail from '@/app/(dashboard)/manager/financial/transactions/[id]/page';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { transactionResponse, transactionRows } from '../../test-fixtures/transactions';
const mockRouter = { replace: jest.fn() }; let mockUser = { id: 'a', role: 'GERENTE' }, mockParams = { id: 'tx-1' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => mockParams }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const original = client.defaults.adapter, originalRefresh = axios.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
beforeEach(() => { clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; mockParams = { id: 'tx-1' }; });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; axios.defaults.adapter = originalRefresh; });
it('navigates and filters through the actual Axios/API/service chain with bounded GET queries', async () => {
  const requests: string[] = [];
  client.defaults.adapter = async config => {
    expect(config.method).toBe('get'); expect(config.headers.get('Authorization')).toBe('Bearer a'); requests.push(String(config.url));
    const q = new URL(String(config.url), 'https://test.invalid').searchParams;
    return reply(config, q.get('type') === 'STRIPE_INSTANT' ? transactionRows(200, 1, { type: 'STRIPE_INSTANT', transaction_type: 'STRIPE_INSTANT' }) : q.get('offset') === '50' ? transactionRows(50, 1) : transactionRows(0, 51));
  };
  render(<History />); await screen.findByRole('region', { name: 'Página confirmada' }); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('tx-50', { exact: true });
  fireEvent.change(screen.getByLabelText('Tipo en el servidor'), { target: { value: 'STRIPE_INSTANT' } }); await screen.findByText('tx-200', { exact: true }); expect(requests).toEqual(['/financial/transactions?limit=51&offset=0', '/financial/transactions?limit=51&offset=50', '/financial/transactions?type=STRIPE_INSTANT&limit=51&offset=0']);
});
it.each(['history', 'detail'])('fences the actual interceptor continuation gap for %s', async kind => {
  client.defaults.adapter = async config => reply(config, kind === 'history' ? transactionRows(config.headers.get('Authorization') === 'Bearer b' ? 200 : 0, 1) : transactionResponse('tx-1', { description: config.headers.get('Authorization') === 'Bearer b' ? 'Current B' : 'Retired A' }));
  let switched = false;
  const interceptor = client.interceptors.response.use(response => { if (!switched) { switched = true; mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); } return response; });
  try {
    await act(async () => { render(kind === 'history' ? <History /> : <Detail />); });
    if (kind === 'history') { await screen.findByText('tx-200', { exact: true }); expect(screen.queryByText('tx-0', { exact: true })).not.toBeInTheDocument(); }
    else { await screen.findByText('Current B'); expect(screen.queryByText('Retired A')).not.toBeInTheDocument(); }
  } finally { client.interceptors.response.eject(interceptor); }
});
it('keeps an ordinary same-account refresh valid while reading a detail', async () => {
  client.defaults.adapter = async config => {
    if (config.headers.get('Authorization') === 'Bearer a') throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, { ...reply(config, {}), status: 401 });
    return reply(config, transactionResponse());
  };
  axios.defaults.adapter = async config => reply(config, { access_token: 'rotated-a', refresh_token: 'rotated-ra' });
  render(<Detail />); await screen.findByText('ID confirmado: tx-1'); expect(localStorage.getItem('access_token')).toBe('rotated-a');
});
it('retains the detail snapshot when a later HTTP response identifies another record', async () => {
  let calls = 0; client.defaults.adapter = async config => reply(config, transactionResponse(++calls === 1 ? 'tx-1' : 'wrong'));
  render(<Detail />); await screen.findByText('ID confirmado: tx-1'); fireEvent.click(screen.getByRole('button', { name: 'Consultar transacción' })); await screen.findByRole('alert'); expect(screen.getByText('ID confirmado: tx-1')).toBeInTheDocument(); expect(screen.queryByText('ID confirmado: wrong')).not.toBeInTheDocument();
});
