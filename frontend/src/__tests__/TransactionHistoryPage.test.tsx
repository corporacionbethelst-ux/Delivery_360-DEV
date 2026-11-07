import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/financial/transactions/page';
import { api } from '@/lib/api';
import { downloadCSV } from '@/lib/csv-export';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { transactionRows } from '../../test-fixtures/transactions';
const mockRouter = { replace: jest.fn() }; let mockUser = { id: 'a', role: 'GERENTE' }, mockAuthenticated = true;
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/csv-export', () => ({ downloadCSV: jest.fn(() => true) }));
const get = jest.mocked(api.get), download = jest.mocked(downloadCSV);
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockUser = { id: 'a', role: 'GERENTE' }; mockAuthenticated = true; download.mockReturnValue(true); });
afterEach(() => clearStoredTokens());
it('reaches records beyond the first 50 and does not expose the lookahead before navigating', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 1)); render(<Page />); await screen.findByRole('region', { name: 'Página confirmada' });
  expect(screen.queryByText('tx-50', { exact: true })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('tx-50', { exact: true }); expect(screen.getByText('Página 2')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
});
it('keeps local search navigable and restricts the CSV to visible matches on its current page', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 1)); render(<Page />); await screen.findByRole('region', { name: 'Página confirmada' });
  fireEvent.change(screen.getByLabelText('Buscar solo en esta página'), { target: { value: 'tx-50' } });
  expect(screen.getByText(/Sin coincidencias en esta página/)).toBeInTheDocument(); expect(get).toHaveBeenCalledTimes(1); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('tx-50', { exact: true }); fireEvent.click(screen.getByRole('button', { name: 'Exportar página CSV' }));
  expect(download.mock.calls[0][0]).toHaveLength(1); expect(download.mock.calls[0][0][0]).toMatchObject({ id: 'tx-50', desplazamiento_consulta: 50, busqueda_local: 'tx-50' });
});
it('queries new backend types and canonical statuses rather than silently filtering one initial batch', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 1)).mockResolvedValueOnce(transactionRows(20, 1, { type: 'BANK_TRANSFER', transaction_type: 'BANK_TRANSFER' })).mockResolvedValueOnce(transactionRows(30, 1, { type: 'BANK_TRANSFER', transaction_type: 'BANK_TRANSFER', status: 'PENDIENTE' }));
  render(<Page />); await screen.findByRole('region', { name: 'Página confirmada' });
  fireEvent.change(screen.getByLabelText('Tipo en el servidor'), { target: { value: 'BANK_TRANSFER' } }); await screen.findByText('tx-20', { exact: true });
  fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'PENDIENTE' } }); await screen.findByText('tx-30', { exact: true });
  expect(get).toHaveBeenLastCalledWith('/financial/transactions?type=BANK_TRANSFER&status=PENDIENTE&limit=51&offset=0');
});
it('does not invent COP/USD or a credit sign for a positive withdrawal', async () => {
  get.mockResolvedValue(transactionRows(0, 1, { type: 'RETIRO', transaction_type: 'RETIRO', amount: 20, created_at: null })); render(<Page />); await screen.findByText('20,00 (moneda no informada)');
  expect(screen.queryByText(/\+20|USD|COP/)).not.toBeInTheDocument(); expect(screen.getByText('Fecha no informada')).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Ver transacción tx-0' })).toHaveAttribute('href', '/manager/financial/transactions/tx-0');
});
it('retains the actual state after a failed filter and blocks CSV until recovery', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 1)).mockRejectedValueOnce(new Error('failed')).mockResolvedValueOnce(transactionRows(0, 1, { status: 'PAGADO' })); render(<Page />); await screen.findByRole('region', { name: 'Página confirmada' });
  fireEvent.change(screen.getByLabelText('Estado en el servidor'), { target: { value: 'PAGADO' } }); await screen.findByRole('alert'); expect(screen.getByLabelText('Estado en el servidor')).toHaveValue('ALL'); expect(screen.getByRole('button', { name: 'Exportar página CSV' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await waitFor(() => expect(screen.getByLabelText('Estado en el servidor')).toHaveValue('PAGADO'));
});
it('distinguishes a first read failure from a measured empty page', async () => {
  get.mockRejectedValue(new Error('unknown')); render(<Page />); await screen.findByRole('alert'); expect(screen.getByText(/No se pudo comprobar el historial/)).toBeInTheDocument(); expect(screen.queryByText('No hay transacciones en esta página de la consulta.')).not.toBeInTheDocument();
});
it('clears search, navigation and private rows when credentials change', async () => {
  get.mockResolvedValueOnce(transactionRows(0, 51)).mockResolvedValueOnce(transactionRows(50, 1)).mockResolvedValueOnce(transactionRows(200, 1)); render(<Page />); await screen.findByRole('region', { name: 'Página confirmada' });
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('Página 2'); fireEvent.change(screen.getByLabelText('Buscar solo en esta página'), { target: { value: 'old search' } });
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await screen.findByText('tx-200', { exact: true }); expect(screen.getByLabelText('Buscar solo en esta página')).toHaveValue(''); expect(screen.getByText('Página 1')).toBeInTheDocument(); expect(screen.queryByText('tx-50', { exact: true })).not.toBeInTheDocument();
});
it.each(['OPERADOR', 'REPARTIDOR', 'CLIENTE'])('does not request a management ledger as %s', async role => {
  mockUser = { id: 'a', role }; render(<Page />); await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/login')); expect(get).not.toHaveBeenCalled();
});
it('does not load unauthenticated requests', () => { mockAuthenticated = false; render(<Page />); expect(get).not.toHaveBeenCalled(); });
