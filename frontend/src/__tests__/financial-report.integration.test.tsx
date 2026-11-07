import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import Page from '@/app/(dashboard)/manager/financial/reports/page';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { ordersResponse, reconciliationResponse, reportRow } from '../../test-fixtures/financial-reports';

const mockRouter = { replace: jest.fn() }; let mockUser = { id: 'a', role: 'GERENTE' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const original = client.defaults.adapter, originalRefresh = axios.defaults.adapter, download = jest.mocked(downloadCSV);
const response = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
const payload = (url: string) => { const params = new URL(url, 'https://test.invalid').searchParams; const range = { date_from: params.get('date_from') ?? undefined, date_to: params.get('date_to') ?? undefined }; return url.includes('/reports/orders') ? ordersResponse(range) : reconciliationResponse(range); };
beforeEach(() => { jest.clearAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; download.mockReturnValue(true); });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; axios.defaults.adapter = originalRefresh; });

it('reads and exports one confirmed range through actual Axios/API/service, using only GETs for reports', async () => {
  const requests: string[] = [];
  client.defaults.adapter = async config => { expect(config.method).toBe('get'); expect(config.headers.get('Authorization')).toBe('Bearer a'); requests.push(String(config.url)); return response(config, payload(String(config.url))); };
  render(<Page />); await screen.findByRole('region', { name: 'Reporte confirmado' });
  fireEvent.change(screen.getByLabelText('Fecha inicio'), { target: { value: '2026-11-01' } }); fireEvent.click(screen.getByRole('button', { name: 'Aplicar consulta' })); await screen.findByText(/Rango confirmado: 2026-11-01/);
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); await screen.findByText(/CSV generado/);
  expect(requests.slice(-2)).toEqual(['/financial/reports/orders?date_from=2026-11-01&limit=5000&offset=0', '/financial/reconciliation?date_from=2026-11-01']); expect(download).toHaveBeenCalledTimes(1);
});
it('retires an export continuation between the real HTTP interceptor and the page after an account change', async () => {
  client.defaults.adapter = async config => response(config, config.headers.get('Authorization') === 'Bearer b' && String(config.url).includes('/reports/orders') ? ordersResponse({}, { rows: [reportRow('b', { external_id: 'Only-B' })] }) : payload(String(config.url)));
  const interceptor = client.interceptors.response.use(result => {
    if (String(result.config.url).includes('limit=5000')) { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); }
    return result;
  });
  try {
    render(<Page />); await screen.findByRole('region', { name: 'Reporte confirmado' });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); }); await screen.findByText('Only-B');
    expect(download).not.toHaveBeenCalled(); expect(screen.queryByText('EXT-1')).not.toBeInTheDocument();
  } finally { client.interceptors.response.eject(interceptor); }
});
it('keeps a same-account token refresh valid while preparing the export', async () => {
  client.defaults.adapter = async config => {
    if (String(config.url).includes('limit=5000') && config.headers.get('Authorization') === 'Bearer a') throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, { ...response(config, {}), status: 401 });
    return response(config, payload(String(config.url)));
  };
  axios.defaults.adapter = async config => response(config, { access_token: 'rotated-a', refresh_token: 'rotated-ra' });
  render(<Page />); await screen.findByRole('region', { name: 'Reporte confirmado' }); fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); await screen.findByText(/CSV generado/);
  expect(download).toHaveBeenCalledTimes(1); expect(localStorage.getItem('access_token')).toBe('rotated-a');
});
it('does not download or erase the confirmed pair after an actual HTTP export failure, then retries deliberately', async () => {
  let fail = false;
  client.defaults.adapter = async config => {
    if (fail && String(config.url).includes('/reconciliation')) throw new AxiosError('unavailable', AxiosError.ERR_BAD_RESPONSE, config, undefined, { ...response(config, {}), status: 503 });
    return response(config, payload(String(config.url)));
  };
  render(<Page />); await screen.findByRole('region', { name: 'Reporte confirmado' }); fail = true; fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); await screen.findByRole('alert');
  expect(download).not.toHaveBeenCalled(); expect(screen.getByRole('region', { name: 'Reporte confirmado' })).toBeInTheDocument();
  fail = false; fireEvent.click(screen.getByRole('button', { name: 'Reintentar exportación' })); await screen.findByText(/CSV generado/); expect(download).toHaveBeenCalledTimes(1);
});
