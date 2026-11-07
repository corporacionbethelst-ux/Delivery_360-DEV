'use client';
import { Fragment, useEffect, useSyncExternalStore, type PropsWithChildren } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';

export function RiderAuditAccess({ children, riderId }: PropsWithChildren<{ riderId: string }>) {
  const router = useRouter(), { user, isAuthenticated } = useAuthStore();
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const allowed = isAuthenticated && !!user && ['GERENTE', 'SUPERADMIN'].includes(user.role);
  useEffect(() => { if (!allowed) router.replace('/login'); }, [allowed, router]);
  return allowed ? <Fragment key={JSON.stringify([generation, user.id, user.role, riderId])}>{children}</Fragment> : <p role="status" className="p-6">Verificando acceso a auditoría…</p>;
}
