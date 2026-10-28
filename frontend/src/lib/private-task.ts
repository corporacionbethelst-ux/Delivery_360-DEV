/** Bind a store action to the credentials present when that action began. */
import type { StoreApi } from 'zustand';
import {
  captureAuthSession,
  isCurrentAuthSession,
  onCredentialsChanged,
  SessionChangedError,
} from '@/lib/auth-session';

export function capturePrivateTask() {
  const session = captureAuthSession();
  const isCurrent = () => !!session.accessToken && isCurrentAuthSession(session);
  const assertCurrent = () => {
    if (!isCurrent()) throw new SessionChangedError();
  };
  assertCurrent();
  return { assertCurrent, isCurrent, generation: session.generation };
}
/** Global module stores contain only ephemeral private data and retain their actions. */
export function resetOnSessionChange<T>(store: StoreApi<T>): () => void {
  return onCredentialsChanged(() => store.setState(store.getInitialState(), true));
}
