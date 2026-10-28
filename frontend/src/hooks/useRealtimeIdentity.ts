import { useSyncExternalStore } from 'react';
import { useAuthStore } from '@/stores/authStore';
import {
  getCredentialGeneration,
  captureAuthSession,
  onCredentialsChanged,
  getAccessTokenRevision,
  onAccessTokenRotated,
} from '@/lib/auth-session';
export interface RealtimeIdentity {
  userId: string | null;
  revision: number;
  generation: number;
  tokenRevision: number;
}
export function useRealtimeIdentity(): RealtimeIdentity {
  const userId = useAuthStore((s) => (s.isAuthenticated && s.user?.is_active ? s.user.id : null));
  const revision = useAuthStore((s) => s.sessionRevision);
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const tokenRevision = useSyncExternalStore(onAccessTokenRotated, getAccessTokenRevision, () => 0);
  return { userId, revision, generation, tokenRevision };
}
export function currentRealtimeIdentity(
  identity: RealtimeIdentity,
  includeRotation = true
): boolean {
  const auth = useAuthStore.getState();
  if (
    !identity.userId ||
    !auth.isAuthenticated ||
    auth.user?.is_active !== true ||
    auth.user.id !== identity.userId ||
    auth.sessionRevision !== identity.revision
  )
    return false;
  const credentials = captureAuthSession();
  return (
    !!credentials.accessToken &&
    credentials.generation === identity.generation &&
    (!includeRotation || getAccessTokenRevision() === identity.tokenRevision)
  );
}
