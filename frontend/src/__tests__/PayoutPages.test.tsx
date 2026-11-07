import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Detail from '@/app/(dashboard)/manager/financial/payouts/[id]/page';
import Manager from '@/app/(dashboard)/manager/financial/payouts/page';
import Rider from '@/app/(dashboard)/rider/earnings/payouts/page';
import { payoutService, type Payout, type PayoutPage } from '@/services/payout.service';
import { riderService } from '@/services/rider.service';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockParams = { id: 'p' }, mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => mockParams }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/services/payout.service', () => ({ payoutService: { getById: jest.fn(), getHistory: jest.fn(), getPage: jest.fn(), approve: jest.fn(), reject: jest.fn() } }));
jest.mock('@/services/rider.service', () => ({ riderService: { getById: jest.fn() } }));
jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => <select value={value} onChange={e => onValueChange(e.target.value)}>{children}</select>,
  SelectTrigger: () => null, SelectValue: () => null, SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));
const row = { id: 'p', rider_id: 'r', amount: 60.12, total_amount: 60.12, method: 'TRANSFERENCIA' as const, status: 'PENDIENTE' as const, requested_at: null, created_at: null, updated_at: null };

const page = (items: Payout[]): PayoutPage => ({ items: items.slice(0, 50), next_cursor: items.length > 50 ? `after-${items[49].id}` : null });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); mockParams = { id: 'p' }; mockUser = { id: 'a', role: 'REPARTIDOR' };
  storeTokens({ access_token: 'a', refresh_token: 'ra' });
  jest.mocked(payoutService.getById).mockResolvedValue(row);
  jest.mocked(payoutService.getPage).mockResolvedValue(page([row]));
  jest.mocked(payoutService.getHistory).mockResolvedValue([]);
  jest.mocked(riderService.getById).mockResolvedValue({ id: 'r', first_name: 'Ana', last_name: 'Test' });
  jest.spyOn(console, 'error').mockImplementation(() => {});
  jest.spyOn(window, 'alert').mockImplementation(() => {});
});
afterEach(() => { clearStoredTokens(); jest.restoreAllMocks(); });

it.each(['EN_PROCESO', 'RECHAZADO', 'FALLIDO', 'COMPLETADO'] as const)('shows the registered management date without declaring a bank transfer completed (%s)', async status => {
  jest.mocked(payoutService.getById).mockResolvedValue({ ...row, status, processed_at: '2026-11-05T10:00:00Z' });
  render(<Detail />);
  await screen.findByText('Fecha de gestión registrada');
  expect(screen.queryByText(/El pago se completó/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aprobar retiro' })).not.toBeInTheDocument();
  expect(screen.getByText('Fecha no informada', { exact: false })).toBeInTheDocument();
});
it('preserves an approved in-process response when its subsequent refresh fails', async () => {
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockRejectedValueOnce(new Error('refresh failed'));
  jest.mocked(payoutService.approve).mockResolvedValue({ ...row, status: 'EN_PROCESO' });
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' }));
  await screen.findByRole('alert');
  expect(screen.getByText('EN PROCESO')).toBeInTheDocument();
  expect(screen.queryByText('Pago no encontrado')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aprobar retiro' })).not.toBeInTheDocument();
});
it('does not substitute a response from an older route after navigating to another payout', async () => {
  const old = deferred<typeof row>(); jest.mocked(payoutService.getById).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...row, id: 'new-payout' });
  const view = render(<Detail />);
  act(() => { mockParams = { id: 'new-payout' }; }); view.rerender(<Detail />);
  await screen.findByText('new-payout');
  await act(async () => { old.resolve(row); }); expect(screen.getByText('new-payout')).toBeInTheDocument();
});
it.each(['rider', 'manager'])('discards a retired account list before publishing or starting subsequent rider queries (%s)', async kind => {
  const old = deferred<PayoutPage>(); jest.mocked(payoutService.getPage).mockReturnValueOnce(old.promise).mockResolvedValueOnce(page([]));
  render(kind === 'rider' ? <Rider /> : <Manager />);
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await act(async () => { old.resolve(page([row])); });
  expect(riderService.getById).not.toHaveBeenCalled();
  expect(screen.queryByText(/60[,.]12/)).not.toBeInTheDocument();
});
it('keeps manager results and shows an error after a failed refresh', async () => {
  jest.mocked(payoutService.getPage).mockResolvedValueOnce(page([row])).mockRejectedValueOnce(new Error('network'));
  render(<Manager />); await screen.findByText(/60[,.]12/);
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }));
  await screen.findByRole('alert'); expect(screen.getByText(/60[,.]12/)).toBeInTheDocument();
  expect(screen.getByText(/corresponden a esta página/)).toBeInTheDocument();
});
it('does not let an earlier overlapping manager refresh overwrite the newer one', async () => {
  const old = deferred<PayoutPage>();
  jest.mocked(payoutService.getPage).mockResolvedValueOnce(page([row])).mockReturnValueOnce(old.promise).mockResolvedValueOnce(page([{ ...row, amount: 77.77, total_amount: 77.77 }]));
  render(<Manager />); await screen.findByText(/60[,.]12/);
  const button = screen.getByRole('button', { name: 'Actualizar' });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  await screen.findByText(/77[,.]77/);
  await act(async () => { old.resolve(page([row])); }); expect(screen.getByText(/77[,.]77/)).toBeInTheDocument();
});
it('does not apply or alert an approval continuation from another account', async () => {
  const old = deferred<typeof row>(); jest.mocked(payoutService.approve).mockReturnValueOnce(old.promise);
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' }));
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await act(async () => { old.resolve({ ...row, status: 'EN_PROCESO' } as never); });
  expect(window.alert).not.toHaveBeenCalled(); expect(payoutService.getById).toHaveBeenCalledTimes(2);
});
it('renders unknown balance snapshots as missing instead of zero', async () => {
  render(<Detail />);
  await screen.findByRole('button', { name: 'Aprobar retiro' });
  expect(screen.getAllByText('Monto no informado')).toHaveLength(2);
});
it('blocks another decision after an uncertain approval and recovers through read-only queries', async () => {
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockResolvedValueOnce({ ...row, status: 'EN_PROCESO' });
  jest.mocked(payoutService.approve).mockRejectedValueOnce(new Error('unknown response'));
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo confirmar la aprobación');
  expect(screen.queryByRole('button', { name: 'Aprobar retiro' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Rechazar retiro' })).not.toBeInTheDocument();
  expect(payoutService.getById).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado del retiro' }));
  await screen.findByText('EN PROCESO');
  expect(payoutService.approve).toHaveBeenCalledTimes(1); expect(payoutService.reject).not.toHaveBeenCalled();
  expect(payoutService.getById).toHaveBeenCalledTimes(2); expect(payoutService.getHistory).toHaveBeenCalledTimes(2);
});
it('requires another deliberate click after an authoritative pending read; a read never replays an approval', async () => {
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockResolvedValueOnce(row).mockResolvedValueOnce({ ...row, status: 'EN_PROCESO' });
  jest.mocked(payoutService.approve).mockRejectedValueOnce(new Error('unknown')).mockResolvedValueOnce({ ...row, status: 'EN_PROCESO' });
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' })); await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado del retiro' }));
  const approve = await screen.findByRole('button', { name: 'Aprobar retiro' }); expect(payoutService.approve).toHaveBeenCalledTimes(1);
  fireEvent.click(approve); await screen.findByText('EN PROCESO'); expect(payoutService.approve).toHaveBeenCalledTimes(2);
});
it('keeps decisions blocked when state/history recovery is still unavailable', async () => {
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockRejectedValueOnce(new Error('read failed'));
  jest.mocked(payoutService.approve).mockRejectedValueOnce(new Error('unknown'));
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' })); await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado del retiro' })); await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: 'Aprobar retiro' })).not.toBeInTheDocument();
  expect(screen.getByText('PENDIENTE')).toBeInTheDocument(); expect(payoutService.approve).toHaveBeenCalledTimes(1);
});
it('recovers a failed initial detail read without requiring navigation away', async () => {
  jest.mocked(payoutService.getById).mockRejectedValueOnce(new Error('not available')).mockResolvedValueOnce(row);
  render(<Detail />); await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado del retiro' })); await screen.findByRole('button', { name: 'Aprobar retiro' });
  expect(payoutService.approve).not.toHaveBeenCalled();
});
it('does not repeat a rejection after an uncertain result and displays the subsequently read server state', async () => {
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockResolvedValueOnce({ ...row, status: 'RECHAZADO', rejection_reason: 'Datos por revisar' });
  jest.mocked(payoutService.reject).mockRejectedValueOnce(new Error('unknown'));
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Rechazar retiro' }));
  fireEvent.change(screen.getByLabelText('Motivo del Rechazo *'), { target: { value: 'Datos por revisar' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar Rechazo' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo confirmar el rechazo');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado del retiro' })); await screen.findByText('RECHAZADO');
  expect(payoutService.reject).toHaveBeenCalledTimes(1); expect(payoutService.approve).not.toHaveBeenCalled();
});
it.each([{ method: 'EFECTIVO' }, { bank_account_last4: '1234' }, { rider_id: 'other' }, { amount: 99 }])('treats an inconsistent approval as unconfirmed and retains the last snapshot (%j)', async invalid => {
  jest.mocked(payoutService.approve).mockResolvedValue({ ...row, status: 'EN_PROCESO', ...invalid } as never);
  render(<Detail />); fireEvent.click(await screen.findByRole('button', { name: 'Aprobar retiro' })); await screen.findByRole('alert');
  expect(screen.getByText('PENDIENTE')).toBeInTheDocument(); expect(screen.queryByText('EN PROCESO')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Aprobar retiro' })).not.toBeInTheDocument();
});
it('ignores an older recovery response after a newer read has completed', async () => {
  let resolve!: (value: typeof row) => void;
  jest.mocked(payoutService.getById).mockResolvedValueOnce(row).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce({ ...row, status: 'RECHAZADO' });
  render(<Detail />); await screen.findByRole('button', { name: 'Aprobar retiro' });
  const consult = screen.getByRole('button', { name: 'Consultar estado del retiro' }); act(() => { fireEvent.click(consult); fireEvent.click(consult); });
  await screen.findByText('RECHAZADO'); await act(async () => { resolve(row); }); expect(screen.getByText('RECHAZADO')).toBeInTheDocument();
});
