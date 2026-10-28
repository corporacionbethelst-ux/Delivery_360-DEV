import React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useTrackingWebSocket } from '@/hooks/useTrackingWebSocket';
import { useAuthStore } from '@/stores/authStore';
import {
  storeTokens,
  clearStoredTokens,
  captureAuthSession,
  commitRefreshedTokens,
} from '@/lib/auth-session';
import { profile, credentials, TestSocket } from '../../test-utils/realtime';
const original = global.WebSocket;
const position = (id = 'r', lat = 1) => ({
  riderId: id,
  lat,
  lng: 2,
  timestamp: '2026-10-27T10:00:00Z',
});
beforeEach(() => {
  jest.useFakeTimers();
  localStorage.clear();
  storeTokens(credentials);
  useAuthStore.setState({ user: profile, isAuthenticated: true, sessionRevision: 1 });
  TestSocket.instances = [];
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: TestSocket });
});
afterEach(() => {
  cleanup();
  clearStoredTokens();
  jest.clearAllTimers();
  jest.useRealTimers();
  global.WebSocket = original;
  jest.restoreAllMocks();
});
it('does not open or reconnect without a verified profile', () => {
  useAuthStore.setState({ isAuthenticated: false, user: null });
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  act(() => result.current.reconnect());
  expect(TestSocket.instances).toHaveLength(0);
  expect(result.current.positions).toEqual([]);
});
it('does not rescue the obsolete token storage key', () => {
  clearStoredTokens();
  localStorage.setItem('token', 'legacy');
  renderHook(() => useTrackingWebSocket('dashboard'));
  expect(TestSocket.instances).toHaveLength(0);
});
it('accepts the real channel protocol, zero coordinates and a latency measurement at performance zero', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard', { heartbeatSec: 1 }));
  const socket = TestSocket.instances[0];
  act(() => socket.open());
  const clock = jest.spyOn(performance, 'now').mockReturnValue(0);
  act(() => jest.advanceTimersByTime(1000));
  expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ action: 'ping' }));
  clock.mockReturnValue(15);
  act(() => {
    socket.message({ type: 'pong' });
    socket.message({ type: 'POSITION_UPDATE', payload: position('r', 0) });
  });
  expect(result.current.latencyMs).toBe(15);
  expect(result.current.positions[0].lat).toBe(0);
  expect(result.current.isConnected).toBe(true);
});
it('ignores callbacks saved from owner A after owner B starts', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard', { heartbeatSec: 1 }));
  const old = TestSocket.instances[0];
  const oldReconnect = result.current.reconnect;
  const message = old.onmessage!,
    open = old.onopen!,
    close = old.onclose!,
    error = old.onerror!;
  act(() => {
    storeTokens({ access_token: 'b-access', refresh_token: 'b-refresh' });
    useAuthStore.setState({ user: { ...profile, id: 'owner-b' }, sessionRevision: 2 });
  });
  const next = TestSocket.instances[1];
  act(() => {
    oldReconnect();
    next.open();
    message({
      data: JSON.stringify({ type: 'POSITION_UPDATE', payload: position() }),
    } as MessageEvent);
    open(new Event('open'));
    close({ code: 1011 } as CloseEvent);
    error(new Event('error'));
    jest.advanceTimersByTime(1000);
  });
  expect(result.current.positions).toEqual([]);
  expect(TestSocket.instances).toHaveLength(2);
  expect(old.close).toHaveBeenCalled();
  expect(next.close).not.toHaveBeenCalled();
  expect(old.send).not.toHaveBeenCalled();
  expect(next.send).toHaveBeenCalledTimes(1);
});
it('logout clears positions and closes a socket while it is still connecting', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  const old = TestSocket.instances[0];
  act(() => old.message({ type: 'POSITION_UPDATE', payload: position() }));
  expect(result.current.positions).toHaveLength(1);
  act(() => clearStoredTokens());
  expect(old.close).toHaveBeenCalled();
  expect(result.current.positions).toEqual([]);
  expect(result.current.isConnected).toBe(false);
});
it('manual reconnect retires the old socket and its saved close callback cannot schedule another one', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  const old = TestSocket.instances[0],
    close = old.onclose!;
  act(() => result.current.reconnect());
  expect(old.close).toHaveBeenCalled();
  act(() => {
    close({ code: 1011 } as CloseEvent);
    jest.advanceTimersByTime(1000);
  });
  expect(TestSocket.instances).toHaveLength(2);
});
it.each([1008, 4001])('policy close %i does not automatically reconnect', (code) => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  act(() => {
    TestSocket.instances[0].end(code);
    jest.advanceTimersByTime(60000);
  });
  expect(TestSocket.instances).toHaveLength(1);
  expect(result.current.error).toContain('No autorizado');
});
it('bounds pending connection attempts with an opening deadline', () => {
  const { result, unmount } = renderHook(() =>
    useTrackingWebSocket('dashboard', {
      openTimeoutMs: 100,
      reconnectIntervalMs: 10,
      maxRetries: 1,
    })
  );
  act(() => jest.advanceTimersByTime(110));
  expect(TestSocket.instances).toHaveLength(2);
  expect(TestSocket.instances[0].close).toHaveBeenCalled();
  act(() => jest.advanceTimersByTime(100));
  expect(result.current.error).toContain('agotaron');
  unmount();
  expect(jest.getTimerCount()).toBe(0);
});
it('respects the retry budget even if unstable sockets open without a server handshake', () => {
  renderHook(() => useTrackingWebSocket('dashboard', { reconnectIntervalMs: 10, maxRetries: 2 }));
  act(() => {
    TestSocket.instances[0].open();
    TestSocket.instances[0].end(1011);
    jest.advanceTimersByTime(10);
  });
  act(() => {
    TestSocket.instances[1].open();
    TestSocket.instances[1].end(1011);
    jest.advanceTimersByTime(20);
  });
  act(() => {
    TestSocket.instances[2].open();
    TestSocket.instances[2].end(1011);
    jest.advanceTimersByTime(1000);
  });
  expect(TestSocket.instances).toHaveLength(3);
});
it('server handshake resets the consecutive failure budget', () => {
  renderHook(() => useTrackingWebSocket('dashboard', { reconnectIntervalMs: 10, maxRetries: 1 }));
  act(() => {
    TestSocket.instances[0].end(1011);
    jest.advanceTimersByTime(10);
  });
  act(() => {
    TestSocket.instances[1].open();
    TestSocket.instances[1].message({ type: 'CONNECTED', channel: 'dashboard' });
    TestSocket.instances[1].end(1011);
    jest.advanceTimersByTime(10);
  });
  expect(TestSocket.instances).toHaveLength(3);
});
it('retains the latest position and bounds unique riders in a validated batch', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard', { maxPositions: 2 }));
  const socket = TestSocket.instances[0];
  act(() => {
    socket.message({ type: 'POSITION_UPDATE', payload: position('r', 3) });
    socket.message({
      type: 'POSITION_UPDATE',
      payload: { ...position('r', 1), timestamp: '2026-10-27T09:00:00Z' },
    });
  });
  expect(result.current.positions[0].lat).toBe(3);
  act(() =>
    socket.message({
      type: 'BATCH_UPDATE',
      payload: [position('b'), { riderId: 'bad', lat: NaN, lng: 1 }, position('c')],
    })
  );
  expect(result.current.positions.map((p) => p.riderId)).toEqual(['b', 'c']);
});
it('channel changes hide old positions before applying the new stream', () => {
  const { result, rerender } = renderHook(({ channel }) => useTrackingWebSocket(channel), {
    initialProps: { channel: 'dashboard' },
  });
  const old = TestSocket.instances[0];
  act(() => old.message({ type: 'POSITION_UPDATE', payload: position() }));
  rerender({ channel: 'rider:123e4567-e89b-42d3-a456-426614174000' });
  expect(result.current.positions).toEqual([]);
  expect(old.close).toHaveBeenCalled();
  expect(TestSocket.instances[1].url).toContain('/rider%3A');
});
it('disable and re-enable cannot revive an old callback', () => {
  const { result, rerender } = renderHook(
    ({ enabled }) => useTrackingWebSocket('dashboard', { enabled }),
    { initialProps: { enabled: true } }
  );
  const old = TestSocket.instances[0],
    message = old.onmessage!;
  rerender({ enabled: false });
  rerender({ enabled: true });
  act(() =>
    message({
      data: JSON.stringify({ type: 'POSITION_UPDATE', payload: position() }),
    } as MessageEvent)
  );
  expect(result.current.positions).toEqual([]);
  expect(TestSocket.instances).toHaveLength(2);
});
it('an ordinary refresh replaces the socket immediately while preserving same-user positions', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  const old = TestSocket.instances[0];
  act(() => old.message({ type: 'POSITION_UPDATE', payload: position() }));
  act(() =>
    commitRefreshedTokens(captureAuthSession(), {
      access_token: 'new-access',
      refresh_token: 'new-refresh',
    })
  );
  expect(old.close).toHaveBeenCalled();
  expect(TestSocket.instances[1].url).toContain('token=new-access');
  expect(result.current.positions).toHaveLength(1);
});
it('inline option objects do not reopen an unchanged connection', () => {
  const { rerender } = renderHook(() => useTrackingWebSocket('dashboard', { enabled: true }));
  rerender();
  rerender();
  expect(TestSocket.instances).toHaveLength(1);
});
it('StrictMode cleanup retires the first CONNECTING socket', () => {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <React.StrictMode>{children}</React.StrictMode>
  );
  const { unmount } = renderHook(() => useTrackingWebSocket('dashboard'), { wrapper });
  expect(TestSocket.instances).toHaveLength(2);
  expect(TestSocket.instances[0].close).toHaveBeenCalled();
  unmount();
  expect(TestSocket.instances[1].close).toHaveBeenCalled();
  expect(jest.getTimerCount()).toBe(0);
});
it('an invalid channel never reaches the WebSocket constructor', () => {
  const { result } = renderHook(() => useTrackingWebSocket('rider:invalid'));
  expect(result.current.error).toContain('Canal');
  expect(TestSocket.instances).toHaveLength(0);
});
it('heartbeat send failure retires the broken socket and uses the bounded reconnect path', () => {
  renderHook(() => useTrackingWebSocket('dashboard', { heartbeatSec: 1, reconnectIntervalMs: 10 }));
  const old = TestSocket.instances[0];
  old.send.mockImplementation(() => {
    throw new Error('private socket details');
  });
  act(() => {
    old.open();
    jest.advanceTimersByTime(1010);
  });
  expect(old.close).toHaveBeenCalled();
  expect(TestSocket.instances).toHaveLength(2);
});
it('malformed or oversized frames cannot publish positions or raw server diagnostics', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  const socket = TestSocket.instances[0];
  act(() => {
    socket.onmessage?.({ data: 'invalid json' } as MessageEvent);
    socket.onmessage?.({ data: 'x'.repeat(262145) } as MessageEvent);
    socket.message({ type: 'error', message: 'private server URL and credentials' });
  });
  expect(result.current.positions).toEqual([]);
  expect(result.current.error).toBe('El servidor no pudo procesar el mensaje de tracking');
});

it('policy rejection retires previously visible coordinates instead of retaining an authorized-looking stream', () => {
  const { result } = renderHook(() => useTrackingWebSocket('dashboard'));
  const socket = TestSocket.instances[0];
  act(() => {
    socket.open();
    socket.message({ type: 'POSITION_UPDATE', payload: position() });
  });
  expect(result.current.positions).toHaveLength(1);
  act(() => socket.end(1008));
  expect(result.current.positions).toEqual([]);
  expect(result.current.lastUpdate).toBeNull();
});
