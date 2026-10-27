/**
 * Auth Store - Zustand store para gestión de autenticación
 * OPTIMIZADO: SSR-safe, tipado estricto, persistencia segura y limpieza de recursos.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { authService } from '@/services/auth.service';
import { getStoredTokens, storeTokens, clearStoredTokens } from '@/lib/api';
import { useNotificationStore } from '@/stores/notificationStore';
import { retireLegacyPushDevice } from '@/lib/deviceRegistration';
import { User, UserRole } from '@/types/user';

// ==============================================================================
// CONFIGURACIÓN DE VERSIÓN (Para invalidar caché en producción)
// ==============================================================================
const APP_VERSION = '1.2.1'; 
const STORAGE_KEY = 'delivery360-auth-v' + APP_VERSION;

// Interfaces tipadas
interface LoginCredentials {
  email: string;
  password: string;
}

interface RegisterRiderData {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  phone: string;
  vehicle_type?: string;
  vehicle_plate?: string;
  license_file?: File;
  id_card_file?: File;
}

interface AuthState {
  sessionRevision: number;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  registerRider: (data: RegisterRiderData | FormData) => Promise<void>;
  checkAuth: () => Promise<void>;
  clearError: () => void;
  updateUser: (user: Partial<User>) => void;
  forceLogout: () => void;
}

const isClient = typeof window !== 'undefined';
let authRevision = 0;

const errorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = error.response;
    if (typeof response === 'object' && response !== null && 'data' in response) {
      const data = response.data;
      if (typeof data === 'object' && data !== null) {
        if ('detail' in data && typeof data.detail === 'string') return data.detail;
        if ('message' in data && typeof data.message === 'string') return data.message;
      }
    }
  }
  return fallback;
};

const validateProfile = (user: User): void => {
  if (!user || !user.id || !user.email || user.is_active !== true ||
      !['SUPERADMIN', 'GERENTE', 'OPERADOR', 'REPARTIDOR', 'CLIENTE', 'AUDITOR'].includes(user.role)) {
    throw new Error('Perfil de usuario no habilitado');
  }
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      sessionRevision: 0,
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async ({ email, password }: LoginCredentials) => {
        const revision = ++authRevision;
        useNotificationStore.getState().reset();
        set({ sessionRevision: revision, user: null, isAuthenticated: false, isLoading: true, error: null });
        try {
          const tokensResponse = await authService.login(email, password);
          if (revision !== authRevision) throw new Error('Inicio de sesión cancelado');
          
          const tokensToSave = {
            access_token: tokensResponse.access_token,
            refresh_token: tokensResponse.refresh_token || '', 
          };
          
          storeTokens(tokensToSave);

          const userData = await authService.getProfile();
          if (revision !== authRevision) throw new Error('Sesión cancelada');
          validateProfile(userData);
          
          const user: User = {
            id: userData.id,
            email: userData.email,
            first_name: userData.first_name || '', 
            last_name: userData.last_name || '',
            role: userData.role as UserRole,
            is_active: userData.is_active ?? true,
            created_at: userData.created_at || new Date().toISOString(),
            updated_at: userData.updated_at,
            phone: userData.phone,
            avatar_url: userData.avatar_url,
            is_superuser: userData.is_superuser,
            failed_login_attempts: userData.failed_login_attempts,
            locked_until: userData.locked_until,
            last_login: userData.last_login,
          };

          if (isClient) {
            localStorage.setItem('app_version', APP_VERSION);
            localStorage.setItem('user', JSON.stringify(user));
            
            // Cookie para el token (ya existente)
            document.cookie = `auth-token=${tokensResponse.access_token}; path=/; max-age=86400; SameSite=Lax`;
            
            // CORRECCIÓN CRÍTICA: Crear cookie 'user-data' para que el middleware la lea
            // Codificamos el JSON para evitar problemas con caracteres especiales en cookies
            const userJson = encodeURIComponent(JSON.stringify(user));
            document.cookie = `user-data=${userJson}; path=/; max-age=86400; SameSite=Lax`;
          }
          
          useNotificationStore.getState().setSession(user.id);
          void retireLegacyPushDevice(tokensResponse.access_token);
          set({ 
            user, 
            isAuthenticated: true, 
            isLoading: false 
          });

        } catch (error: unknown) {
          if (revision !== authRevision) throw error;
          const errorMsg = errorMessage(error, 'Credenciales inválidas o error de conexión');

          clearStoredTokens();
          if (isClient) {
            localStorage.removeItem('user');
            document.cookie = 'auth-token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
            document.cookie = 'user-data=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
          }

          set({ 
            error: errorMsg, 
            isLoading: false, 
            isAuthenticated: false, 
            user: null 
          });
          
          throw new Error(errorMsg);
        }
      },

      logout: async () => {
        // Capture the bearer before local cleanup; never use a later account's token.
        const accessToken = getStoredTokens().accessToken;
        get().forceLogout();
        try {
          await authService.logout(accessToken);
        } catch {
          // Local logout is immediate even when the server is unavailable.
        }
      },

      forceLogout: () => {
        const revision = ++authRevision;
        void retireLegacyPushDevice(getStoredTokens().accessToken);
        useNotificationStore.getState().reset();
        clearStoredTokens();
        if (isClient) {
          localStorage.removeItem('user');
          localStorage.removeItem(STORAGE_KEY);
          document.cookie = 'auth-token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
          document.cookie = 'user-data=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT';
        }
        set({ sessionRevision: revision, user: null, isAuthenticated: false, isLoading: false, error: null });
      },

      registerRider: async (data: RegisterRiderData | FormData) => {
        set({ isLoading: true, error: null });
        try {
          await authService.register(data);
          set({ isLoading: false });
        } catch (error: unknown) {
          const msg = errorMessage(error, 'Error en registro');
          set({ error: msg, isLoading: false });
          throw new Error(msg);
        }
      },

      checkAuth: async () => {
        if (get().isLoading) return;
        const revision = ++authRevision;
        useNotificationStore.getState().reset();
        set({ sessionRevision: revision, user: null, isLoading: true, isAuthenticated: false });
        if (isClient) {
          const storedVersion = localStorage.getItem('app_version');
          if (storedVersion !== APP_VERSION) {
            get().forceLogout();
            Object.keys(localStorage).filter(key => key.startsWith('delivery360-auth-v'))
              .forEach(key => localStorage.removeItem(key));
            localStorage.setItem('app_version', APP_VERSION);
            set({ isLoading: false, isAuthenticated: false, user: null });
            return;
          }
        }

        const tokens = getStoredTokens();
        
        if (!tokens.accessToken) {
          get().forceLogout();
          return;
        }

        try {
          const userData = await authService.getProfile();
          if (revision !== authRevision) return;
          validateProfile(userData);
          const liveTokens = getStoredTokens();
          if (!liveTokens.accessToken) {
            get().forceLogout();
            return;
          }
          const user: User = {
            id: userData.id,
            email: userData.email,
            first_name: userData.first_name || '',
            last_name: userData.last_name || '',
            role: userData.role as UserRole,
            is_active: userData.is_active ?? true,
            created_at: userData.created_at || new Date().toISOString(),
            updated_at: userData.updated_at,
            phone: userData.phone,
            avatar_url: userData.avatar_url,
            is_superuser: userData.is_superuser,
          };
          
          if (isClient) {
            localStorage.setItem('user', JSON.stringify(user));
            document.cookie = `auth-token=${liveTokens.accessToken}; path=/; max-age=86400; SameSite=Lax`;
            
            const userJson = encodeURIComponent(JSON.stringify(user));
            document.cookie = `user-data=${userJson}; path=/; max-age=86400; SameSite=Lax`;
          }
          
          useNotificationStore.getState().setSession(user.id);
          void retireLegacyPushDevice(liveTokens.accessToken);
          set({ user, isAuthenticated: true, isLoading: false });
        } catch {
          if (revision !== authRevision) return;
          get().forceLogout();
        }
      },

      clearError: () => set({ error: null }),

      updateUser: (userData: Partial<User>) => {
        const current = get().user;
        if (current) {
          const updated = { ...current, ...userData };
          if (isClient) {
            localStorage.setItem('user', JSON.stringify(updated));
            const userJson = encodeURIComponent(JSON.stringify(updated));
            document.cookie = `user-data=${userJson}; path=/; max-age=86400; SameSite=Lax`;
          }
          set({ user: updated });
        }
      },
    }),
    { 
      name: STORAGE_KEY,
      storage: createJSONStorage(() => (isClient ? localStorage : {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {},
      })),
      // Cached storage is never proof of a valid server session.
      partialize: () => ({}),
      merge: (_persisted, current) => current,
    }
  )
);

export default useAuthStore;