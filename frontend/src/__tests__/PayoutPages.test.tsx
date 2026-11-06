import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Detail from '@/app/(dashboard)/manager/financial/payouts/[id]/page';
import Manager from '@/app/(dashboard)/manager/financial/payouts/page';
import Rider from '@/app/(dashboard)/rider/earnings/payouts/page';
import { payoutService } from '@/services/payout.service';
import { riderService } from '@/services/rider.service';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockParams = { id: 'p' }, mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, useParams: () => mockParams }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/services/payout.service', () => ({ payoutService: { getById: jest.fn(), getHistory: jest.fn(), getAll: jest.fn(), approve: jest.fn(), reject: jest.fn() } }));
jest.mock('@/services/rider.service', () => ({ riderService: { getById: jest.fn() } }));
jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => <select value={value} onChange={e => onValueChange(e.target.value)}>{children}</select>,
  SelectTrigger: () => null, SelectValue: () => null, SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));
const row = { id: 'p', rider_id: 'r', amount: 60.12, total_amount: 60.12, method: 'TRANSFERENCIA' as const, status: 'PENDIENTE' as const, requested_at: null, created_at: null, updated_at: null };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); mockParams = { id: 'p' }; mockUser = { id: 'a', role: 'REPARTIDOR' };
  storeTokens({ access_token: 'a', refresh_token: 'ra' });
  jest.mocked(payoutService.getById).mockResolvedValue(row);
  jest.mocked(payoutService.getAll).mockResolvedValue([row]);
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
  const old = deferred<typeof row[]>(); jest.mocked(payoutService.getAll).mockReturnValueOnce(old.promise).mockResolvedValueOnce([]);
  render(kind === 'rider' ? <Rider /> : <Manager />);
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await act(async () => { old.resolve([row]); });
  expect(riderService.getById).not.toHaveBeenCalled();
  expect(screen.queryByText(/60[,.]12/)).not.toBeInTheDocument();
});
it('keeps manager results and shows an error after a failed refresh', async () => {
  jest.mocked(payoutService.getAll).mockResolvedValueOnce([row]).mockRejectedValueOnce(new Error('network'));
  render(<Manager />); await screen.findByText(/60[,.]12/);
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }));
  await screen.findByRole('alert'); expect(screen.getByText(/60[,.]12/)).toBeInTheDocument();
  expect(screen.getByText(/corresponden a este lote/)).toBeInTheDocument();
});
it('does not let an earlier overlapping manager refresh overwrite the newer one', async () => {
  const old = deferred<typeof row[]>();
  jest.mocked(payoutService.getAll).mockResolvedValueOnce([row]).mockReturnValueOnce(old.promise).mockResolvedValueOnce([{ ...row, amount: 77.77, total_amount: 77.77 }]);
  render(<Manager />); await screen.findByText(/60[,.]12/);
  const button = screen.getByRole('button', { name: 'Actualizar' });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  await screen.findByText(/77[,.]77/);
  await act(async () => { old.resolve([row]); }); expect(screen.getByText(/77[,.]77/)).toBeInTheDocument();
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
