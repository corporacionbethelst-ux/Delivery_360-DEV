/** Abort and bound a group of browser requests, including adapters that ignore cancellation. */
export class RequestScope {
  private closed = false;
  private pending = new Set<() => void>();
  run<T>(work: (signal: AbortSignal) => Promise<T>, timeoutMs = 15000): Promise<T> {
    if (this.closed) return Promise.reject(new Error('Solicitud cancelada'));
    const controller = new AbortController();
    let rejectCancellation!: (error: Error) => void;
    const cancellation = new Promise<never>((_resolve, reject) => {
      rejectCancellation = reject;
    });
    const cancel = () => {
      clearTimeout(timer);
      rejectCancellation(new Error('Solicitud cancelada'));
      controller.abort();
    };
    const timer = setTimeout(() => {
      rejectCancellation(new Error('Tiempo de solicitud agotado'));
      controller.abort();
    }, timeoutMs);
    this.pending.add(cancel);
    let operation: Promise<T>;
    try {
      operation = work(controller.signal);
    } catch (error) {
      operation = Promise.reject(error);
    }
    const result = Promise.race([operation, cancellation]);
    const cleanup = () => {
      clearTimeout(timer);
      this.pending.delete(cancel);
    };
    void result.then(cleanup, cleanup);
    return result;
  }
  cancelAll(): void {
    this.closed = true;
    this.pending.forEach((cancel) => cancel());
    this.pending.clear();
  }
}
