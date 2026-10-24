import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WithdrawPage from '@/app/(dashboard)/rider/earnings/withdraw/page';
import { payoutService, createPayoutIdempotencyKey } from '@/services/payout.service';
const mockRouter = { push: jest.fn(), back: jest.fn() };
const mockUser = { id: 'rider-user', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/services/payout.service', () => ({ payoutService: { getAvailableBalance: jest.fn(), requestPayout: jest.fn() }, createPayoutIdempotencyKey: jest.fn() }));
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(payoutService.getAvailableBalance).mockResolvedValue({ available: 100, pending: 0 });
  jest.mocked(payoutService.requestPayout).mockRejectedValue(new Error('Network unavailable'));
  jest.mocked(createPayoutIdempotencyKey).mockReturnValueOnce('intent-1').mockReturnValueOnce('intent-2');
});
const submit = () => fireEvent.submit(screen.getByLabelText('Monto a Retirar').closest('form')!);
it('reuses the same key after an uncertain response instead of starting another withdrawal', async () => {
  render(<WithdrawPage />);
  const amount = await screen.findByLabelText('Monto a Retirar');
  fireEvent.change(amount, { target: { value: '60' } });
  submit();
  await screen.findByText('Error al procesar. Intenta más tarde.');
  submit();
  await waitFor(() => expect(payoutService.requestPayout).toHaveBeenCalledTimes(2));
  expect(jest.mocked(payoutService.requestPayout).mock.calls.map(([data]) => data.idempotency_key)).toEqual(['intent-1', 'intent-1']);
  expect(createPayoutIdempotencyKey).toHaveBeenCalledTimes(1);
});
it('creates a new intent when the requested amount changes', async () => {
  render(<WithdrawPage />);
  const amount = await screen.findByLabelText('Monto a Retirar');
  fireEvent.change(amount, { target: { value: '60' } });
  submit();
  await screen.findByText('Error al procesar. Intenta más tarde.');
  fireEvent.change(amount, { target: { value: '50' } });
  submit();
  await waitFor(() => expect(payoutService.requestPayout).toHaveBeenCalledTimes(2));
  expect(jest.mocked(payoutService.requestPayout).mock.calls.map(([data]) => data.idempotency_key)).toEqual(['intent-1', 'intent-2']);
});
it('does not submit an incomplete bank suffix', async () => {
  render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText('Monto a Retirar'), { target: { value: '60' } });
  fireEvent.change(screen.getByLabelText('Últimos 4 dígitos (Opcional)'), { target: { value: '12' } });
  submit();
  expect(await screen.findByText('Ingresa los cuatro dígitos completos de la cuenta.')).toBeInTheDocument();
  expect(payoutService.requestPayout).not.toHaveBeenCalled();
});
