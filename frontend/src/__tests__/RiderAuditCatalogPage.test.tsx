import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/operations/rider-audit/page';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditCatalogHttpResponse, auditCatalogResponse } from '../../test-fixtures/rider-audit-catalog';
const mockRouter = { replace: jest.fn() }; let mockUser: { id: string; role: string } | null = { id: 'a', role: 'GERENTE' }, mockAuthenticated = true;
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; mockAuthenticated = true; get.mockImplementation(async url => auditCatalogHttpResponse(url, 1)); download.mockReturnValue(true); });
afterEach(() => clearStoredTokens());
it('shows real rider/user IDs, faithful money and a correctly encoded detail link', async () => {
  get.mockResolvedValue(auditCatalogResponse(0, 1, { rider_id: 'rider/a?x=1', user_id: 'actual-user', total_earned: 0, pending_payouts: 0, available_to_payout: 0 })); render(<Page />); const article = await screen.findByRole('article', { name: 'Auditoría de rider/a?x=1' });
  expect(within(article).getByText('ID usuario: actual-user')).toBeInTheDocument(); expect(within(article).getAllByText('0,00 (moneda no informada)')).toHaveLength(2); expect(screen.getByRole('link', { name: 'Ver auditoría de rider/a?x=1' })).toHaveAttribute('href', '/manager/operations/rider-audit/rider%2Fa%3Fx%3D1'); expect(screen.queryByText(/COP|USD/)).not.toBeInTheDocument();
});
it('distinguishes unknown availability from Offline and keeps unknown metadata/dates visible', async () => {
  get.mockResolvedValue(auditCatalogResponse(0, 1, { is_online: null, status: null, vehicle_type: null, vehicle_plate: null, operating_zone: null, last_location_at: null })); render(<Page />); await screen.findByRole('article'); expect(screen.getByText('0 · 1 sin información')).toBeInTheDocument(); expect(within(screen.getByRole('article')).queryByText('Offline', { exact: true })).not.toBeInTheDocument(); expect(screen.getByText('Fecha no informada')).toBeInTheDocument(); expect(screen.getByText('0, 0', { exact: true })).toBeInTheDocument();
});
it('restricts metrics and CSV to page search matches without another GET', async () => {
  get.mockResolvedValue(auditCatalogResponse(0, 2)); render(<Page />); await screen.findByRole('region', { name: 'Página de auditoría confirmada' });
  fireEvent.change(screen.getByLabelText('Buscar solo en esta página'), { target: { value: 'PLACA-1' } }); expect(screen.getAllByRole('article')).toHaveLength(1); const metrics = screen.getByRole('region', { name: 'Métricas de las coincidencias de esta página' }); expect(within(metrics).getByText('Órdenes activas de las coincidencias').parentElement).toHaveTextContent('4');
  fireEvent.click(screen.getByRole('button', { name: 'Exportar página CSV' })); expect(download).toHaveBeenCalledWith([expect.objectContaining({ id_rider: 'rider-1', id_usuario: 'user-rider-1', busqueda_local: 'PLACA-1' })], expect.any(String)); expect(get).toHaveBeenCalledTimes(1);
});
it('does not let a search with no matches hide page navigation or export an empty file', async () => {
  get.mockImplementation(async url => auditCatalogHttpResponse(url)); render(<Page />); await screen.findByRole('region', { name: 'Página de auditoría confirmada' }); fireEvent.change(screen.getByLabelText('Buscar solo en esta página'), { target: { value: 'rider-50' } }); expect(screen.getByText(/Sin coincidencias en esta página/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByRole('article', { name: 'Auditoría de rider-50' }); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeEnabled();
});
it('preserves a confirmed page on filter failure, labels its query, and disables export until retry', async () => {
  render(<Page />); await screen.findByRole('article'); get.mockRejectedValueOnce(new Error('offline'));
  fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'INACTIVO' } }); await screen.findByRole('alert'); expect(screen.getByText('Consulta confirmada: estado ALL; disponibilidad Todos.')).toBeInTheDocument(); expect(screen.getByLabelText('Estado en el servidor')).toHaveValue('ALL'); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText('Consulta confirmada: estado INACTIVO; disponibilidad Todos.'); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeEnabled();
});
it('sends status and explicit Offline as server filters and labels only confirmed data', async () => {
  render(<Page />); await screen.findByRole('article'); fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'SUSPENDIDO' } }); await screen.findByText('Consulta confirmada: estado SUSPENDIDO; disponibilidad Todos.');
  fireEvent.change(screen.getByLabelText('Disponibilidad en el servidor'), { target: { value: 'false' } }); await screen.findByText('Consulta confirmada: estado SUSPENDIDO; disponibilidad Offline.'); expect(get).toHaveBeenLastCalledWith('/riders/audit/summary?status_filter=SUSPENDIDO&is_online=false&limit=51&offset=0');
});
it('distinguishes a cold read failure from an empty successful page', async () => {
  get.mockRejectedValueOnce(new Error('offline')); render(<Page />); await screen.findByRole('alert'); expect(screen.queryByText(/No hay repartidores/)).not.toBeInTheDocument(); expect(screen.queryByRole('region', { name: 'Página de auditoría confirmada' })).not.toBeInTheDocument();
  get.mockResolvedValue(auditCatalogResponse(0, 0)); fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText('No hay repartidores en esta página de la consulta.');
});
it('shows CSV failure without losing the confirmed data and allows another download attempt', async () => {
  render(<Page />); await screen.findByRole('article'); download.mockImplementationOnce(() => { throw new Error('blocked'); }); fireEvent.click(screen.getByRole('button', { name: 'Exportar página CSV' })); await screen.findByRole('alert'); expect(screen.getByRole('article')).toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: 'Exportar página CSV' })); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('resets private search and data before the next account response arrives', async () => {
  render(<Page />); await screen.findByRole('article'); fireEvent.change(screen.getByLabelText('Buscar solo en esta página'), { target: { value: 'José' } }); let resolve!: (v: unknown) => void; const pending = new Promise(r => { resolve = r; }); get.mockReturnValueOnce(pending);
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); }); expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(screen.getByLabelText('Buscar solo en esta página')).toHaveValue('');
  await act(async () => { resolve(auditCatalogResponse(0, 1, { rider_id: 'current-b' })); }); await screen.findByRole('article', { name: 'Auditoría de current-b' });
});
it.each(['ADMIN', 'OPERADOR', 'REPARTIDOR'])('does not mount private catalog reads for %s', role => { mockUser = { id: 'a', role }; render(<Page />); expect(get).not.toHaveBeenCalled(); expect(mockRouter.replace).toHaveBeenCalledWith('/login'); });
it('does not mount private catalog reads while logged out', () => { mockAuthenticated = false; mockUser = null; render(<Page />); expect(get).not.toHaveBeenCalled(); });
