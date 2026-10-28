import { AxiosError, AxiosHeaders, InternalAxiosRequestConfig } from 'axios';
import React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useLiveMapData } from '@/hooks/useLiveMapData';
import { useAuthStore } from '@/stores/authStore';
import {
  storeTokens,
  clearStoredTokens,
  captureAuthSession,
  commitRefreshedTokens,
} from '@/lib/auth-session';
import { riderService } from '@/services/rider.service';
import { orderService } from '@/services/order.service';
import { trackingService } from '@/services/tracking.service';
import { credentials, profile, deferred } from '../../test-utils/realtime';
jest.mock('@/services/rider.service', () => ({ riderService: { getAll: jest.fn() } }));
jest.mock('@/services/order.service', () => ({ orderService: { getAll: jest.fn() } }));
jest.mock('@/services/tracking.service', () => ({
  trackingService: { getActiveRiders: jest.fn() },
}));
const riders = jest.mocked(riderService.getAll),
  orders = jest.mocked(orderService.getAll),
  stats = jest.mocked(trackingService.getActiveRiders);
const row = (id = 'r') => ({
  id,
  first_name: 'Test',
  last_name: 'Rider',
  last_lat: 0,
  last_lng: 0,
  is_online: true,
});
beforeEach(() => {
  jest.useFakeTimers();
  localStorage.clear();
  storeTokens(credentials);
  useAuthStore.setState({ user: profile, isAuthenticated: true, sessionRevision: 1 });
  riders.mockReset().mockResolvedValue([row()] as never);
  orders
    .mockReset()
    .mockResolvedValue([{ id: 'o', status: 'EN_RUTA', delivery_lat: 0, delivery_lng: 0 }] as never);
  stats.mockReset().mockResolvedValue({
    riders: [],
    alerts: [],
    stats: { activeCount: 1, onlineTotal: 1, staleOver15Min: 0, avgWaitMinutes: null },
  });
});
afterEach(() => {
  cleanup();
  clearStoredTokens();
  jest.clearAllTimers();
  jest.useRealTimers();
});
it('starts no REST work without a verified profile', async () => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  renderHook(() => useLiveMapData(false));
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(riders).not.toHaveBeenCalled();
  expect(orders).not.toHaveBeenCalled();
});
it('publishes one complete snapshot and uses the optional statistics', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  expect(result.current.riders[0].lat).toBe(0);
  expect(result.current.orders[0].lat).toBe(0);
  expect(result.current.liveStats?.activeCount).toBe(1);
  expect(result.current.isLoadingInitial).toBe(false);
});
it('does not publish a partial snapshot before orders complete', async () => {
  const late = deferred<never>();
  orders.mockReturnValueOnce(late.promise);
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  expect(result.current.riders).toEqual([]);
  await act(async () => {
    late.resolve([] as never);
  });
  expect(result.current.riders).toHaveLength(1);
});
it('optional statistics failure keeps the mandatory map usable', async () => {
  stats.mockRejectedValueOnce(new Error('private stats diagnostic'));
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  expect(result.current.riders).toHaveLength(1);
  expect(result.current.liveStats).toBeNull();
  expect(result.current.error).toBeNull();
});
it('a mandatory refresh failure retains the last completed snapshot and shows only a generic error', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  riders.mockRejectedValueOnce(new Error('private URL and token'));
  await act(async () => {
    await result.current.fetchData(true);
  });
  expect(result.current.riders[0].id).toBe('r');
  expect(result.current.error).toContain('No se pudo actualizar');
  expect(result.current.error).not.toContain('token');
  expect(result.current.isRefreshing).toBe(false);
});
it('an old owner result or failure cannot overwrite owner B', async () => {
  const late = deferred<never>();
  riders.mockReturnValueOnce(late.promise);
  const { result } = renderHook(() => useLiveMapData(false));
  act(() => {
    storeTokens({ access_token: 'b-access', refresh_token: 'b-refresh' });
    useAuthStore.setState({ user: { ...profile, id: 'owner-b' }, sessionRevision: 2 });
  });
  await act(async () => {});
  await act(async () => {
    late.resolve([row('old-a')] as never);
  });
  expect(result.current.riders.map((r) => r.id)).toEqual(['r']);
});
it('logout clears local map payloads and retires its polling timer', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  act(() => {
    useAuthStore.getState().forceLogout();
  });
  expect(result.current.riders).toEqual([]);
  expect(result.current.orders).toEqual([]);
  const before = riders.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(60000);
  });
  expect(riders).toHaveBeenCalledTimes(before);
});
it('uses 10-second fallback polling while disconnected and 60-second polling when connected', async () => {
  const { rerender } = renderHook(({ connected }) => useLiveMapData(connected), {
    initialProps: { connected: false },
  });
  await act(async () => {});
  await act(async () => {
    jest.advanceTimersByTime(10000);
  });
  expect(riders).toHaveBeenCalledTimes(2);
  rerender({ connected: true });
  await act(async () => {});
  const before = riders.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(10000);
  });
  expect(riders).toHaveBeenCalledTimes(before);
  await act(async () => {
    jest.advanceTimersByTime(50000);
  });
  expect(riders).toHaveBeenCalledTimes(before + 1);
});
it('the latest manual refresh wins over an older pending request', async () => {
  const late = deferred<never>();
  riders.mockReturnValueOnce(late.promise);
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {
    await result.current.fetchData(true);
    late.resolve([row('old')] as never);
  });
  expect(result.current.riders[0].id).toBe('r');
});
it('ordinary token rotation preserves the current snapshot and polling interval', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  const before = riders.mock.calls.length;
  act(() =>
    commitRefreshedTokens(captureAuthSession(), {
      access_token: 'rotated',
      refresh_token: 'refresh-rotated',
    })
  );
  expect(result.current.riders).toHaveLength(1);
  expect(riders).toHaveBeenCalledTimes(before);
});
it('callbacks retained after unmount cannot start another refresh or update local riders', async () => {
  const { result, unmount } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  const fetch = result.current.fetchData,
    set = result.current.setRiders;
  unmount();
  const before = riders.mock.calls.length;
  await act(async () => {
    await fetch(true);
    set([]);
  });
  expect(riders).toHaveBeenCalledTimes(before);
  expect(jest.getTimerCount()).toBe(0);
});
it('StrictMode cannot publish a discarded first setup', async () => {
  const late = deferred<never>();
  riders.mockReturnValueOnce(late.promise);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <React.StrictMode>{children}</React.StrictMode>
  );
  const { result } = renderHook(() => useLiveMapData(false), { wrapper });
  await act(async () => {
    late.resolve([row('obsolete')] as never);
  });
  expect(result.current.riders.map((r) => r.id)).toEqual(['r']);
});

it('permission rejection clears the former snapshot instead of presenting it as fallback data', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  riders.mockRejectedValueOnce(
    new AxiosError('denied', 'ERR_BAD_REQUEST', config, undefined, {
      config,
      data: {},
      status: 403,
      statusText: 'Forbidden',
      headers: {},
    })
  );
  await act(async () => {
    await result.current.fetchData(true);
  });
  expect(result.current.riders).toEqual([]);
  expect(result.current.orders).toEqual([]);
  expect(result.current.liveStats).toBeNull();
  expect(result.current.error).toContain('Verifica tu sesión y permisos');
});

it('does not send anonymous map requests if credentials disappear before authStore updates', async () => {
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  const before = riders.mock.calls.length;
  act(() => clearStoredTokens());
  await act(async () => {
    jest.advanceTimersByTime(20000);
    await result.current.fetchData(true);
  });
  expect(riders).toHaveBeenCalledTimes(before);
  expect(result.current.riders).toEqual([]);
});
