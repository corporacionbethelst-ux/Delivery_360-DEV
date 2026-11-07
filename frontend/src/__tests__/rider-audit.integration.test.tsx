import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import client from '@/lib/api';
import Page from '@/app/(dashboard)/manager/operations/rider-audit/[id]/page';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditHttpResponse, auditOrderResponse, auditSummaryPage, auditSummaryResponse } from '../../test-fixtures/rider-audit';
const mockRouter = { replace: jest.fn() }; let mockUser = { id: 'a', role: 'GERENTE' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => ({ id: 'rider-1' }) }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
const original = client.defaults.adapter, originalRefresh = axios.defaults.adapter;
const reply = (config: InternalAxiosRequestConfig, data: unknown) => ({ config, data, status: 200, statusText: 'OK', headers: new AxiosHeaders() });
beforeEach(() => { storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; });
afterEach(() => { clearStoredTokens(); client.defaults.adapter = original; axios.defaults.adapter = originalRefresh; });
it('uses the real Axios/API chain for independent bounded navigation and actual HTTP envelopes', async () => {
  const urls: string[] = []; client.defaults.adapter = async config => { expect(config.method).toBe('get'); expect(config.headers.get('Authorization')).toBe('Bearer a'); urls.push(String(config.url)); return reply(config, auditHttpResponse(String(config.url))); };
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' });
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Páginas de Entregas registradas del repartidor' })).getByRole('button', { name: 'Siguiente' }));
  await screen.findByText('d-50', { exact: true }); expect(urls).toHaveLength(8); expect(urls[6]).toBe('/deliveries?rider_id=rider-1&limit=51&offset=50&include_total=true');
  expect(screen.getByRole('link', { name: 'Ver orden o-0' })).toBeInTheDocument();
});
it('retires the interceptor continuation gap when another account takes over', async () => {
  client.defaults.adapter = async config => { const url = String(config.url); return reply(config, url.startsWith('/orders') ? [auditOrderResponse(config.headers.get('Authorization') === 'Bearer b' ? 'current-b' : 'retired-a')] : auditHttpResponse(url, 1)); };
  let switched = false;
  const interceptor = client.interceptors.response.use(response => { if (!switched) { switched = true; mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); } return response; });
  try { await act(async () => { render(<Page />); }); await screen.findByRole('link', { name: 'Ver orden current-b' }); expect(screen.queryByRole('link', { name: 'Ver orden retired-a' })).not.toBeInTheDocument(); }
  finally { client.interceptors.response.eject(interceptor); }
});
it('allows verified same-account credential refresh while assembling the set', async () => {
  client.defaults.adapter = async config => { if (config.headers.get('Authorization') === 'Bearer a') throw new AxiosError('expired', AxiosError.ERR_BAD_REQUEST, config, undefined, { ...reply(config, {}), status: 401 }); return reply(config, auditHttpResponse(String(config.url), 1)); };
  axios.defaults.adapter = async config => reply(config, { access_token: 'rotated-a', refresh_token: 'rotated-ra' });
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' }); expect(localStorage.getItem('access_token')).toBe('rotated-a');
});
it('rejects another rider in a later HTTP response and preserves every confirmed block', async () => {
  let wrong = false; client.defaults.adapter = async config => reply(config, wrong && String(config.url).startsWith('/orders') ? [auditOrderResponse('wrong', 'another-rider')] : auditHttpResponse(String(config.url), 1));
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' }); wrong = true;
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar auditoría' })); await screen.findByRole('alert'); expect(screen.getByRole('link', { name: 'Ver orden o-0' })).toBeInTheDocument(); expect(screen.queryByRole('link', { name: 'Ver orden wrong' })).not.toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Ver transacción tx-0' })).toBeInTheDocument();
});
it('continues summary pagination through the real chain without treating the page count as a global total', async () => {
  const summaries: string[] = []; client.defaults.adapter = async config => {
    const url = String(config.url); if (url.startsWith('/riders/')) { summaries.push(url); const offset = Number(new URL(url, 'https://test.invalid').searchParams.get('offset')); return reply(config, auditSummaryPage(offset === 0 ? Array.from({ length: 100 }, (_, i) => auditSummaryResponse(`other-${i}`)) : [auditSummaryResponse()], offset)); }
    return reply(config, auditHttpResponse(url, 1));
  };
  render(<Page />); await screen.findByText('José Rider', { exact: true }); expect(summaries).toEqual(['/riders/audit/summary?limit=100&offset=0', '/riders/audit/summary?limit=100&offset=100']);
});
