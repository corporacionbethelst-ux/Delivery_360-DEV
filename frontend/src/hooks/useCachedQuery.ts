/** Private queries are scoped to a credential generation, key and component lifetime. */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { capturePrivateTask } from '@/lib/private-task';
import { cacheUtils, readPrivateCache } from '@/lib/private-cache';
export { cacheUtils } from '@/lib/private-cache';

interface UseCachedQueryOptions<T> {
  key: string;
  queryFn: () => Promise<T>;
  ttl?: number;
  enabled?: boolean;
  staleTime?: number;
}
interface UseCachedQueryResult<T> {
  data: T | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  isFromCache: boolean;
  refetch: () => Promise<void>;
}
interface State<T> {
  key: string;
  generation: number;
  data: T | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  isFromCache: boolean;
}
export function useCachedQuery<T>({
  key,
  queryFn,
  ttl = 300,
  enabled = true,
  staleTime = 60,
}: UseCachedQueryOptions<T>): UseCachedQueryResult<T> {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const query = useRef(queryFn);
  query.current = queryFn;
  const scope = useRef({ key, generation, enabled });
  scope.current = { key, generation, enabled };
  const alive = useRef(false),
    sequence = useRef(0);
  const [state, setState] = useState<State<T>>({
    key,
    generation,
    data: null,
    isLoading: enabled,
    isError: false,
    error: null,
    isFromCache: false,
  });
  const fetchData = useCallback(async () => {
    const sameScope = () =>
      alive.current &&
      scope.current.enabled &&
      scope.current.key === key &&
      scope.current.generation === generation;
    if (!enabled || !sameScope()) return;
    let task: ReturnType<typeof capturePrivateTask>;
    try {
      task = capturePrivateTask();
    } catch {
      setState({
        key,
        generation,
        data: null,
        isLoading: false,
        isError: false,
        error: null,
        isFromCache: false,
      });
      return;
    }
    if (getCredentialGeneration() !== generation) return;
    const request = ++sequence.current;
    setState((previous) => ({
      key,
      generation,
      data: previous.key === key && previous.generation === generation ? previous.data : null,
      isLoading: true,
      isError: false,
      error: null,
      isFromCache:
        previous.key === key && previous.generation === generation && previous.isFromCache,
    }));
    try {
      const result = await query.current();
      task.assertCurrent();
      if (!sameScope() || request !== sequence.current) return;
      cacheUtils.set(key, result, ttl, task.generation);
      setState({
        key,
        generation,
        data: result,
        isLoading: false,
        isError: false,
        error: null,
        isFromCache: false,
      });
    } catch {
      if (!task.isCurrent() || !sameScope() || request !== sequence.current) return;
      const cached = readPrivateCache<T>(key);
      setState({
        key,
        generation,
        data: cached ? cached.data : null,
        isLoading: false,
        isError: !cached,
        error: cached ? null : new Error('No se pudieron cargar los datos'),
        isFromCache: !!cached,
      });
    }
  }, [enabled, key, generation, ttl]);
  useEffect(() => {
    alive.current = true;
    ++sequence.current;
    if (enabled) {
      const cached = readPrivateCache<T>(key);
      if (getCredentialGeneration() === generation) {
        if (cached) {
          setState({
            key,
            generation,
            data: cached.data,
            isLoading: false,
            isError: false,
            error: null,
            isFromCache: true,
          });
          if (cached.ageMs >= staleTime * 1000) void fetchData();
        } else {
          void fetchData();
        }
      }
    }
    return () => {
      alive.current = false;
    };
  }, [enabled, key, generation, staleTime, fetchData]);
  const visible =
    enabled && state.key === key && state.generation === generation
      ? state
      : { data: null, isLoading: enabled, isError: false, error: null, isFromCache: false };
  return {
    data: visible.data,
    isLoading: visible.isLoading,
    isError: visible.isError,
    error: visible.error,
    isFromCache: visible.isFromCache,
    refetch: fetchData,
  };
}
