import { act, cleanup, renderHook } from '@testing-library/react';
import { AxiosError, AxiosHeaders } from 'axios';
import client from '@/lib/api';
import { useLiveMapData } from '@/hooks/useLiveMapData';
import { useAuthStore } from '@/stores/authStore';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { credentials, profile } from '../../test-utils/realtime';
const original = client.defaults.adapter;
afterEach(() => {
  cleanup();
  clearStoredTokens();
  client.defaults.adapter = original;
  jest.restoreAllMocks();
});
it('recognizes a forbidden HTTP response after the real rider service normalizes it', async () => {
  localStorage.clear();
  storeTokens(credentials);
  useAuthStore.setState({ user: profile, isAuthenticated: true, sessionRevision: 1 });
  const log = jest.spyOn(console, 'error').mockImplementation(() => {});
  let forbidden = false;
  client.defaults.adapter = async (config) => {
    const base = { config, status: 200, statusText: 'OK', headers: new AxiosHeaders() };
    if (config.url === '/riders') {
      if (forbidden)
        throw new AxiosError('denied', 'ERR_BAD_REQUEST', config, undefined, {
          ...base,
          status: 403,
          data: { detail: 'No autorizado' },
        });
      return { ...base, data: [{ id: 'r', last_lat: 1, last_lng: 2, is_online: true }] };
    }
    if (config.url?.startsWith('/orders')) return { ...base, data: [] };
    return {
      ...base,
      data: {
        riders: [],
        alerts: [],
        stats: { activeCount: 1, onlineTotal: 1, staleOver15Min: 0, avgWaitMinutes: null },
      },
    };
  };
  const { result } = renderHook(() => useLiveMapData(false));
  await act(async () => {});
  expect(result.current.riders).toHaveLength(1);
  forbidden = true;
  await act(async () => {
    await result.current.fetchData(true);
  });
  expect(result.current.riders).toEqual([]);
  expect(result.current.orders).toEqual([]);
  expect(result.current.error).toContain('Verifica tu sesión y permisos');
  expect(JSON.stringify(log.mock.calls)).not.toContain('realtime-access-a');
});
