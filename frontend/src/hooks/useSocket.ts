import { useEffect, useState, useCallback } from "react";
import { onCredentialsChanged } from "@/lib/auth-session";

export interface Notification {
  id: string;
  title: string;
  message: string;
  type: "INFO" | "WARNING" | "ERROR" | "SUCCESS";
  timestamp: string;
  read: boolean;
  data?: unknown;
}
/** Legacy local feed adapter. Real inbox transport lives in useNotifications.
 * No random orders, fabricated remote connection or background demo timers.
 */
export function useSocket() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  useEffect(() => onCredentialsChanged(() => setNotifications([])), []);
  const markAsRead = useCallback(
    (id: string) =>
      setNotifications((rows) =>
        rows.map((row) => (row.id === id ? { ...row, read: true } : row)),
      ),
    [],
  );
  const markAllAsRead = useCallback(
    () =>
      setNotifications((rows) => rows.map((row) => ({ ...row, read: true }))),
    [],
  );
  const clearNotifications = useCallback(() => setNotifications([]), []);
  const addNotification = useCallback(
    (input: Omit<Notification, "id" | "timestamp" | "read">) => {
      const notification = {
        ...input,
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        read: false,
      };
      setNotifications((rows) => [notification, ...rows].slice(0, 50));
    },
    [],
  );
  return {
    isConnected: false,
    notifications,
    markAsRead,
    markAllAsRead,
    clearNotifications,
    unreadCount: notifications.filter((row) => !row.read).length,
    addNotification,
  };
}
export default useSocket;
