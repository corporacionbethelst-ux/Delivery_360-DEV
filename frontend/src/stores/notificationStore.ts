/**
 * Notification Store - Gestión de notificaciones en tiempo real
 * Optimizado para SSR, con persistencia segura y limpieza automática.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { api } from '@/lib/api';

// ==============================================================================
// TIPOS
// ==============================================================================

export type NotificationType = 'ORDER' | 'PAYMENT' | 'ALERT' | 'SYSTEM' | 'USER';

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  read: boolean;
  createdAt: string; // ISO Date
  actionUrl?: string;
  metadata?: Record<string, any>;
}

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  lastFetched: number | null;

  // Acciones
  fetchNotifications: () => Promise<void>;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  deleteNotification: (id: string) => void;
  addNotification: (notif: Omit<Notification, 'id' | 'read' | 'createdAt'>) => void; // Para WebSocket o manuales
  reset: () => void;
}

// ==============================================================================
// CONFIGURACIÓN
// ==============================================================================

const isClient = typeof window !== 'undefined';
const MAX_NOTIFICATIONS = 50; // Límite local para evitar memoria infinita

// ==============================================================================
// STORE
// ==============================================================================

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      lastFetched: null,

      fetchNotifications: async () => {
        set({ isLoading: true });
        try {
          // ✅ LLAMADA REAL AL BACKEND
          const response = await api.get<Notification[]>('/notifications?limit=50');
          const data = response;

          set({ 
            notifications: data.slice(0, MAX_NOTIFICATIONS), 
            unreadCount: data.filter(n => !n.read).length,
            lastFetched: Date.now(),
            isLoading: false 
          });

        } catch (error) {
          console.error('Error fetching notifications:', error);
          set({ isLoading: false });
        }
      },

      markAsRead: (id) => {
        const current = get().notifications;
        const updated = current.map(n => 
          n.id === id ? { ...n, read: true } : n
        );
        
        set({
          notifications: updated,
          unreadCount: updated.filter(n => !n.read).length
        });

        // Opcional: Llamar al backend para sincronizar
        // api.patch(`/notifications/${id}/read`).catch(console.error);
      },

      markAllAsRead: () => {
        const updated = get().notifications.map(n => ({ ...n, read: true }));
        set({
          notifications: updated,
          unreadCount: 0
        });

        // Opcional: Llamar al backend
        // api.post('/notifications/mark-all-read').catch(console.error);
      },

      deleteNotification: (id) => {
        const updated = get().notifications.filter(n => n.id !== id);
        set({
          notifications: updated,
          unreadCount: updated.filter(n => !n.read).length
        });
      },

      addNotification: (newNotif) => {
        const current = get().notifications;
        const notification: Notification = {
          id: `local-${Date.now()}`, // ID temporal si viene de WS
          read: false,
          createdAt: new Date().toISOString(),
          ...newNotif
        };

        // Insertar al inicio y mantener límite
        const updated = [notification, ...current].slice(0, MAX_NOTIFICATIONS);

        set({
          notifications: updated,
          unreadCount: updated.filter(n => !n.read).length
        });
      },

      reset: () => {
        set({
          notifications: [],
          unreadCount: 0,
          lastFetched: null
        });
      },
    }),
    {
      name: 'delivery360-notifications-v1',
      storage: createJSONStorage(() => (isClient ? localStorage : {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {},
      })),
      // Solo persistimos la lista y el conteo, no el estado de carga
      partialize: (state) => ({ 
        notifications: state.notifications, 
        unreadCount: state.unreadCount,
        lastFetched: state.lastFetched
      }),
      // Evitar hidratación incorrecta en SSR
      skipHydration: false, 
    }
  )
);