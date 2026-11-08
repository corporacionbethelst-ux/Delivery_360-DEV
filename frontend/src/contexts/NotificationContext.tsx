'use client';

import React, { createContext, useContext } from 'react';
import { useSocket } from '@/hooks/useSocket';

interface NotificationContextType {
  unreadCount: number;
  notifications: any[];
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  isConnected: boolean;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const {isConnected,notifications,markAsRead,markAllAsRead,unreadCount}=useSocket();

  return (
    <NotificationContext.Provider value={{
      unreadCount,
      notifications,
      markAsRead,
      markAllAsRead,
      isConnected
    }}>
      {children}
    </NotificationContext.Provider>
  );
}

export const useNotifications = () => {
  const context = useContext(NotificationContext);
  if (!context) throw new Error('useNotifications must be used within NotificationProvider');
  return context;
};