/** Central API client. Requests and refresh work stay within their original session. */
import axios, {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  CanceledError,
  InternalAxiosRequestConfig,
} from 'axios';
import {
  AuthGeneration,
  AuthSession,
  TokenPair,
  captureAuthSession,
  clearStoredTokens,
  commitRefreshedTokens,
  expireAuthSession,
  getStoredTokens,
  isCurrentAuthSession,
  onCredentialsChanged,
  RefreshUnavailableError,
  SessionChangedError,
  SessionExpiredError,
  storeTokens,
  validRefreshPair,
} from '@/lib/auth-session';
export { getStoredTokens, storeTokens, clearStoredTokens } from '@/lib/auth-session';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace(
  /\/$/,
  ''
);
const REFRESH_TIMEOUT_MS = 15000;
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});
interface SessionRequest extends InternalAxiosRequestConfig {
  _authSession?: AuthGeneration;
  _authAttemptToken?: string | null;
  _authRetried?: boolean;
  _authPublic?: boolean;
}
interface RefreshFlight {
  session: AuthSession;
  promise: Promise<TokenPair>;
  cancel: () => void;
}
let refreshFlight: RefreshFlight | null = null;
onCredentialsChanged(() => {
  const previous = refreshFlight;
  refreshFlight = null;
  previous?.cancel();
});

function requestPath(config: InternalAxiosRequestConfig): string {
  const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
  const base = new URL(API_BASE_URL, origin);
  const target = new URL(apiClient.getUri(config), origin);
  const prefix = base.pathname.replace(/\/$/, '');
  if (
    target.origin !== base.origin ||
    (target.pathname !== prefix && !target.pathname.startsWith(`${prefix}/`))
  ) {
    throw new Error('La solicitud no pertenece a la API configurada');
  }
  return target.pathname.slice(prefix.length).replace(/\/$/, '') || '/';
}
const publicAuthPaths = new Set([
  '/auth/login',
  '/auth/register',
  '/auth/register-rider',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/refresh',
]);
function assertCurrent(config: SessionRequest): AuthGeneration {
  if (!config._authSession || !isCurrentAuthSession(config._authSession))
    throw new SessionChangedError();
  return config._authSession;
}
async function performRefresh(session: AuthSession, signal: AbortSignal): Promise<TokenPair> {
  try {
    const response = await axios.post<unknown>(
      `${API_BASE_URL}/auth/refresh`,
      { refresh_token: session.refreshToken },
      {
        headers: { 'Content-Type': 'application/json' },
        signal,
        timeout: REFRESH_TIMEOUT_MS,
      }
    );
    if (!isCurrentAuthSession(session) || signal.aborted) throw new SessionChangedError();
    if (!validRefreshPair(response.data)) throw new RefreshUnavailableError();
    commitRefreshedTokens(session, response.data);
    return response.data;
  } catch (error: unknown) {
    if (!isCurrentAuthSession(session) || signal.aborted) throw new SessionChangedError();
    if (error instanceof RefreshUnavailableError || error instanceof SessionChangedError)
      throw error;
    if (axios.isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0))
      throw new SessionExpiredError();
    throw new RefreshUnavailableError();
  }
}
function refreshSession(session: AuthSession): Promise<TokenPair> {
  if (!isCurrentAuthSession(session)) return Promise.reject(new SessionChangedError());
  if (!session.accessToken || !session.refreshToken)
    return Promise.reject(new SessionExpiredError());
  if (refreshFlight?.session.generation === session.generation) return refreshFlight.promise;
  const controller = new AbortController();
  let rejectCancellation!: (error: Error) => void;
  const cancellation = new Promise<never>((_resolve, reject) => {
    rejectCancellation = reject;
  });
  const timer = setTimeout(() => {
    rejectCancellation(new RefreshUnavailableError());
    controller.abort();
  }, REFRESH_TIMEOUT_MS);
  const promise = Promise.race([performRefresh(session, controller.signal), cancellation]);
  const flight: RefreshFlight = {
    session,
    promise,
    cancel: () => {
      rejectCancellation(new SessionChangedError());
      controller.abort();
    },
  };
  refreshFlight = flight;
  const cleanup = () => {
    clearTimeout(timer);
    if (refreshFlight === flight) refreshFlight = null;
  };
  void promise.then(cleanup, cleanup);
  return promise;
}
function waitForRefresh(
  work: Promise<TokenPair>,
  signal?: InternalAxiosRequestConfig['signal']
): Promise<TokenPair> {
  if (!signal) return work;
  if (signal.aborted) return Promise.reject(new CanceledError('Solicitud cancelada'));
  return new Promise((resolve, reject) => {
    const abort = () => {
      cleanup();
      reject(new CanceledError('Solicitud cancelada'));
    };
    const cleanup = () => signal.removeEventListener?.('abort', abort);
    signal.addEventListener?.('abort', abort);
    void work.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error) => {
        cleanup();
        reject(error);
      }
    );
  });
}
apiClient.interceptors.request.use(
  (incoming: InternalAxiosRequestConfig) => {
    const config = incoming as SessionRequest;
    const path = requestPath(config);
    config._authSession ??= { generation: captureAuthSession().generation };
    assertCurrent(config);
    config._authPublic = publicAuthPaths.has(path);
    if (config.signal?.aborted) throw new CanceledError('Solicitud cancelada');
    const accessToken = config._authPublic ? null : getStoredTokens().accessToken;
    config._authAttemptToken = accessToken;
    if (accessToken) config.headers.set('Authorization', `Bearer ${accessToken}`);
    else config.headers.delete('Authorization');
    return config;
  },
  (error: unknown) => {
    throw error;
  },
  { synchronous: true }
);

apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    assertCurrent(response.config as SessionRequest);
    return response;
  },
  async (error: unknown) => {
    const config = (error as AxiosError | undefined)?.config as SessionRequest | undefined;
    if (!config) throw error;
    const session = assertCurrent(config);
    if (config.signal?.aborted) throw new CanceledError('Solicitud cancelada');
    if (!axios.isAxiosError(error) || error.response?.status !== 401 || config._authPublic)
      throw error;
    if (config._authRetried) {
      if (getStoredTokens().accessToken !== config._authAttemptToken)
        throw new SessionChangedError();
      expireAuthSession(session);
      throw new SessionExpiredError();
    }
    config._authRetried = true;
    const live = captureAuthSession();
    if (!live.accessToken) throw error;
    try {
      // A late 401 for a token already rotated in this session needs no second refresh.
      if (live.accessToken === config._authAttemptToken)
        await waitForRefresh(refreshSession(live), config.signal);
      assertCurrent(config);
      if (config.signal?.aborted) throw new CanceledError('Solicitud cancelada');
      return apiClient(config);
    } catch (refreshError: unknown) {
      if (refreshError instanceof SessionExpiredError) expireAuthSession(session);
      throw refreshError;
    }
  }
);

export const authApi = {
  login: async (email: string, password: string) => {
    clearStoredTokens();
    const form = new URLSearchParams({ username: email, password });
    const response = await apiClient.post<TokenPair>('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    storeTokens(response.data);
    return response.data;
  },
  registerRider: async (data: Record<string, string | Blob | null | undefined>) => {
    const formData = new FormData();
    Object.keys(data).forEach((key) => {
      const value = data[key];
      if (value !== undefined && value !== null) formData.append(key, value);
    });
    const response = await apiClient.post<TokenPair>('/auth/register', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    if (validRefreshPair(response.data)) storeTokens(response.data);
    return response.data;
  },
  refresh: async (refreshToken: string) => {
    const session = captureAuthSession();
    if (refreshToken !== session.refreshToken) throw new SessionChangedError();
    try {
      return await refreshSession(session);
    } catch (error: unknown) {
      if (error instanceof SessionExpiredError) expireAuthSession(session);
      throw error;
    }
  },
  logout: clearStoredTokens,
  me: async () => (await apiClient.get('/users/me')).data,
};
export const api = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    apiClient.get<T>(url, config).then((res) => res.data),
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    apiClient.post<T>(url, data, config).then((res) => res.data),
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    apiClient.put<T>(url, data, config).then((res) => res.data),
  patch: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    apiClient.patch<T>(url, data, config).then((res) => res.data),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    apiClient.delete<T>(url, config).then((res) => res.data),
};
export default apiClient;
