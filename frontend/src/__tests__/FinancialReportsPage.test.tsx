import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/financial/reports/page';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { emptyOrders, emptyReconciliation, ordersResponse, reconciliationResponse, reportRow } from '../../test-fixtures/financial-reports';

const mockRouter = { replace: jest.fn() };
let mockUser = { id: 'a', role: 'GERENTE' }, mockAuthenticated = true;
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
const query = (url: string) => { const q = new URL(url, 'https://test.invalid').searchParams; return { date_from: q.get('date_from') ?? undefined, date_to: q.get('date_to') ?? undefined }; };
const reply = (url: string) => url.includes('/reports/orders') ? ordersResponse(query(url)) : reconciliationResponse(query(url));
function deferred() { let resolve!: (value: unknown) => void; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; mockAuthenticated = true; get.mockImplementation(async url => reply(url)); download.mockReturnValue(true); });
afterEach(() => clearStoredTokens());
const loaded = () => screen.findByRole('region', { name: 'Reporte confirmado' });

it('distinguishes order totals from paid-delivery reconciliation and does not invent order currency', async () => {
  render(<Page />); await loaded();
  expect(screen.getByText('order-1')).toBeInTheDocument();
  expect(screen.getByText('Moneda no informada para órdenes')).toBeInTheDocument(); expect(screen.getByText('Moneda informada: COP')).toBeInTheDocument();
  expect(screen.getByText(/Los importes de órdenes no equivalen a ingresos cobrados/)).toBeInTheDocument();
  expect(screen.getByText(/no certifican transferencias bancarias/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeEnabled();
});
it('does not show fictitious zero statistics on an initial failure and recovers via retry', async () => {
  get.mockRejectedValue(new Error('offline')); render(<Page />); await screen.findByRole('alert');
  expect(screen.queryByRole('region', { name: 'Reporte confirmado' })).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeDisabled();
  get.mockImplementation(async url => reply(url)); fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await loaded();
});
it('shows genuine empty data without a CSV download', async () => {
  get.mockImplementation(async url => url.includes('/reports/orders') ? ordersResponse({}, emptyOrders) : reconciliationResponse({}, emptyReconciliation));
  render(<Page />); await screen.findByText('No hay órdenes en el rango confirmado.');
  expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeDisabled(); expect(download).not.toHaveBeenCalled();
});
it('keeps draft dates distinct from the confirmed range and requires applying before export', async () => {
  render(<Page />); await loaded();
  fireEvent.change(screen.getByLabelText('Fecha inicio'), { target: { value: '2026-11-01' } });
  expect(get).toHaveBeenCalledTimes(2); expect(screen.getByText(/Rango confirmado: sin límite inicial/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar consulta' })); await screen.findByText(/Rango confirmado: 2026-11-01/);
  expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeEnabled();
});
it('retains both confirmed datasets on a failed apply and retries its original filters', async () => {
  render(<Page />); await loaded(); fireEvent.change(screen.getByLabelText('Fecha inicio'), { target: { value: '2026-11-01' } });
  get.mockRejectedValue(new Error('failed')); fireEvent.click(screen.getByRole('button', { name: 'Aplicar consulta' })); await screen.findByRole('alert');
  expect(screen.getByText(/Rango confirmado: sin límite inicial/)).toBeInTheDocument();
  get.mockImplementation(async url => reply(url)); fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText(/Rango confirmado: 2026-11-01/);
});
it('does not mix an updated order report with the old reconciliation during export', async () => {
  render(<Page />); await loaded();
  get.mockImplementation(async url => url.includes('/reports/orders') ? ordersResponse({}, { total_revenue: 20, rows: [reportRow('changed', { delivery_fee: 20 })] }) : Promise.reject(new Error('reconciliation failed')));
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); await screen.findByRole('alert');
  expect(screen.getByText('EXT-1')).toBeInTheDocument(); expect(download).not.toHaveBeenCalled();
});
it('cancels a pending CSV when dates are edited and never downloads the old data later', async () => {
  const pending = deferred(); render(<Page />); await loaded();
  get.mockImplementation(url => url.includes('/reports/orders') ? pending.promise : Promise.resolve(reconciliationResponse()));
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' }));
  fireEvent.change(screen.getByLabelText('Fecha fin'), { target: { value: '2026-11-07' } });
  await screen.findByText(/La exportación se canceló/); await act(async () => { pending.resolve(ordersResponse()); });
  expect(download).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeDisabled();
});
it('uses only the applied range in CSV rows and filename and preserves absent payment fields', async () => {
  render(<Page />); await loaded(); fireEvent.change(screen.getByLabelText('Fecha inicio'), { target: { value: '2026-11-01' } }); fireEvent.change(screen.getByLabelText('Fecha fin'), { target: { value: '2026-11-07' } });
  fireEvent.click(screen.getByRole('button', { name: 'Aplicar consulta' })); await screen.findByText(/Rango confirmado: 2026-11-01/);
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' })); await screen.findByText(/CSV generado con 1 orden/);
  expect(download.mock.calls[0][1]).toContain('2026-11-01_2026-11-07_1_filas');
  expect(download.mock.calls[0][0][0]).toMatchObject({ id_orden: 'order-1', metodo_pago: '', moneda: '', rango_desde_utc: '2026-11-01T00:00:00Z' });
});
it('clears retired account data and blocks an old pending export after switching accounts', async () => {
  const old = deferred(); render(<Page />); await loaded();
  get.mockImplementation(url => url.includes('limit=5000') ? old.promise : Promise.resolve(url.includes('/reports/orders') ? ordersResponse({}, { rows: [reportRow('private-b', { external_id: 'B-ref' })] }) : reconciliationResponse()));
  fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' }));
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await screen.findByText('B-ref'); await act(async () => { old.resolve(ordersResponse()); });
  expect(screen.queryByText('EXT-1')).not.toBeInTheDocument(); expect(download).not.toHaveBeenCalled();
});
it('clears the snapshot when the role changes even without a token generation change', async () => {
  const pending = deferred(); const view = render(<Page />); await loaded();
  get.mockReturnValue(pending.promise); mockUser = { id: 'a', role: 'SUPERADMIN' }; view.rerender(<Page />);
  expect(screen.queryByRole('region', { name: 'Reporte confirmado' })).not.toBeInTheDocument();
  view.unmount(); await act(async () => { pending.resolve(ordersResponse()); });
});
it.each(['OPERADOR', 'REPARTIDOR', 'CLIENTE'])('does not query management reports as %s', async role => {
  mockUser = { id: 'a', role }; render(<Page />); await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/login')); expect(get).not.toHaveBeenCalled();
});
it('does not query reports when authentication is absent', () => {
  mockAuthenticated = false; render(<Page />); expect(get).not.toHaveBeenCalled();
});
