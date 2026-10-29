import { startHeartbeat } from '@/lib/realtime-heartbeat';
beforeEach(() => jest.useFakeTimers());
afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
  jest.restoreAllMocks();
});
it('waits for the first tick and ignores unsolicited pongs', () => {
  const send = jest.fn(),
    lost = jest.fn();
  const hb = startHeartbeat(send, lost, 1000, 200);
  expect(hb.pong()).toBeNull();
  jest.advanceTimersByTime(999);
  expect(send).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(send).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(200);
  expect(lost).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});
it('keeps one outstanding ping without extending its deadline on later ticks', () => {
  const send = jest.fn(),
    lost = jest.fn();
  startHeartbeat(send, lost, 1, 1000);
  jest.advanceTimersByTime(1000);
  expect(send).toHaveBeenCalledTimes(1);
  expect(lost).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(lost).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(60000);
  expect(send).toHaveBeenCalledTimes(1);
});
it('accepts pong, clears its deadline and starts a fresh deadline for the next ping', () => {
  const send = jest.fn(),
    lost = jest.fn();
  const hb = startHeartbeat(send, lost, 1000, 200);
  jest.advanceTimersByTime(1000);
  jest.advanceTimersByTime(100);
  expect(hb.pong()).toBe(100);
  expect(hb.pong()).toBeNull();
  jest.advanceTimersByTime(900);
  expect(send).toHaveBeenCalledTimes(2);
  jest.advanceTimersByTime(199);
  expect(lost).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(lost).toHaveBeenCalledTimes(1);
});
it('measures a ping sent at performance zero and clamps a backwards clock', () => {
  const clock = jest.spyOn(performance, 'now').mockReturnValue(0);
  const hb = startHeartbeat(jest.fn(), jest.fn(), 1000);
  jest.advanceTimersByTime(1000);
  clock.mockReturnValue(15);
  expect(hb.pong()).toBe(15);
  clock.mockReturnValue(100);
  jest.advanceTimersByTime(1000);
  clock.mockReturnValue(99);
  expect(hb.pong()).toBe(0);
  hb.stop();
});
it.each([false, true])('stop is idempotent before or after a pending ping (%s)', (pending) => {
  const send = jest.fn(),
    lost = jest.fn(),
    hb = startHeartbeat(send, lost, 1000);
  if (pending) jest.advanceTimersByTime(1000);
  const count = send.mock.calls.length;
  hb.stop();
  hb.stop();
  expect(hb.pong()).toBeNull();
  jest.advanceTimersByTime(100000);
  expect(send).toHaveBeenCalledTimes(count);
  expect(lost).not.toHaveBeenCalled();
  expect(jest.getTimerCount()).toBe(0);
});
it('a send exception retires all timers and reports loss only once', () => {
  const send = jest.fn(() => {
      throw new Error('private transport diagnostic');
    }),
    lost = jest.fn();
  const hb = startHeartbeat(send, lost, 1000);
  jest.advanceTimersByTime(100000);
  expect(send).toHaveBeenCalledTimes(1);
  expect(lost).toHaveBeenCalledTimes(1);
  expect(hb.pong()).toBeNull();
  expect(jest.getTimerCount()).toBe(0);
});
it('handles a synchronous pong received while sending the ping', () => {
  const lost = jest.fn();
  let hb: ReturnType<typeof startHeartbeat>;
  const send = jest.fn(() => hb.pong());
  hb = startHeartbeat(send, lost, 1000, 200);
  jest.advanceTimersByTime(5000);
  expect(send).toHaveBeenCalledTimes(5);
  expect(lost).not.toHaveBeenCalled();
  hb.stop();
});
it.each([0, -1, NaN, Infinity, 300001])(
  'invalid interval %s falls back without a hot loop',
  (interval) => {
    const send = jest.fn(),
      lost = jest.fn(),
      hb = startHeartbeat(send, lost, interval);
    jest.advanceTimersByTime(29999);
    expect(send).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(send).toHaveBeenCalledTimes(1);
    hb.stop();
  }
);
it.each([0, -1, NaN, Infinity, 30001])(
  'invalid pong timeout %s uses the bounded default',
  (timeout) => {
    const lost = jest.fn();
    startHeartbeat(jest.fn(), lost, 1000, timeout);
    jest.advanceTimersByTime(10999);
    expect(lost).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(lost).toHaveBeenCalledTimes(1);
  }
);
