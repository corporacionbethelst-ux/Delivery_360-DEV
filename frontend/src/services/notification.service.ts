import { api } from '@/lib/api';

export type NotificationType = 'INFO' | 'WARNING' | 'SUCCESS' | 'ERROR' | 'ASSIGNMENT';
export type NotificationStatus = 'LEIDO' | 'NO_LEIDO';

export interface Notification {
  id: string;
  user_id: string;
  type: NotificationType;
  status: NotificationStatus;
  title: string;
  message: string;
  related_entity_id?: string | null; // ID de orden, turno, etc.
  created_at: string;
  read_at?: string | null;
}

// Filtros opcionales para notificaciones
export interface NotificationFilters {
  limit?: number;
  status?: NotificationStatus;
}

export const notificationService = {
  /**
   * Obtener lista de notificaciones con filtros opcionales.
   */
  getAll: async (params?: Readonly<NotificationFilters>): Promise<Notification[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.status) queryParams.append('status', params.status);
      
      const query = queryParams.toString() ? `?${queryParams}` : '';
      return await api.get<Notification[]>(`/notifications${query}`);
    } catch (error) {
      console.error('[NotificationService] Error fetching notifications:', error);
      throw error;
    }
  },

  /**
   * Marcar una notificación específica como leída.
   */
  markAsRead: async (id: string): Promise<Notification> => {
    if (!id) throw new Error('[NotificationService] ID de notificación requerido');
    
    try {
      return await api.patch<Notification>(`/notifications/${id}/read`);
    } catch (error) {
      console.error(`[NotificationService] Error marking notification ${id} as read:`, error);
      throw error;
    }
  },

  /**
   * Marcar TODAS las notificaciones del usuario como leídas.
   */
  markAllAsRead: async (): Promise<void> => {
    try {
      await api.post('/notifications/read-all');
    } catch (error) {
      console.error('[NotificationService] Error marking all notifications as read:', error);
      throw error;
    }
  },

  /**
   * Obtener conteo de notificaciones no leídas.
   */
  getUnreadCount: async (): Promise<{ count: number }> => {
    try {
      return await api.get<{ count: number }>('/notifications/unread-count');
    } catch (error) {
      console.error('[NotificationService] Error fetching unread count:', error);
      // Retornar 0 en caso de error para no romper la UI
      return { count: 0 };
    }
  }
};