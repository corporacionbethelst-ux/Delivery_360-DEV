'use client';
import { Fragment, type PropsWithChildren, useSyncExternalStore } from 'react';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { useAuthStore } from '@/stores/authStore';

export function PayoutSessionBoundary({ children }: PropsWithChildren) {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user } = useAuthStore();
  return <Fragment key={JSON.stringify([generation, user?.id, user?.role])}>{children}</Fragment>;
}
