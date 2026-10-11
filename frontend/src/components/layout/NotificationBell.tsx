'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, AlertCircle, Info, Truck, DollarSign } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useNotificationStore } from '@/stores/notificationStore'; // ✅ Store correcto (REST /alerts)
import { useNotifications as useOmnichannelNotifications } from '@/hooks/useNotifications'; // Fase 9: WS + inbox omnicanal
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

// Feature flag Fase 9: campana visible solo si NEXT_PUBLIC_FEATURE_NOTIFICATIONS != 'false'
const FEATURE_NOTIFICATIONS = process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS !== 'false';

// Mapeo de tipos a iconos
export const getIconByType = (type: string) => {
  switch (type) {
    case 'ORDER': return <Truck className="h-4 w-4 text-blue-500" />;
    case 'PAYMENT': return <DollarSign className="h-4 w-4 text-green-500" />;
    case 'ALERT': return <AlertCircle className="h-4 w-4 text-red-500" />;
    default: return <Info className="h-4 w-4 text-gray-500" />;
  }
};

export function NotificationBell() {
  const { notifications, unreadCount, markAsRead, markAllAsRead, fetchNotifications } = useNotificationStore();
  // Fase 9: fuente en vivo (WS + snapshot unread) — una sola conexión por pantalla,
  // coexiste con el store heredado de /alerts sin abrir un segundo pool WS propio.
  const omnichannel = useOmnichannelNotifications({ enabled: FEATURE_NOTIFICATIONS, inboxSize: 10 });
  const [isOpen, setIsOpen] = useState(false);

  if (!FEATURE_NOTIFICATIONS) return null;

  const liveBadge = Math.max(unreadCount, omnichannel.unreadCount);
  const liveItems = omnichannel.items.slice(0, 10);

  // Cargar notificaciones al montar (si el store no lo hace automáticamente)
  useEffect(() => {
    if (isOpen && notifications.length === 0) {
      fetchNotifications();
    }
  }, [isOpen, notifications.length, fetchNotifications]);

  return (
    <div className="relative">
      <Button 
        variant="ghost" 
        size="icon" 
        className="relative hover:bg-gray-100 dark:hover:bg-gray-800"
        onClick={() => setIsOpen(!isOpen)}
      >
        <Bell className="w-5 h-5" />
        {liveBadge > 0 && (
          <span className="absolute top-1.5 right-1.5 w-2.5 h-2.5 bg-red-600 rounded-full border-2 border-white animate-pulse" />
        )}
      </Button>

      {isOpen && (
        <>
          {/* Backdrop para cerrar al hacer clic fuera */}
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          
          <Card className="absolute right-0 top-12 w-80 md:w-96 z-50 shadow-xl border border-gray-200 max-h-[600px] overflow-hidden flex flex-col bg-white">
            {/* Header */}
            <div className="p-4 border-b flex justify-between items-center bg-gray-50/50">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-sm">Notificaciones</h3>
                {liveBadge > 0 && (
                  <Badge variant="destructive" className="h-5 px-1.5 text-xs">{liveBadge}</Badge>
                )}
              </div>
              {unreadCount > 0 && (
                <button 
                  onClick={markAllAsRead} 
                  className="text-xs text-blue-600 hover:text-blue-800 hover:underline flex items-center gap-1 font-medium transition-colors"
                >
                  <CheckCheck className="w-3.5 h-3.5" /> Marcar todas
                </button>
              )}
            </div>

            {/* Lista Scrollable */}
            <div className="overflow-y-auto flex-1">
              {liveItems.length === 0 && notifications.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-8 text-center text-gray-500">
                  <Bell className="h-10 w-10 mb-2 opacity-20" />
                  <p className="text-sm">No hay notificaciones nuevas</p>
                </div>
              ) : (
                <>
                  {liveItems.map((n) => (
                    <div
                      key={`omni-${n.id}`}
                      onClick={() => n.status !== 'LEIDO' && omnichannel.markRead(n.id)}
                      className={`p-4 border-b last:border-0 hover:bg-gray-50 cursor-pointer transition-colors relative ${n.status !== 'LEIDO' ? 'bg-blue-50/30' : ''}`}
                    >
                      {n.status !== 'LEIDO' && (
                        <span className="absolute top-4 left-2 w-2 h-2 bg-blue-600 rounded-full" />
                      )}
                      <div className="flex gap-3 items-start pl-2">
                        <div className="mt-0.5 flex-shrink-0">
                          <Info className="h-4 w-4 text-indigo-500" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">
                            {n.title || n.template_code || 'Notificación'}
                          </p>
                          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{n.body}</p>
                          {n.created_at && (
                            <p className="text-[10px] text-gray-400 mt-2 font-mono">
                              {formatDistanceToNow(new Date(n.created_at), { addSuffix: true, locale: es })}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {notifications.map((notif) => (
                  <div 
                    key={notif.id} 
                    onClick={() => markAsRead(notif.id)}
                    className={`p-4 border-b last:border-0 hover:bg-gray-50 cursor-pointer transition-colors relative group ${!notif.read ? 'bg-blue-50/30' : ''}`}
                  >
                    {!notif.read && (
                      <span className="absolute top-4 left-2 w-2 h-2 bg-blue-600 rounded-full" />
                    )}
                    <div className="flex gap-3 items-start pl-2">
                      <div className="mt-0.5 flex-shrink-0">
                        {getIconByType(notif.type)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium truncate ${!notif.read ? 'text-blue-900' : 'text-gray-900'}`}>
                          {notif.title}
                        </p>
                        <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                          {notif.message}
                        </p>
                        <p className="text-[10px] text-gray-400 mt-2 font-mono">
                          {formatDistanceToNow(new Date(notif.createdAt), { addSuffix: true, locale: es })}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
                </>
              )}
            </div>
            
            {/* Footer opcional si hay muchas */}
            {(notifications.length > 10 || liveItems.length > 0) && (
              <div className="p-2 border-t bg-gray-50 text-center">
                <Link href="/notifications" className="text-xs text-blue-600 hover:underline font-medium">
                  Ver inbox completo
                </Link>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}