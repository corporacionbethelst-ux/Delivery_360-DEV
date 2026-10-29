/** One complete REST snapshot per verified scope; overlapping and retired reads cannot publish. */
import { isAxiosError } from 'axios';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { SetStateAction } from 'react';
import { useRealtimeIdentity, currentRealtimeIdentity } from '@/hooks/useRealtimeIdentity';
import { riderService } from '@/services/rider.service';
import { orderService } from '@/services/order.service';
import { trackingService, DashboardStats } from '@/services/tracking.service';
import { riderSnapshot, orderSnapshot, SnapshotRider } from '@/lib/live-map-data';
import type { MapOrder } from '@/components/maps/DeliveryMap';
interface Snapshot {
  key: string;
  riders: SnapshotRider[];
  orders: MapOrder[];
  onlineWithoutLocation: number;
  liveStats: DashboardStats | null;
  isLoadingInitial: boolean;
  isRefreshing: boolean;
  error: string | null;
  accessDenied: boolean;
}
const empty = {
  riders: [] as SnapshotRider[],
  orders: [] as MapOrder[],
  onlineWithoutLocation: 0,
  liveStats: null,
  isLoadingInitial: true,
  isRefreshing: false,
  error: null,
  accessDenied: false,
};
export function useLiveMapData(isConnected: boolean) {
  const { userId, revision, generation, tokenRevision } = useRealtimeIdentity();
  const key = JSON.stringify([userId, revision, generation]);
  const scope = useRef(key);
  scope.current = key;
  const pending = useRef<{ key: string; request: number } | null>(null);
  const alive = useRef(false),
    sequence = useRef(0);
  const [snapshot, setSnapshot] = useState<Snapshot>({ ...empty, key });
  const fetchData = useCallback(
    async (isManual = false) => {
      const identity = { userId, revision, generation, tokenRevision };
      const current = () =>
        alive.current && scope.current === key && currentRealtimeIdentity(identity, false);
      if (!current() || (!isManual && pending.current?.key === key)) return;
      const request = ++sequence.current;
      const work = { key, request };
      pending.current = work;
      setSnapshot((previous) => ({
        ...(previous.key === key ? previous : { ...empty, key }),
        isRefreshing: isManual,
        error: null,
      }));
      try {
        const [rawRiders, rawOrders, live] = await Promise.all([
          riderService.getAll(),
          orderService.getAll({ limit: 50 }),
          trackingService.getActiveRiders().catch(() => null),
        ]);
        if (!current() || request !== sequence.current) return;
        const mapped = riderSnapshot(rawRiders);
        setSnapshot({
          key,
          ...mapped,
          orders: orderSnapshot(rawOrders),
          liveStats: live?.stats ?? null,
          isLoadingInitial: false,
          isRefreshing: false,
          error: null,
          accessDenied: false,
        });
      } catch (error: unknown) {
        const status = isAxiosError(error)
          ? error.response?.status
          : error instanceof Error && 'status' in error && typeof error.status === 'number'
            ? error.status
            : undefined;
        const denied = status === 401 || status === 403;
        if (current() && request === sequence.current)
          setSnapshot((previous) => ({
            ...(denied ? { ...empty, key } : previous.key === key ? previous : { ...empty, key }),
            isLoadingInitial: false,
            isRefreshing: false,
            accessDenied: denied || (previous.key === key && previous.accessDenied),
            error: denied
              ? 'No se pudo acceder al mapa. Verifica tu sesión y permisos.'
              : 'No se pudo actualizar el mapa. Se conservan los últimos datos disponibles.',
          }));
      } finally {
        if (pending.current === work) pending.current = null;
      }
    },
    [userId, revision, generation, tokenRevision, key]
  );
  // A token rotation can change fetchData without changing this scope; keep the latest callback for polling.
  const refresh = useRef(fetchData);
  refresh.current = fetchData;
  useEffect(() => {
    alive.current = true;
    ++sequence.current;
    if (userId) void refresh.current();
    const interval = userId
      ? setInterval(
          () => {
            void refresh.current();
          },
          isConnected ? 60000 : 10000
        )
      : undefined;
    return () => {
      alive.current = false;
      if (pending.current?.key === key) pending.current = null;
      clearInterval(interval);
    };
  }, [key, userId, isConnected]);
  const setRiders = useCallback(
    (change: SetStateAction<SnapshotRider[]>) => {
      const identity = { userId, revision, generation, tokenRevision };
      if (!alive.current || scope.current !== key || !currentRealtimeIdentity(identity, false))
        return;
      setSnapshot((previous) =>
        previous.key === key
          ? { ...previous, riders: typeof change === 'function' ? change(previous.riders) : change }
          : previous
      );
    },
    [key, userId, revision, generation, tokenRevision]
  );
  const visible =
    snapshot.key === key && userId ? snapshot : { ...empty, isLoadingInitial: !!userId };
  return { ...visible, fetchData, setRiders };
}
