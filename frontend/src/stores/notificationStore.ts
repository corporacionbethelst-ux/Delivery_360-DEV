/** Operational alerts are private session data: no browser persistence. */
import { create } from 'zustand';
import { api } from '@/lib/api';
import { onCredentialsChanged } from '@/lib/auth-session';

export type NotificationType = 'ORDER' | 'PAYMENT' | 'ALERT' | 'SYSTEM' | 'USER' | 'OPERATIONAL';
export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  read: boolean;
  createdAt: string;
  actionUrl?: string;
  metadata?: Record<string, unknown>;
}
interface Alert {
  id: string;
  type: string;
  title: string;
  description: string;
  createdAt: string;
  isRead: boolean;
  orderId?: string | null;
  riderId?: string | null;
}
interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  lastFetched: number | null;
  sessionUserId: string | null;
  setSession: (userId: string | null) => void;
  fetchNotifications: () => Promise<void>;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  deleteNotification: (id: string) => void;
  addNotification: (notif: Omit<Notification, 'id' | 'read' | 'createdAt'>) => void;
  reset: () => void;
}
const MAX_NOTIFICATIONS = 50;
let revision = 0;
function removeLegacyCache(): void {
  try {
    if (typeof window !== 'undefined') localStorage.removeItem('delivery360-notifications-v1');
  } catch {
    /* Storage denial does not restore private data. */
  }
}
removeLegacyCache();

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  isLoading: false,
  lastFetched: null,
  sessionUserId: null,
  setSession: (userId) => {
    ++revision;
    removeLegacyCache();
    set({
      sessionUserId: userId,
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      lastFetched: null,
    });
  },
  fetchNotifications: async () => {
    if (!get().sessionUserId) return;
    const request = ++revision;
    set({ isLoading: true });
    try {
      const alerts = await api.get<Alert[]>('/alerts?limit=50');
      if (request !== revision) return;
      const notifications: Notification[] = alerts.slice(0, MAX_NOTIFICATIONS).map((alert) => ({
        id: alert.id,
        type: 'OPERATIONAL',
        title: alert.title,
        message: alert.description,
        read: alert.isRead,
        createdAt: alert.createdAt,
        actionUrl: alert.orderId ? `/operator/orders/${alert.orderId}` : undefined,
        metadata: {
          alertType: alert.type,
          orderId: alert.orderId ?? undefined,
          riderId: alert.riderId ?? undefined,
        },
      }));
      set({
        notifications,
        unreadCount: notifications.filter((n) => !n.read).length,
        lastFetched: Date.now(),
        isLoading: false,
      });
    } catch {
      if (request === revision) set({ isLoading: false });
    }
  },
  markAsRead: (id) => {
    if (!get().sessionUserId) return;
    ++revision;
    const notifications = get().notifications.map((n) => (n.id === id ? { ...n, read: true } : n));
    set({
      notifications,
      unreadCount: notifications.filter((n) => !n.read).length,
      isLoading: false,
    });
    void api.patch(`/alerts/${encodeURIComponent(id)}/read`).catch(() => {});
  },
  markAllAsRead: () => {
    if (!get().sessionUserId) return;
    ++revision;
    set({
      notifications: get().notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
      isLoading: false,
    });
    void api.post('/alerts/read-all').catch(() => {});
  },
  deleteNotification: (id) => {
    if (!get().sessionUserId) return;
    ++revision;
    const notifications = get().notifications.filter((n) => n.id !== id);
    set({
      notifications,
      unreadCount: notifications.filter((n) => !n.read).length,
      isLoading: false,
    });
  },
  addNotification: (notif) => {
    if (!get().sessionUserId) return;
    ++revision;
    const notification: Notification = {
      ...notif,
      id: `local-${Date.now()}`,
      read: false,
      createdAt: new Date().toISOString(),
    };
    const notifications = [notification, ...get().notifications].slice(0, MAX_NOTIFICATIONS);
    set({
      notifications,
      unreadCount: notifications.filter((n) => !n.read).length,
      isLoading: false,
    });
  },
  reset: () => get().setSession(null),
}));

// Advance the request revision too, so an already accepted old REST result cannot revive alerts.
onCredentialsChanged(() => useNotificationStore.getState().reset());
