'use client';

import { useSyncExternalStore } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { PrivateNotificationInbox } from '@/components/notifications/PrivateNotificationInbox';

export default function NotificationsInboxPage() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user, sessionRevision } = useAuthStore();
  if (process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS === 'false')
    return (
      <p className="p-6 text-slate-600">Las notificaciones están deshabilitadas en este entorno.</p>
    );
  if (!user)
    return <p className="p-6 text-slate-600">Inicia sesión para consultar tus notificaciones.</p>;
  return (
    <PrivateNotificationInbox
      key={JSON.stringify([generation, sessionRevision, user.id, user.role])}
    />
  );
}
