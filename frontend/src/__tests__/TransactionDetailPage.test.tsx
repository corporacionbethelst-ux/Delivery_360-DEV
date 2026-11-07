import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/financial/transactions/[id]/page';
import { api } from '@/lib/api';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
import { transactionResponse } from '../../test-fixtures/transactions';
const mockRouter = { replace: jest.fn() }; let mockParams: { id: string | string[] } = { id: 'tx-1' }, mockUser = { id: 'a', role: 'GERENTE' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => mockParams }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
function deferred() { let resolve!: (value: unknown) => void, reject!: (error: Error) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockParams = { id: 'tx-1' }; mockUser = { id: 'a', role: 'GERENTE' }; get.mockResolvedValue(transactionResponse()); jest.spyOn(window, 'print').mockImplementation(() => {}); });
afterEach(() => { clearStoredTokens(); jest.restoreAllMocks(); });
it('shows true identity, audit metadata and unknown currency without a fabricated process date', async () => {
  render(<Page />); await screen.findByText('ID confirmado: tx-1');
  expect(screen.getByText('Moneda').parentElement).toHaveTextContent('No informada'); expect(screen.getByText('actor-1')).toBeInTheDocument(); expect(screen.getByText('order-1')).toBeInTheDocument();
  expect(screen.getByText('Fecha no informada')).toBeInTheDocument(); expect(screen.queryByText(/Procesamiento Exitoso/)).not.toBeInTheDocument();
  expect(screen.getByText(/no son una confirmación bancaria/)).toBeInTheDocument();
});
it('preserves zeros, signed amounts and absent balances', async () => {
  get.mockResolvedValue(transactionResponse('tx-1', { amount: -5.5, balance_before: 0, balance_after: null, created_at: null })); render(<Page />); await screen.findByText('ID confirmado: tx-1');
  expect(screen.getByText('-5,50 (moneda no informada)')).toBeInTheDocument(); expect(screen.getByText('0,00 (moneda no informada)')).toBeInTheDocument(); expect(screen.getByText('Monto no informado')).toBeInTheDocument();
});
it('offers a read-only retry after an initial error without pretending the transaction does not exist', async () => {
  get.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce(transactionResponse()); render(<Page />); await screen.findByRole('alert');
  expect(screen.queryByRole('region', { name: 'Transacción confirmada' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar lectura' })); await screen.findByText('ID confirmado: tx-1'); expect(get).toHaveBeenCalledTimes(2);
});
it('preserves confirmed data and blocks printing after a failed refresh until a valid recovery', async () => {
  get.mockResolvedValueOnce(transactionResponse()).mockRejectedValueOnce(new Error('failed')).mockResolvedValueOnce(transactionResponse()); render(<Page />); await screen.findByText('ID confirmado: tx-1');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar transacción' })); await screen.findByRole('alert');
  expect(screen.getByText('ID confirmado: tx-1')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Imprimir registro' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar lectura' })); await screen.findByRole('button', { name: 'Imprimir registro' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Imprimir registro' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Imprimir registro' })); expect(window.print).toHaveBeenCalledTimes(1);
});
it('rejects another transaction identity during refresh instead of replacing the reviewed record', async () => {
  get.mockResolvedValueOnce(transactionResponse()).mockResolvedValueOnce(transactionResponse('wrong')); render(<Page />); await screen.findByText('ID confirmado: tx-1');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar transacción' })); await screen.findByRole('alert'); expect(screen.getByText('ID confirmado: tx-1')).toBeInTheDocument(); expect(screen.queryByText('ID confirmado: wrong')).not.toBeInTheDocument();
});
it.each(['success', 'failure'])('keeps a newer detail response when an older refresh completes (%s)', async mode => {
  const old = deferred(); get.mockResolvedValueOnce(transactionResponse()).mockReturnValueOnce(old.promise).mockResolvedValueOnce(transactionResponse('tx-1', { description: 'Newest' }));
  render(<Page />); await screen.findByText('ID confirmado: tx-1'); fireEvent.click(screen.getByRole('button', { name: 'Consultar transacción' })); fireEvent.click(screen.getByRole('button', { name: 'Consultar transacción' })); await screen.findByText('Newest');
  await act(async () => { if (mode === 'success') old.resolve(transactionResponse('tx-1', { description: 'Old' })); else old.reject(new Error('old')); });
  expect(screen.getByText('Newest')).toBeInTheDocument(); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('retires the old route immediately and never publishes its late response on the new transaction', async () => {
  const old = deferred(); get.mockReturnValueOnce(old.promise).mockResolvedValueOnce(transactionResponse('tx-2')); const view = render(<Page />);
  mockParams = { id: 'tx-2' }; view.rerender(<Page />); await screen.findByText('ID confirmado: tx-2');
  await act(async () => { old.resolve(transactionResponse()); }); expect(screen.queryByText('ID confirmado: tx-1')).not.toBeInTheDocument();
});
it('clears a previous account snapshot before the new request finishes', async () => {
  const next = deferred(); get.mockResolvedValueOnce(transactionResponse()).mockReturnValueOnce(next.promise); render(<Page />); await screen.findByText('ID confirmado: tx-1');
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); }); expect(screen.queryByRole('region', { name: 'Transacción confirmada' })).not.toBeInTheDocument();
  await act(async () => { next.resolve(transactionResponse('tx-1', { description: 'B data' })); }); await screen.findByText('B data');
});
it('ends invalid/missing route IDs without HTTP or an infinite spinner', async () => {
  mockParams = { id: [] }; render(<Page />); await screen.findByRole('alert'); expect(get).not.toHaveBeenCalled(); expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
it('prints a confirmed UUID even when the requested UUID uses uppercase characters', async () => {
  mockParams = { id: '12345678-ABCD-1234-ABCD-123456789012' };
  get.mockResolvedValue(transactionResponse('12345678-abcd-1234-abcd-123456789012'));
  render(<Page />); await screen.findByText('ID confirmado: 12345678-abcd-1234-abcd-123456789012');
  fireEvent.click(screen.getByRole('button', { name: 'Imprimir registro' }));
  expect(window.print).toHaveBeenCalledTimes(1);
});
