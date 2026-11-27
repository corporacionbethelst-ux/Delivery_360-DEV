/** Local invalidation only: no notification contents or credentials. */
const listeners = new Set<(generation: number) => void>();
export function onNotificationInboxChanged(listener: (generation: number) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function notificationInboxChanged(generation: number): void {
  listeners.forEach((listener) => {
    try {
      listener(generation);
    } catch {
      /* Other views still refresh. */
    }
  });
}
