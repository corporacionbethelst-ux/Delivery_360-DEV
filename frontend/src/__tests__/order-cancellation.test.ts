import { api } from '@/lib/api';
import { orderService } from '@/services/order.service';
import { isDeliveryCancelled, isDeliveryTerminal, isCancellationReasonValid } from '@/lib/delivery-status';

jest.mock('@/lib/api', () => ({ api: { patch: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());

it.each(['CANCELADA', 'CANCELADO'])('recognizes %s as cancellation and terminal', (status) => {
  expect(isDeliveryCancelled(status)).toBe(true);
  expect(isDeliveryTerminal(status)).toBe(true);
});

it.each(['COMPLETADA', 'FALLIDA', 'ENTREGADO', 'FALLIDO'])('keeps %s terminal without calling it cancelled', (status) => {
  expect(isDeliveryTerminal(status)).toBe(true);
  expect(isDeliveryCancelled(status)).toBe(false);
});

it.each(['PENDIENTE', 'INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'EN_DESTINO', null, undefined])('keeps %s nonterminal', (status) => {
  expect(isDeliveryTerminal(status)).toBe(false);
});

it.each(['', 'corto', 'x'.repeat(501), 'motivo\ninvalido', 'motivo\u200binvalido'])('rejects invalid reasons before HTTP', async (reason) => {
  expect(isCancellationReasonValid(reason)).toBe(false);
  await expect(orderService.cancel('o', reason)).rejects.toThrow('motivo');
  expect(api.patch).not.toHaveBeenCalled();
});

it('requires an explicit reason and trims valid Unicode reasons', async () => {
  await expect(orderService.cancel('o')).rejects.toThrow('motivo');
  const reason = '😀'.repeat(500);
  expect(isCancellationReasonValid(reason)).toBe(true);
  jest.mocked(api.patch).mockResolvedValue({ id: 'a/b', status: 'CANCELADO' });
  await orderService.cancel('a/b', '  ' + reason + '  ');
  expect(api.patch).toHaveBeenCalledWith('/orders/a%2Fb/cancel', { reason });
});

it('propagates server conflicts without falling back to a generic status change', async () => {
  const error = { response: { status: 409, data: { detail: 'Existe evidencia financiera' } } };
  const quiet = jest.spyOn(console, 'error').mockImplementation(() => {});
  jest.mocked(api.patch).mockRejectedValue(error);
  await expect(orderService.cancel('o', 'Cliente solicita cancelar')).rejects.toBe(error);
  expect(api.patch).toHaveBeenCalledTimes(1);
  quiet.mockRestore();
});
