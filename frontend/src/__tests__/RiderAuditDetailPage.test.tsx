import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/operations/rider-audit/[id]/page';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { auditHttpResponse, auditSummaryPage, auditSummaryResponse, auditOrderResponse, auditDeliveryResponse, auditDeliveryPage } from '../../test-fixtures/rider-audit';
const mockRouter = { replace: jest.fn() }; let mockParams: { id: string | string[] } = { id: 'rider-1' }, mockUser: { id: string; role: string } | null = { id: 'a', role: 'GERENTE' }, mockAuthenticated = true;
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => mockParams }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
function deferred() { let resolve!: (v: unknown) => void, reject!: (e: Error) => void; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); mockParams = { id: 'rider-1' }; mockUser = { id: 'a', role: 'GERENTE' }; mockAuthenticated = true; get.mockImplementation(async url => auditHttpResponse(url, 1)); });
afterEach(() => clearStoredTokens());
it('shows exact identities, legitimate zero values, UTC and unknown currencies', async () => {
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' });
  expect(screen.getByText('0, 0', { exact: true })).toBeInTheDocument(); expect(screen.getByText('Offline', { exact: true })).toBeInTheDocument();
  expect(screen.getAllByText('0,00 (moneda no informada)')).toHaveLength(2); expect(screen.queryByText(/COP|USD|\$0/)).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Ver orden o-0' })).toHaveAttribute('href', '/manager/operations/orders/o-0'); expect(screen.getByRole('link', { name: 'Ver transacción tx-0' })).toHaveAttribute('href', '/manager/financial/transactions/tx-0');
  expect(screen.getAllByText(/UTC/).length).toBeGreaterThan(0); expect(screen.getByText(/no acreditan una transferencia bancaria/)).toBeInTheDocument();
});
it('leaves absent amounts, dates and snapshots unknown rather than inventing zero or pending payment', async () => {
  get.mockImplementation(async url => url.startsWith('/orders') ? [auditOrderResponse('o', 'rider-1', { total: null, created_at: null })] : url.startsWith('/deliveries') ? auditDeliveryPage([auditDeliveryResponse('d', 'rider-1', { locked_bonus_amount: null, updated_at: null })]) : auditHttpResponse(url, 1));
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' }); expect(screen.getAllByText('Monto no informado')).toHaveLength(2); expect(screen.getAllByText('Fecha no informada')).toHaveLength(2); expect(screen.queryByText('Pendiente', { exact: true })).not.toBeInTheDocument();
});
it('separates fallback orders and does not count their derived completed status as a real delivery', async () => {
  get.mockImplementation(async url => url.startsWith('/deliveries') ? auditDeliveryPage([auditDeliveryResponse('order-support', 'rider-1', { order_id: 'support', locked_bonus_amount: null })]) : auditHttpResponse(url, 1));
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' }); const deliveries = screen.getByRole('region', { name: 'Entregas registradas del repartidor' }); expect(within(deliveries).getByText('0 filas cargadas en la página 1.')).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Ver orden de apoyo support' })).toHaveAttribute('href', '/manager/operations/orders/support');
});
it('does not publish any partial blocks before all four reads finish', async () => {
  const pending = deferred(); get.mockImplementation(async url => url.startsWith('/financial') ? pending.promise : auditHttpResponse(url, 1)); render(<Page />); expect(screen.queryByRole('region', { name: 'Auditoría confirmada' })).not.toBeInTheDocument();
  await act(async () => { pending.resolve(auditHttpResponse('/financial/transactions', 1)); }); await screen.findByRole('region', { name: 'Auditoría confirmada' });
});
it('shows a cold read error and offers a retry instead of an empty rider catalog', async () => {
  get.mockRejectedValue(new Error('offline')); render(<Page />); await screen.findByRole('alert'); expect(screen.queryByText(/No hay registros/)).not.toBeInTheDocument(); expect(screen.queryByRole('region', { name: 'Auditoría confirmada' })).not.toBeInTheDocument();
  get.mockImplementation(async url => auditHttpResponse(url, 1)); fireEvent.click(screen.getByRole('button', { name: 'Reintentar auditoría' })); await screen.findByRole('region', { name: 'Auditoría confirmada' });
});
it('keeps the whole previous set when one refresh block fails', async () => {
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' });
  get.mockImplementation(async url => { if (url.startsWith('/deliveries')) throw new Error('offline'); if (url.startsWith('/orders')) return [auditOrderResponse('changed')]; return auditHttpResponse(url, 1); });
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar auditoría' })); await screen.findByRole('alert'); expect(screen.getByRole('link', { name: 'Ver orden o-0' })).toBeInTheDocument(); expect(screen.queryByRole('link', { name: 'Ver orden changed' })).not.toBeInTheDocument();
});
it('navigates independent bounded tables without displaying hidden lookahead rows', async () => {
  get.mockImplementation(async url => auditHttpResponse(url)); render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' });
  expect(screen.queryByRole('link', { name: 'Ver orden o-50' })).not.toBeInTheDocument();
  const nav = screen.getByRole('navigation', { name: 'Páginas de Órdenes del repartidor' }); fireEvent.click(within(nav).getByRole('button', { name: 'Siguiente' })); await screen.findByRole('link', { name: 'Ver orden o-50' });
  expect(within(nav).getByText('Página 2')).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Ver transacción tx-0' })).toBeInTheDocument(); expect(screen.queryByRole('link', { name: 'Ver transacción tx-50' })).not.toBeInTheDocument();
});
it('labels an exhausted summary lookup as absent within its scope, not a nonexistent rider', async () => {
  get.mockImplementation(async url => url.startsWith('/riders/') ? auditSummaryPage([]) : auditHttpResponse(url, 1)); render(<Page />); await screen.findByText(/Esto no confirma que el repartidor no exista/); expect(screen.getByRole('link', { name: 'Ver orden o-0' })).toBeInTheDocument();
});
it('clears all old blocks on route change and ignores an old success', async () => {
  const old = deferred(); get.mockImplementation(async url => url.startsWith('/orders') ? old.promise : auditHttpResponse(url, 1)); const view = render(<Page />);
  get.mockImplementation(async url => auditHttpResponse(url, 1, 'rider-2')); mockParams = { id: 'rider-2' }; view.rerender(<Page />); await screen.findByText('Repartidor de la consulta confirmada: rider-2');
  await act(async () => { old.resolve([auditOrderResponse('retired')]); }); expect(screen.queryByRole('link', { name: 'Ver orden retired' })).not.toBeInTheDocument(); expect(screen.queryByText('Repartidor de la consulta confirmada: rider-1')).not.toBeInTheDocument();
});
it('clears a confirmed account before the next account reads finish', async () => {
  render(<Page />); await screen.findByRole('region', { name: 'Auditoría confirmada' }); const pending = deferred(); get.mockImplementation(async url => url.startsWith('/orders') ? pending.promise : auditHttpResponse(url, 1));
  act(() => { mockUser = { id: 'b', role: 'GERENTE' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); }); expect(screen.queryByRole('region', { name: 'Auditoría confirmada' })).not.toBeInTheDocument();
  await act(async () => { pending.resolve([auditOrderResponse('b-order')]); }); await screen.findByRole('link', { name: 'Ver orden b-order' });
});
it.each(['ADMIN', 'OPERADOR', 'REPARTIDOR'])('prevents mounting private reads for role %s', role => {
  mockUser = { id: 'a', role }; render(<Page />); expect(get).not.toHaveBeenCalled(); expect(mockRouter.replace).toHaveBeenCalledWith('/login');
});
it('does not mount private reads when logged out', () => { mockAuthenticated = false; mockUser = null; render(<Page />); expect(get).not.toHaveBeenCalled(); });
it('ends invalid array route parameters with a visible recoverable error, without HTTP', async () => {
  mockParams = { id: [] }; render(<Page />); await screen.findByRole('alert'); expect(get).not.toHaveBeenCalled(); expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
it('keeps the zero-delivery SLA denominator explicit', async () => {
  get.mockImplementation(async url => url.startsWith('/riders/') ? auditSummaryPage([auditSummaryResponse('rider-1', { deliveries_total: 0, deliveries_completed: 0, deliveries_failed: 0, deliveries_in_progress: 0, sla_compliant: 0, sla_compliance_rate: 0 })]) : auditHttpResponse(url, 1)); render(<Page />); await screen.findByText('Sin entregas en el denominador');
});
