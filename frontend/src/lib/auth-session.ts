/** Browser credentials and their local generation; server authorization remains mandatory. */
export interface TokenPair {
  access_token: string;
  refresh_token: string;
}
export interface AuthTokens {
  accessToken: string | null;
  refreshToken: string | null;
}
export interface AuthGeneration {
  generation: number;
}
export interface AuthSession extends AuthTokens, AuthGeneration {}
const empty: AuthTokens = { accessToken: null, refreshToken: null };
let tokens: AuthTokens = { ...empty };
let generation = 0;
let ignoreStorage = false;
const listeners = new Set<() => void>();
const rotationListeners = new Set<() => void>();
let accessTokenRevision = 0;
export const getAccessTokenRevision = (): number => accessTokenRevision;
export function onAccessTokenRotated(listener: () => void): () => void {
  rotationListeners.add(listener);
  return () => {
    rotationListeners.delete(listener);
  };
}
const browser = () => typeof window !== 'undefined';

function invalidate(): void {
  ++generation;
  listeners.forEach((listener) => {
    try {
      listener();
    } catch {
      /* One subscriber must not block credential cleanup or other stores. */
    }
  });
}
/** Internal invalidation only. Does not expose credentials to subscribers. */
export function onCredentialsChanged(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function getStoredTokens(): AuthTokens {
  if (!browser()) return { ...empty };
  if (!ignoreStorage) {
    try {
      const stored = {
        accessToken: localStorage.getItem('access_token'),
        refreshToken: localStorage.getItem('refresh_token'),
      };
      if (
        stored.accessToken !== tokens.accessToken ||
        stored.refreshToken !== tokens.refreshToken
      ) {
        tokens = stored;
        invalidate();
      }
    } catch {
      /* Memory remains usable when the browser denies storage. */
    }
  }
  return { ...tokens };
}
/** Pure snapshot for React subscriptions; observing storage remains an explicit read. */
export const getCredentialGeneration = (): number => generation;
export function captureAuthSession(): AuthSession {
  return { ...getStoredTokens(), generation };
}
export function isCurrentAuthSession(session: AuthGeneration): boolean {
  getStoredTokens();
  return session.generation === generation;
}
export class SessionChangedError extends Error {
  constructor() {
    super('La sesión cambió; vuelve a realizar la solicitud');
    this.name = 'SessionChangedError';
  }
}
export class SessionExpiredError extends Error {
  constructor() {
    super('La sesión expiró; inicia sesión nuevamente');
    this.name = 'SessionExpiredError';
  }
}
export class RefreshUnavailableError extends Error {
  constructor() {
    super('No se pudo renovar la sesión; intenta nuevamente');
    this.name = 'RefreshUnavailableError';
  }
}
const validToken = (value: unknown): value is string =>
  typeof value === 'string' &&
  value.length > 0 &&
  value.length <= 16384 &&
  /^[\x21-\x7e]+$/.test(value);
export function validRefreshPair(value: unknown): value is TokenPair {
  if (!value || typeof value !== 'object') return false;
  const pair = value as Partial<TokenPair>;
  return validToken(pair.access_token) && validToken(pair.refresh_token);
}
function removeStoredCredentials(): boolean {
  let removed = true;
  for (const key of ['access_token', 'refresh_token', 'user', 'auth-storage']) {
    try {
      localStorage.removeItem(key);
    } catch {
      removed = false;
    }
  }
  try {
    document.cookie = 'auth-token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
    document.cookie = 'user-data=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
  } catch {
    /* Cookie denial cannot restore credentials in memory. */
  }
  return removed;
}
function persist(pair: TokenPair): void {
  try {
    localStorage.setItem('access_token', pair.access_token);
    localStorage.setItem('refresh_token', pair.refresh_token);
    tokens = { accessToken: pair.access_token, refreshToken: pair.refresh_token };
    ignoreStorage = false;
  } catch {
    tokens = { ...empty };
    ignoreStorage = true;
    invalidate();
    removeStoredCredentials();
    window.dispatchEvent(new Event('delivery360-session-expired'));
    throw new Error('No se pudieron guardar las credenciales');
  }
}
export function storeTokens(pair: TokenPair): void {
  if (!browser()) return;
  if (
    !validToken(pair.access_token) ||
    (pair.refresh_token !== '' && !validToken(pair.refresh_token))
  ) {
    throw new Error('Credenciales recibidas no válidas');
  }
  invalidate();
  persist(pair);
}
/** A successful refresh rotates this generation; a new login must use storeTokens. */
export function commitRefreshedTokens(session: AuthSession, pair: TokenPair): void {
  const live = getStoredTokens();
  if (
    !isCurrentAuthSession(session) ||
    live.accessToken !== session.accessToken ||
    live.refreshToken !== session.refreshToken
  ) {
    throw new SessionChangedError();
  }
  if (!validRefreshPair(pair)) throw new RefreshUnavailableError();
  persist(pair);
  try {
    if (document.cookie.split(';').some((cookie) => cookie.trim().startsWith('auth-token='))) {
      document.cookie = `auth-token=${pair.access_token}; path=/; max-age=86400; SameSite=Lax`;
    }
  } catch {
    /* The next verified profile check also synchronizes navigation cookies. */
  }
  ++accessTokenRevision;
  rotationListeners.forEach((listener) => {
    try {
      listener();
    } catch {
      /* Other transports still rotate. */
    }
  });
}
export function clearStoredTokens(): void {
  tokens = { ...empty };
  ignoreStorage = true;
  invalidate();
  if (browser()) ignoreStorage = !removeStoredCredentials();
}
export function expireAuthSession(session: AuthGeneration): void {
  if (!isCurrentAuthSession(session)) return;
  clearStoredTokens();
  if (browser()) window.dispatchEvent(new Event('delivery360-session-expired'));
}
