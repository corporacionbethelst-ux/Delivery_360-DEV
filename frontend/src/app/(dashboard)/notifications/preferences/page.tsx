'use client';
import { useSyncExternalStore } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { PrivateNotificationPreferences } from '@/components/notifications/PrivateNotificationPreferences';
export default function NotificationPreferencesPage() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user, sessionRevision } = useAuthStore();
  if (process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS === 'false')
    return (
      <p className="p-6 text-slate-600">Las notificaciones están deshabilitadas en este entorno.</p>
    );
  if (!user)
    return <p className="p-6 text-slate-600">Inicia sesión para consultar tus preferencias.</p>;
  return (
    <PrivateNotificationPreferences
      key={JSON.stringify([generation, sessionRevision, user.id, user.role])}
      scopeGeneration={generation}
      role={user.role}
    />
  );
}
