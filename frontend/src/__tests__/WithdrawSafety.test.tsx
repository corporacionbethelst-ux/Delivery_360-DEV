import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/rider/earnings/withdraw/page';
import { payoutService, createPayoutIdempotencyKey } from '@/services/payout.service';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { loadWithdrawalIntent, saveWithdrawalIntent } from '@/lib/withdrawal-intent';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/services/payout.service', () => ({ payoutService: { getAvailableBalance: jest.fn(), requestPayout: jest.fn(), findRequestByKey: jest.fn() }, createPayoutIdempotencyKey: jest.fn(), payoutHttpStatus: jest.requireActual('@/services/payout.service').payoutHttpStatus }));
const intent = { version: 1 as const, userId: 'a', key: 'safe-key', amountCents: 6000, bankLast4: '1234' };
const reply = { id: 'p', rider_id: 'r', amount: 60, total_amount: 60, method: 'TRANSFERENCIA' as const, status: 'PENDIENTE' as const, requested_at: null, created_at: null, updated_at: null, idempotency_key: 'safe-key', requested_by_user_id: 'a', bank_account_last4: '1234' };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); sessionStorage.clear(); mockUser = { id: 'a', role: 'REPARTIDOR' };
  storeTokens({ access_token: 'token-a', refresh_token: 'ra' });
  jest.mocked(payoutService.getAvailableBalance).mockResolvedValue({ available: 100, pending: 0, currency: 'COP' });
  jest.mocked(payoutService.findRequestByKey).mockResolvedValue(null);
  jest.mocked(payoutService.requestPayout).mockResolvedValue(reply);
  jest.mocked(createPayoutIdempotencyKey).mockReturnValue('safe-key');
});
afterEach(() => clearStoredTokens());
const submit = () => fireEvent.submit(screen.getByLabelText('Monto a Retirar').closest('form')!);
async function fill() {
  fireEvent.change(await screen.findByLabelText('Monto a Retirar'), { target: { value: '60' } });
  fireEvent.change(screen.getByLabelText('Últimos 4 dígitos (Opcional)'), { target: { value: '1234' } });
}

it.each([{ idempotency_key: 'other' }, { requested_by_user_id: 'b' }, { amount: 61, total_amount: 61 }, { method: 'EFECTIVO' }, { bank_account_last4: '9999' }])('retains the original key and shows no success on an inconsistent POST confirmation (%j)', async invalid => {
  jest.mocked(payoutService.requestPayout).mockResolvedValue({ ...reply, ...invalid } as never);
  render(<Page />); await fill(); submit();
  await screen.findByText('Error al procesar. Intenta más tarde.');
  expect(screen.queryByText('¡Solicitud Enviada!')).not.toBeInTheDocument();
  expect(loadWithdrawalIntent('a')).toEqual(intent);
  expect(screen.getByRole('button', { name: 'Reintentar misma solicitud' })).toBeEnabled();
});
it.each([{ idempotency_key: 'other' }, { requested_by_user_id: 'b' }, { amount: 61, total_amount: 61 }, { bank_account_last4: '9999' }])('does not clear recovery metadata on a mismatched lookup (%j)', async invalid => {
  saveWithdrawalIntent(intent);
  jest.mocked(payoutService.findRequestByKey).mockResolvedValue({ ...reply, ...invalid } as never);
  render(<Page />);
  await screen.findByText('No se pudo confirmar la solicitud. Conservamos sus datos para reintentar sin crear otra.');
  expect(screen.queryByText('Solicitud encontrada')).not.toBeInTheDocument();
  expect(loadWithdrawalIntent('a')).toEqual(intent); expect(payoutService.requestPayout).not.toHaveBeenCalled();
});
it('does not publish or clear another account request after switching during POST', async () => {
  const old = deferred<typeof reply>(); jest.mocked(payoutService.requestPayout).mockReturnValue(old.promise);
  render(<Page />); await fill(); submit();
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'token-b', refresh_token: 'rb' }); });
  await screen.findByLabelText('Monto a Retirar');
  await act(async () => { old.resolve(reply); });
  expect(screen.queryByText('¡Solicitud Enviada!')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Monto a Retirar')).toHaveValue(null);
  expect(loadWithdrawalIntent('a')).toEqual(intent); expect(loadWithdrawalIntent('b')).toBeNull();
});
it('checks the continuation gap even when the mocked service changes accounts immediately before returning', async () => {
  jest.mocked(payoutService.requestPayout).mockImplementation(async () => {
    mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'token-b', refresh_token: 'rb' }); return reply;
  });
  render(<Page />); await fill();
  await act(async () => { submit(); });
  expect(screen.queryByText('¡Solicitud Enviada!')).not.toBeInTheDocument(); expect(loadWithdrawalIntent('a')).toEqual(intent);
});
it('does not clear the old account intent after a late lookup', async () => {
  saveWithdrawalIntent(intent);
  const old = deferred<typeof reply>(); jest.mocked(payoutService.findRequestByKey).mockReturnValue(old.promise);
  render(<Page />); await waitFor(() => expect(payoutService.findRequestByKey).toHaveBeenCalled());
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'token-b', refresh_token: 'rb' }); });
  await act(async () => { old.resolve(reply); });
  expect(screen.queryByText('Solicitud encontrada')).not.toBeInTheDocument(); expect(loadWithdrawalIntent('a')).toEqual(intent);
});
it('does not let a late balance from another account enable a withdrawal', async () => {
  const old = deferred<{ available: number; pending: number }>();
  jest.mocked(payoutService.getAvailableBalance).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ available: 0, pending: 0, currency: 'COP' });
  render(<Page />);
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'token-b', refresh_token: 'rb' }); });
  await screen.findByLabelText('Monto a Retirar');
  await act(async () => { old.resolve({ available: 999, pending: 0 }); });
  expect(screen.getByRole('button', { name: 'Enviar solicitud de retiro' })).toBeDisabled();
  expect(screen.queryByText(/999/)).not.toBeInTheDocument();
});
it('retains recovery metadata when unmounted while awaiting POST', async () => {
  const old = deferred<typeof reply>(); jest.mocked(payoutService.requestPayout).mockReturnValue(old.promise);
  const page = render(<Page />); await fill(); submit(); page.unmount();
  await act(async () => { old.resolve(reply); }); expect(loadWithdrawalIntent('a')).toEqual(intent);
});
it('blocks two submit events in the same render with a synchronous lock', async () => {
  const old = deferred<typeof reply>(); jest.mocked(payoutService.requestPayout).mockReturnValue(old.promise);
  render(<Page />); await fill(); act(() => { submit(); submit(); });
  expect(payoutService.requestPayout).toHaveBeenCalledTimes(1); expect(createPayoutIdempotencyKey).toHaveBeenCalledTimes(1);
  await act(async () => { old.resolve(reply); }); await screen.findByText('¡Solicitud Enviada!');
});
it('keeps a failed balance unknown and offers a read-only retry', async () => {
  jest.mocked(payoutService.getAvailableBalance).mockRejectedValueOnce(new Error('degraded'));
  render(<Page />);
  await screen.findByText('No se pudo cargar tu saldo disponible. Puedes volver a consultarlo.');
  expect(screen.getAllByText('No disponible').length).toBeGreaterThan(0);
  expect(screen.getByRole('button', { name: 'Enviar solicitud de retiro' })).toBeDisabled();
  expect(payoutService.requestPayout).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Volver a consultar saldo' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Enviar solicitud de retiro' })).toBeEnabled());
});
it('can recover an authoritative existing request even when the balance service is unavailable', async () => {
  saveWithdrawalIntent(intent);
  jest.mocked(payoutService.getAvailableBalance).mockRejectedValue(new Error('degraded'));
  jest.mocked(payoutService.findRequestByKey).mockResolvedValue(reply);
  render(<Page />); await screen.findByText('Solicitud encontrada');
  expect(loadWithdrawalIntent('a')).toBeNull(); expect(screen.getByText(/moneda no informada/)).toBeInTheDocument();
  expect(payoutService.requestPayout).not.toHaveBeenCalled();
});
it('retains an uncertain key and permits the same retry even when no balance is available', async () => {
  saveWithdrawalIntent(intent);
  jest.mocked(payoutService.getAvailableBalance).mockRejectedValue(new Error('degraded'));
  render(<Page />); await screen.findByText('La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.');
  expect(screen.getByRole('button', { name: 'Reintentar misma solicitud' })).toBeEnabled(); submit();
  await screen.findByText('Solicitud encontrada'); expect(payoutService.requestPayout).toHaveBeenCalledWith(expect.objectContaining({ amount: 60, idempotency_key: 'safe-key' }));
});
it('waits for recovery initialization before exposing a new request form', async () => {
  saveWithdrawalIntent(intent);
  const balance = deferred<{ available: number; pending: number }>(); jest.mocked(payoutService.getAvailableBalance).mockReturnValue(balance.promise);
  render(<Page />); expect(screen.queryByLabelText('Monto a Retirar')).not.toBeInTheDocument();
  await act(async () => { balance.resolve({ available: 100, pending: 0 }); });
  await screen.findByText('La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.');
  expect(screen.getByLabelText('Monto a Retirar')).toBeDisabled(); expect(createPayoutIdempotencyKey).not.toHaveBeenCalled();
});
