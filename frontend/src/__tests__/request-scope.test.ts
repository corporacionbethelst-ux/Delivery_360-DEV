import { RequestScope } from '@/lib/request-scope';
import { deferred } from '../../test-utils/realtime';
beforeEach(() => jest.useFakeTimers());
afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
});
it('resolves a successful request and clears its timer', async () => {
  const scope = new RequestScope();
  await expect(scope.run(async () => 42)).resolves.toBe(42);
  expect(jest.getTimerCount()).toBe(0);
});
it('bounds a transport that never observes its abort signal', async () => {
  const scope = new RequestScope(),
    late = deferred<string>();
  let signal!: AbortSignal;
  const work = scope
    .run((s) => {
      signal = s;
      return late.promise;
    })
    .catch((error) => error);
  jest.advanceTimersByTime(15000);
  expect((await work).message).toBe('Tiempo de solicitud agotado');
  expect(signal.aborted).toBe(true);
  late.resolve('obsolete');
  await Promise.resolve();
  expect(jest.getTimerCount()).toBe(0);
});
it('cancels all waiters immediately and cannot start more work after cleanup', async () => {
  const scope = new RequestScope(),
    late = deferred<string>(),
    call = jest.fn(() => late.promise);
  const a = scope.run(call).catch((error) => error),
    b = scope.run(call).catch((error) => error);
  scope.cancelAll();
  expect(jest.getTimerCount()).toBe(0);
  expect((await a).message).toBe('Solicitud cancelada');
  expect((await b).message).toBe('Solicitud cancelada');
  await expect(scope.run(call)).rejects.toThrow('cancelada');
  expect(call).toHaveBeenCalledTimes(2);
  late.resolve('obsolete');
});
it('contains synchronous failures without leaking an active timer', async () => {
  const scope = new RequestScope();
  await expect(
    scope.run(() => {
      throw new Error('failure');
    })
  ).rejects.toThrow('failure');
  expect(jest.getTimerCount()).toBe(0);
});
