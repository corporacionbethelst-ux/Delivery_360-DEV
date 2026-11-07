import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import Page from '@/app/(dashboard)/manager/financial/resumen/page';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { summaryResponse } from '../../test-fixtures/financial-summary';

const mockRouter = { replace: jest.fn() };
let mockUser = { id: 'a', role: 'GERENTE' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const original = client.defaults.adapter, originalRefresh = axios.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
beforeEach(() => { clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; axios.defaults.adapter = originalRefresh; });

it('queries the selected server periods through the actual Axios/API/service chain', async () => {
  const requests: string[] = [];
  client.defaults.adapter = async config => {
    expect(config.headers.get('Authorization')).toBe('Bearer a'); expect(config.method).toBe('get');
    requests.push(String(config.url)); const period = new URL(String(config.url), 'https://test.invalid').searchParams.get('period') as 'week' | 'month';
    return reply(config, summaryResponse(period));
  };
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByText('Datos confirmados: Mes');
  expect(requests).toEqual(['/financial/summary?period=week', '/financial/summary?period=month']);
});
it('retires the continuation after the HTTP interceptor accepts it but before the page publishes it', async () => {
  client.defaults.adapter = async config => reply(config, summaryResponse(String(config.url).includes('month') ? 'month' : 'week', config.headers.get('Authorization') === 'Bearer b' ? { total_revenue: 777, net_margin: 737 } : {}));
  const interceptor = client.interceptors.response.use(response => {
    if (String(response.config.url).includes('month')) {
      mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' });
    }
    return response;
  });
  try {
    render(<Page />); await screen.findByText('Datos confirmados: Semana');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Mes' })); });
    await screen.findAllByText('777,00 (moneda no informada)');
    expect(screen.getByText('Datos confirmados: Semana')).toBeInTheDocument(); expect(screen.queryByText('Datos confirmados: Mes')).not.toBeInTheDocument();
  } finally { client.interceptors.response.eject(interceptor); }
});
it('continues a verified same-account token refresh without discarding the selected period', async () => {
  const requests: string[] = [];
  client.defaults.adapter = async config => {
    const token = String(config.headers.get('Authorization')); requests.push(`${config.url} ${token}`);
    if (String(config.url).includes('month') && token === 'Bearer a') throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, { ...reply(config, {}), status: 401 });
    return reply(config, summaryResponse(String(config.url).includes('month') ? 'month' : 'week'));
  };
  axios.defaults.adapter = async config => reply(config, { access_token: 'rotated-a', refresh_token: 'rotated-ra' });
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByText('Datos confirmados: Mes');
  expect(localStorage.getItem('access_token')).toBe('rotated-a');
  expect(requests).toEqual(['/financial/summary?period=week Bearer a', '/financial/summary?period=month Bearer a', '/financial/summary?period=month Bearer rotated-a']);
});
it.each(['http-error', 'contradictory'])('preserves confirmed data after an HTTP/validation failure (%s)', async mode => {
  client.defaults.adapter = async config => {
    if (String(config.url).includes('month')) {
      if (mode === 'http-error') throw new AxiosError('unavailable', AxiosError.ERR_BAD_RESPONSE, config, undefined, { ...reply(config, {}), status: 500 });
      return reply(config, summaryResponse('month', { net_margin: 999 }));
    }
    return reply(config, summaryResponse('week'));
  };
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByRole('alert');
  expect(screen.getByText('Datos confirmados: Semana')).toBeInTheDocument();
  expect(screen.getAllByText('100,00 (moneda no informada)').length).toBeGreaterThan(0);
});
