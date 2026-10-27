import React from 'react';
import { act, renderHook } from '@testing-library/react';
import { useNotifications } from '@/hooks/useNotifications';
import { useAuthStore } from '@/stores/authStore';
import { User } from '@/types/user';
const profile: User = {
  id: 'owner-1',
  email: 'owner@example.test',
  first_name: 'Owner',
  last_name: 'Test',
  role: 'OPERADOR',
  is_active: true,
  created_at: '',
  updated_at: '',
};

class Socket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: any;
  onmessage: any;
  onclose: any;
  onerror: any;
  send = jest.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  close = jest.fn(() => {
    this.readyState = 3;
  });
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
  end(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}
const original = global.WebSocket,
  originalFetch = global.fetch;
const fetcher = jest.fn();
beforeEach(() => {
  jest.useFakeTimers();
  Socket.instances = [];
  fetcher.mockReset();
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ items: [], unread_count: 0 }) });
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: Socket });
  global.fetch = fetcher;
  localStorage.setItem('access_token', 'unit-test-token');
  useAuthStore.setState({ user: profile, isAuthenticated: true, sessionRevision: 1 });
});
afterEach(() => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  jest.clearAllTimers();
  jest.useRealTimers();
  global.WebSocket = original;
  global.fetch = originalFetch;
  localStorage.clear();
});

it('continues REST polling while an open socket has no realtime transport', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  const socket = Socket.instances[0];
  act(() => {
    socket.open();
    socket.message({ type: 'CONNECTED', unread_count: 3, realtime_available: false });
  });
  expect(result.current.isConnected).toBe(false);
  expect(result.current.unreadCount).toBe(3);
  const before = fetcher.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(fetcher.mock.calls.length).toBeGreaterThan(before);
  expect(Socket.instances).toHaveLength(1);
  unmount();
  expect(socket.close).toHaveBeenCalled();
});
it('does not poll just because an authorized realtime connection is idle', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  act(() => {
    Socket.instances[0].open();
    Socket.instances[0].message({ type: 'CONNECTED', unread_count: 0, realtime_available: true });
  });
  const before = fetcher.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(result.current.isConnected).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(before);
  expect(Socket.instances[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'ping' }));
  unmount();
});
it('uses canonical counts and updates one item when Redis repeats an event', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  const socket = Socket.instances[0];
  act(() => socket.open());
  const message = {
    type: 'NEW_NOTIFICATION',
    id: 'known',
    title: 'Persisted',
    channel: 'IN_APP',
    status: 'PENDIENTE',
    unread_count: 4,
  };
  act(() => {
    socket.message(message);
    socket.message(message);
  });
  expect(result.current.items).toHaveLength(1);
  expect(result.current.unreadCount).toBe(4);
  act(() => socket.message({ ...message, status: 'LEIDO', unread_count: 3 }));
  expect(result.current.items[0].status).toBe('LEIDO');
  expect(result.current.unreadCount).toBe(3);
  unmount();
});
it('stops reconnecting after a policy close and keeps the REST fallback', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  act(() => {
    Socket.instances[0].open();
    Socket.instances[0].end(1008);
  });
  const before = fetcher.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(Socket.instances).toHaveLength(1);
  expect(result.current.isConnected).toBe(false);
  expect(fetcher.mock.calls.length).toBeGreaterThan(before);
  unmount();
});

const inboxItem = (id = 'private-a') => ({
  id,
  channel: 'IN_APP',
  status: 'PENDIENTE',
  body: 'Private owner data',
});
const response = (id = 'private-a') => ({
  ok: true,
  json: async () => ({ items: [inboxItem(id)], unread_count: 1 }),
});
function pendingResponse() {
  let resolve!: (value: unknown) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
it('does not open transports or perform REST operations without a verified session', async () => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {
    await result.current.refreshInbox();
    await result.current.markRead('private');
    jest.advanceTimersByTime(120000);
  });
  expect(Socket.instances).toHaveLength(0);
  expect(fetcher).not.toHaveBeenCalled();
  expect(result.current.items).toEqual([]);
  unmount();
});
it('does not fall back to a legacy token key when the current bearer is absent', async () => {
  localStorage.removeItem('access_token');
  localStorage.setItem('token', 'legacy-unsafe');
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  expect(Socket.instances).toHaveLength(0);
  expect(fetcher).not.toHaveBeenCalled();
  expect(result.current.isConnected).toBe(false);
  unmount();
});
it('aborts pending REST work and ignores its completion after logout', async () => {
  const delayed = pendingResponse();
  fetcher.mockReturnValueOnce(delayed.promise);
  const { result, unmount } = renderHook(() => useNotifications());
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
  act(() => useAuthStore.getState().forceLogout());
  expect(signal.aborted).toBe(true);
  await act(async () => {
    delayed.resolve(response());
  });
  expect(result.current.items).toEqual([]);
  expect(result.current.unreadCount).toBe(0);
  expect(Socket.instances[0].close).toHaveBeenCalled();
  unmount();
});
it('a saved callback from owner A cannot inject messages or reconnect after owner B starts', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  const old = Socket.instances[0],
    message = old.onmessage,
    close = old.onclose,
    open = old.onopen,
    error = old.onerror;
  act(() => useAuthStore.setState({ user: { ...profile, id: 'owner-b' }, sessionRevision: 2 }));
  await act(async () => {});
  const next = Socket.instances[1];
  act(() => {
    message({
      data: JSON.stringify({ type: 'NEW_NOTIFICATION', ...inboxItem(), unread_count: 8 }),
    });
    close({ code: 1011 });
    open({});
    error({});
  });
  await act(async () => {
    jest.advanceTimersByTime(1000);
  });
  expect(Socket.instances).toHaveLength(2);
  expect(old.close).toHaveBeenCalled();
  expect(next.close).not.toHaveBeenCalled();
  expect(result.current.items).toEqual([]);
  expect(result.current.unreadCount).toBe(0);
  expect(result.current.error).toBeNull();
  unmount();
});
it('disabling then enabling creates a fresh generation and rejects the old REST result', async () => {
  const old = pendingResponse();
  fetcher.mockReturnValueOnce(old.promise);
  const { result, rerender, unmount } = renderHook(({ enabled }) => useNotifications({ enabled }), {
    initialProps: { enabled: true },
  });
  rerender({ enabled: false });
  expect(result.current.items).toEqual([]);
  fetcher.mockResolvedValueOnce(response('new-generation'));
  rerender({ enabled: true });
  await act(async () => {});
  await act(async () => {
    old.resolve(response('old-generation'));
  });
  expect(result.current.items.map((n) => n.id)).toEqual(['new-generation']);
  expect(Socket.instances).toHaveLength(2);
  unmount();
});
it('same-account reauthentication still rejects a response from the previous session', async () => {
  const old = pendingResponse();
  fetcher.mockReturnValueOnce(old.promise);
  const { result, unmount } = renderHook(() => useNotifications());
  fetcher.mockResolvedValueOnce(response('new-session'));
  act(() => useAuthStore.setState({ sessionRevision: 2 }));
  await act(async () => {});
  await act(async () => {
    old.resolve(response('old-session'));
  });
  expect(result.current.items.map((n) => n.id)).toEqual(['new-session']);
  unmount();
});
it('late failures from an unmounted instance do not expose errors in the next instance', async () => {
  const old = pendingResponse();
  fetcher.mockReturnValueOnce(old.promise);
  const first = renderHook(() => useNotifications());
  first.unmount();
  const next = renderHook(() => useNotifications());
  await act(async () => {
    old.reject(new Error('private network diagnostic'));
  });
  expect(next.result.current.error).toBeNull();
  next.unmount();
});
it('an older REST snapshot cannot erase a newer live event or its recovered history', async () => {
  const old = pendingResponse();
  fetcher.mockReturnValueOnce(old.promise);
  const { result, unmount } = renderHook(() => useNotifications());
  fetcher.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ items: [inboxItem('live'), inboxItem('history')], unread_count: 2 }),
  });
  act(() =>
    Socket.instances[0].message({ type: 'NEW_NOTIFICATION', ...inboxItem('live'), unread_count: 2 })
  );
  await act(async () => {});
  await act(async () => {
    old.resolve(response('stale'));
  });
  expect(result.current.items.map((n) => n.id)).toEqual(['live', 'history']);
  expect(result.current.unreadCount).toBe(2);
  unmount();
});
it('latest REST refresh wins when completions arrive out of order', async () => {
  const old = pendingResponse();
  fetcher.mockReturnValueOnce(old.promise);
  const { result, unmount } = renderHook(() => useNotifications());
  fetcher.mockResolvedValueOnce(response('latest'));
  await act(async () => {
    await result.current.refreshInbox();
    old.resolve(response('old'));
  });
  expect(result.current.items.map((n) => n.id)).toEqual(['latest']);
  unmount();
});
it('updates optimistic unread count once for repeated read actions', async () => {
  fetcher.mockResolvedValueOnce(response());
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  await act(async () => {
    await result.current.markRead('private-a');
  });
  expect(result.current.unreadCount).toBe(0);
  await act(async () => {
    await result.current.markRead('private-a');
  });
  expect(result.current.unreadCount).toBe(0);
  expect(result.current.items[0].status).toBe('LEIDO');
  unmount();
});
it('a failed read from the previous session cannot refetch using the next account', async () => {
  fetcher.mockResolvedValueOnce(response());
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  const failed = pendingResponse();
  fetcher.mockReturnValueOnce(failed.promise);
  let work!: Promise<void>;
  act(() => {
    work = result.current.markRead('private-a');
  });
  act(() => useAuthStore.setState({ user: { ...profile, id: 'owner-b' }, sessionRevision: 2 }));
  await act(async () => {});
  const calls = fetcher.mock.calls.length;
  await act(async () => {
    failed.reject(new Error('private error'));
    await work;
  });
  expect(fetcher).toHaveBeenCalledTimes(calls);
  expect(result.current.items).toEqual([]);
  unmount();
});
it('filters non-IN_APP data and invalid counts in REST snapshots', async () => {
  fetcher.mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      items: [inboxItem('valid'), { ...inboxItem('sms'), channel: 'SMS' }, null],
      unread_count: -3,
    }),
  });
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  expect(result.current.items.map((n) => n.id)).toEqual(['valid']);
  expect(result.current.unreadCount).toBe(0);
  unmount();
});
it('does not fabricate IDs or display other-channel live payloads', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  act(() => {
    Socket.instances[0].message({ type: 'NEW_NOTIFICATION', channel: 'IN_APP' });
    Socket.instances[0].message({ type: 'NEW_NOTIFICATION', ...inboxItem(), channel: 'PUSH' });
  });
  expect(result.current.items).toEqual([]);
  expect(result.current.unreadCount).toBe(0);
  unmount();
});
it('a bearer rotation retires the old socket and restores live transport at the next poll', async () => {
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  const old = Socket.instances[0];
  act(() => old.open());
  localStorage.setItem('access_token', 'rotated');
  act(() => old.message({ type: 'NEW_NOTIFICATION', ...inboxItem(), unread_count: 5 }));
  expect(result.current.items).toEqual([]);
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(old.close).toHaveBeenCalled();
  expect(Socket.instances[1].url).toContain('token=rotated');
  expect(fetcher.mock.calls.at(-1)?.[1].headers.Authorization).toBe('Bearer rotated');
  unmount();
});
it('reconnects with the configured backoff and clears all timers on unmount', async () => {
  const { unmount } = renderHook(() =>
    useNotifications({ reconnectIntervalMs: 700, maxRetries: 1 })
  );
  await act(async () => {});
  act(() => Socket.instances[0].end(1011));
  act(() => jest.advanceTimersByTime(699));
  expect(Socket.instances).toHaveLength(1);
  act(() => jest.advanceTimersByTime(1));
  expect(Socket.instances).toHaveLength(2);
  act(() => Socket.instances[1].end(1011));
  act(() => jest.advanceTimersByTime(15000));
  expect(Socket.instances).toHaveLength(2);
  unmount();
  expect(jest.getTimerCount()).toBe(0);
});
it('uses a generic REST error instead of a private network exception', async () => {
  fetcher.mockRejectedValueOnce(new Error('private token and URL'));
  const { result, unmount } = renderHook(() => useNotifications());
  await act(async () => {});
  expect(result.current.error).toBe('No se pudo actualizar el inbox');
  unmount();
});

it('React StrictMode cleanup cannot revive the first generation', async () => {
  const old = pendingResponse(); fetcher.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response('current'));
  const wrapper = ({ children }: { children: React.ReactNode }) => <React.StrictMode>{children}</React.StrictMode>;
  const { result, unmount } = renderHook(() => useNotifications(), { wrapper });
  await act(async () => { old.resolve(response('discarded')); });
  expect(Socket.instances).toHaveLength(2); expect(Socket.instances[0].close).toHaveBeenCalled();
  expect(result.current.items.map(n => n.id)).toEqual(['current']); unmount(); expect(jest.getTimerCount()).toBe(0);
});
