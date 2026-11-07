import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/financial/resumen/page';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { summaryResponse, zeroSummary } from '../../test-fixtures/financial-summary';

const mockRouter = { replace: jest.fn() };
let mockUser = { id: 'a', role: 'GERENTE' }, mockAuthenticated = true;
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
function deferred() { let resolve!: (value: unknown) => void, reject!: (error: Error) => void; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' });
  mockUser = { id: 'a', role: 'GERENTE' }; mockAuthenticated = true;
  get.mockResolvedValue(summaryResponse('week'));
});
afterEach(() => clearStoredTokens());

it('labels the server period and UTC range without assuming dollars or confirmed bank payments', async () => {
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  expect(get).toHaveBeenCalledWith('/financial/summary?period=week');
  expect(screen.getByText(/Rango consultado \(UTC\)/)).toHaveTextContent('2/11/26');
  expect(screen.getByText('Moneda no informada por el servidor')).toBeInTheDocument();
  expect(screen.queryByText(/US\$|USD/)).not.toBeInTheDocument();
  expect(screen.getByText('Costo reconocido de repartidores')).toBeInTheDocument();
  expect(screen.getByText(/no confirma una transferencia bancaria/)).toBeInTheDocument();
});
it('keeps loading and an initial failure distinct from a zero-valued financial report and allows retry', async () => {
  const pending = deferred(); get.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(summaryResponse('week'));
  render(<Page />); expect(screen.queryByRole('region', { name: 'Resumen confirmado' })).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Consultando Semana');
  await act(async () => { pending.reject(new Error('offline')); }); await screen.findByRole('alert');
  expect(screen.queryByRole('region', { name: 'Resumen confirmado' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText('Datos confirmados: Semana');
});
it('shows genuine zeros while keeping absent optional metrics unknown', async () => {
  get.mockResolvedValue(summaryResponse('week', { ...zeroSummary, other_costs: undefined, cash_payouts_processed: undefined }));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  expect(screen.getAllByText('0,00 (moneda no informada)').length).toBeGreaterThan(2);
  expect(screen.getAllByText('No informado')).toHaveLength(2);
});
it('retains the confirmed period when another period fails and retries the actual failed query', async () => {
  get.mockResolvedValueOnce(summaryResponse('week')).mockRejectedValueOnce(new Error('month failed')).mockResolvedValueOnce(summaryResponse('month'));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByRole('alert');
  expect(screen.getByText('Datos confirmados: Semana')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Semana' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText('Datos confirmados: Mes');
  expect(get.mock.calls.slice(-2).map(([url]) => url)).toEqual(['/financial/summary?period=month', '/financial/summary?period=month']);
});
it.each(['success', 'error'])('does not let an old period completion replace a newer successful period (%s)', async mode => {
  const old = deferred(); get.mockResolvedValueOnce(summaryResponse('week')).mockReturnValueOnce(old.promise).mockResolvedValueOnce(summaryResponse('month'));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Hoy' }));
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByText('Datos confirmados: Mes');
  await act(async () => { if (mode === 'success') old.resolve(summaryResponse()); else old.reject(new Error('old error')); });
  expect(screen.getByText('Datos confirmados: Mes')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument(); expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
it('refreshes the confirmed period instead of resetting the selection', async () => {
  get.mockResolvedValueOnce(summaryResponse('week')).mockResolvedValueOnce(summaryResponse('month')).mockRejectedValueOnce(new Error('offline'));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByText('Datos confirmados: Mes');
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar resumen' })); await screen.findByRole('alert');
  expect(get).toHaveBeenLastCalledWith('/financial/summary?period=month'); expect(screen.getByText('Datos confirmados: Mes')).toBeInTheDocument();
});
it('discards the previous account snapshot and pending continuation before rendering another account', async () => {
  const old = deferred(), current = deferred();
  get.mockResolvedValueOnce(summaryResponse('week')).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' }));
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  expect(screen.queryByRole('region', { name: 'Resumen confirmado' })).not.toBeInTheDocument();
  await act(async () => { current.resolve(summaryResponse('week', { currency: 'COP' })); old.resolve(summaryResponse('month')); });
  await screen.findByText('Moneda informada: COP'); expect(screen.getByText('Datos confirmados: Semana')).toBeInTheDocument();
});
it('clears a retired role snapshot even when the credential generation is unchanged', async () => {
  const next = deferred(); get.mockResolvedValueOnce(summaryResponse('week')).mockReturnValueOnce(next.promise);
  const view = render(<Page />); await screen.findByText('Datos confirmados: Semana');
  mockUser = { id: 'a', role: 'SUPERADMIN' }; view.rerender(<Page />);
  expect(screen.queryByRole('region', { name: 'Resumen confirmado' })).not.toBeInTheDocument();
  await act(async () => { next.resolve(summaryResponse('week')); }); await screen.findByText('Datos confirmados: Semana');
});
it.each(['REPARTIDOR', 'OPERADOR', 'CLIENTE'])('does not request a management summary under role %s', async role => {
  mockUser = { id: 'a', role }; render(<Page />);
  await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/login')); expect(get).not.toHaveBeenCalled();
});
it('does not request data when authentication is missing', () => {
  mockAuthenticated = false; render(<Page />); expect(get).not.toHaveBeenCalled();
});
it('draws a negative net margin to the left of zero with a nonnegative bar width', async () => {
  get.mockResolvedValue(summaryResponse('week', { total_costs: 140, total_rider_payouts: 130, rider_earnings_accrued: 135, net_margin: -40 }));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  const chart = screen.getByRole('img', { name: 'Neto: -40,00 (moneda no informada)' });
  const bar = chart.querySelector('[data-direction="negative"]') as HTMLElement;
  expect(parseFloat(bar.style.width)).toBeGreaterThan(0); expect(parseFloat(bar.style.left)).toBeLessThan(50);
});
it('keeps omitted range and cost details unknown without deriving them from other fields', async () => {
  get.mockResolvedValue(summaryResponse('week', { period_start: undefined, period_end: undefined, other_costs: null }));
  render(<Page />); await screen.findByText('Rango no informado por el servidor'); expect(screen.getByText('No informado')).toBeInTheDocument();
});
it.each([{ period: 'week' }, { total_revenue: false }, { net_margin: 61 }])('retains valid figures after a contradictory HTTP response (%j)', async changes => {
  get.mockResolvedValueOnce(summaryResponse('week')).mockResolvedValueOnce(summaryResponse('month', changes));
  render(<Page />); await screen.findByText('Datos confirmados: Semana');
  fireEvent.click(screen.getByRole('button', { name: 'Mes' })); await screen.findByRole('alert');
  expect(screen.getByText('Datos confirmados: Semana')).toBeInTheDocument();
});
it('retires a completion after the page unmounts', async () => {
  const old = deferred(); get.mockReturnValue(old.promise); const view = render(<Page />); view.unmount();
  await act(async () => { old.resolve(summaryResponse('week')); }); expect(get).toHaveBeenCalledTimes(1);
});
