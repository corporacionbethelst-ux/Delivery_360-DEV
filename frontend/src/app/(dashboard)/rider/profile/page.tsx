'use client';
import { useSyncExternalStore } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { PrivateRiderProfile } from '@/components/riders/PrivateRiderProfile';
export default function RiderProfilePage() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user, sessionRevision } = useAuthStore();
  if (!user) return <p className="p-6 text-slate-600">Inicia sesión para consultar tu perfil.</p>;
  if (user.role !== 'REPARTIDOR')
    return (
      <p className="p-6 text-slate-600">Este perfil corresponde a una cuenta de repartidor.</p>
    );
  return (
    <PrivateRiderProfile
      key={JSON.stringify([generation, sessionRevision, user.id, user.role])}
      owner={user.id}
      scopeGeneration={generation}
    />
  );
}
