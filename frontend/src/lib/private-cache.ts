/** Session-local cache. Private API data is never persisted to browser storage. */
import {
  captureAuthSession,
  isCurrentAuthSession,
  onCredentialsChanged,
  SessionChangedError,
} from '@/lib/auth-session';
interface Entry {
  data: unknown;
  writtenAt: number;
  expiresAt: number;
  generation: number;
}
const entries = new Map<string, Entry>();
const LIMIT = 500;
function discardLegacyCache(): void {
  try {
    if (typeof window !== 'undefined') localStorage.removeItem('delivery360_cache');
  } catch {
    /* Never restore private disk data. */
  }
}
discardLegacyCache();
onCredentialsChanged(() => {
  entries.clear();
  discardLegacyCache();
});
export function readPrivateCache<T>(key: string): { data: T; ageMs: number } | null {
  const session = captureAuthSession();
  if (!session.accessToken) return null;
  const entry = entries.get(key);
  if (!entry) return null;
  if (entry.generation !== session.generation || Date.now() >= entry.expiresAt) {
    entries.delete(key);
    return null;
  }
  entries.delete(key);
  entries.set(key, entry);
  return { data: entry.data as T, ageMs: Date.now() - entry.writtenAt };
}
export const cacheUtils = {
  get: <T>(key: string): T | null => {
    const entry = readPrivateCache<T>(key);
    return entry ? entry.data : null;
  },
  set: <T>(key: string, data: T, ttl: number, expectedGeneration?: number): void => {
    const session = captureAuthSession();
    if (expectedGeneration !== undefined && expectedGeneration !== session.generation)
      throw new SessionChangedError();
    if (!session.accessToken || !isCurrentAuthSession(session)) return;
    if (!Number.isFinite(ttl) || ttl < 0) throw new Error('Tiempo de caché no válido');
    entries.delete(key);
    if (ttl === 0) return;
    entries.set(key, {
      data,
      generation: session.generation,
      writtenAt: Date.now(),
      expiresAt: Date.now() + ttl * 1000,
    });
    while (entries.size > LIMIT) {
      const oldest = entries.keys().next().value;
      if (oldest !== undefined) entries.delete(oldest);
    }
  },
  clear: (): void => {
    entries.clear();
    discardLegacyCache();
  },
  remove: (key: string): void => {
    entries.delete(key);
  },
  removePattern: (pattern: string): void => {
    entries.forEach((_value, key) => {
      if (key.includes(pattern)) entries.delete(key);
    });
  },
  // Compatibility only: disk persistence is retired, including automatic timers/listeners.
  persist: discardLegacyCache,
  restore: discardLegacyCache,
};
