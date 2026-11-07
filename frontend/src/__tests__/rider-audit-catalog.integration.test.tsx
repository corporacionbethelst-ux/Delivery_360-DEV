import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import Page from '@/app/(dashboard)/manager/operations/rider-audit/page';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditCatalogHttpResponse, auditCatalogResponse } from '../../test-fixtures/rider-audit-catalog';
const mockRouter = { replace: jest.fn() }; let mockUser = { id: 'a', role: 'GERENTE' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const original = client.defaults.adapter, originalRefresh = axios.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
beforeEach(() => { storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; axios.defaults.adapter = originalRefresh; });
it('navigates and filters through the actual Axios/API/service chain with bounded GET queries', async () => {
  const urls: string[] = []; client.defaults.adapter = async config => { expect(config.method).toBe('get'); expect(config.headers.get('Authorization')).toBe('Bearer a'); urls.push(String(config.url)); return reply(config, auditCatalogHttpResponse(String(config.url))); };
  render(<Page />); await screen.findByRole('region', { name: 'Página de auditoría confirmada' }); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByRole('article', { name: 'Auditoría de rider-50' });
  fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'INACTIVO' } }); await screen.findByText('Consulta confirmada: estado INACTIVO; disponibilidad Todos.');
  fireEvent.change(screen.getByLabelText('Disponibilidad en el servidor'), { target: { value: 'false' } }); await screen.findByText('Consulta confirmada: estado INACTIVO; disponibilidad Offline.'); expect(urls).toEqual(['/riders/audit/summary?limit=51&offset=0', '/riders/audit/summary?limit=51&offset=50', '/riders/audit/summary?status_filter=INACTIVO&limit=51&offset=0', '/riders/audit/summary?status_filter=INACTIVO&is_online=false&limit=51&offset=0']);
});
it('fences the interceptor continuation gap before old-account data can publish', async () => {
  client.defaults.adapter = async config => reply(config, auditCatalogResponse(0, 1, { rider_id: config.headers.get('Authorization') === 'Bearer b' ? 'current-b' : 'retired-a' })); let switched = false;
  const interceptor = client.interceptors.response.use(response => { if (!switched) { switched = true; mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); } return response; });
  try { await act(async () => { render(<Page />); }); await screen.findByRole('article', { name: 'Auditoría de current-b' }); expect(screen.queryByRole('article', { name: 'Auditoría de retired-a' })).not.toBeInTheDocument(); }
  finally { client.interceptors.response.eject(interceptor); }
});
it('keeps verified same-account token refresh valid for the catalog', async () => {
  client.defaults.adapter = async config => { if (config.headers.get('Authorization') === 'Bearer a') throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, { ...reply(config, {}), status: 401 }); return reply(config, auditCatalogResponse()); };
  axios.defaults.adapter = async config => reply(config, { access_token: 'rotated-a', refresh_token: 'rotated-ra' }); render(<Page />); await screen.findByRole('article'); expect(localStorage.getItem('access_token')).toBe('rotated-a');
});
it('rejects a later HTTP response outside the selected filter without replacing the confirmed page', async () => {
  client.defaults.adapter = async config => reply(config, auditCatalogResponse()); render(<Page />); await screen.findByRole('article');
  fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'SUSPENDIDO' } }); await screen.findByRole('alert'); expect(screen.getByText('Consulta confirmada: estado ALL; disponibilidad Todos.')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeDisabled(); expect(screen.getByRole('article')).toBeInTheDocument();
});
it('lets a new refresh win even when a retired HTTP response arrives later', async () => {
  let retiredConfig!: InternalAxiosRequestConfig; let calls = 0, resolve!: (v: ReturnType<typeof reply>) => void;
  client.defaults.adapter = async config => { calls++; if (calls === 2) { retiredConfig = config; return new Promise(done => { resolve = done; }); } return reply(config, auditCatalogResponse(0, 1, { full_name: calls === 1 ? 'Initial' : 'Newest' })); };
  render(<Page />); await screen.findByText('Initial', { exact: true }); fireEvent.click(screen.getByRole('button', { name: 'Actualizar consulta' })); await act(async () => {}); fireEvent.click(screen.getByRole('button', { name: 'Actualizar consulta' })); await screen.findByText('Newest', { exact: true });
  await act(async () => { resolve(reply(retiredConfig, auditCatalogResponse(0, 1, { full_name: 'Retired' }))); }); expect(screen.queryByText('Retired', { exact: true })).not.toBeInTheDocument(); expect(screen.getByText('Newest', { exact: true })).toBeInTheDocument();
});
