/** One outstanding ping and a response deadline, owned by a single socket. */
export interface Heartbeat {
  pong(): number | null;
  stop(): void;
}
export function startHeartbeat(
  sendPing: () => void,
  onLost: () => void,
  intervalMs = 30000,
  timeoutMs = 10000
): Heartbeat {
  const interval =
    Number.isFinite(intervalMs) && intervalMs >= 1 && intervalMs <= 300000 ? intervalMs : 30000;
  const timeout =
    Number.isFinite(timeoutMs) && timeoutMs >= 1 && timeoutMs <= 30000 ? timeoutMs : 10000;
  let stopped = false;
  let sentAt: number | null = null;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  const timer = setInterval(() => {
    if (stopped || sentAt !== null) return;
    sentAt = performance.now();
    deadline = setTimeout(lost, timeout);
    try {
      sendPing();
    } catch {
      lost();
    }
  }, interval);
  function stop() {
    stopped = true;
    clearInterval(timer);
    clearTimeout(deadline);
    sentAt = null;
  }
  function lost() {
    if (stopped) return;
    stop();
    onLost();
  }
  return {
    stop,
    pong() {
      if (stopped || sentAt === null) return null;
      const latency = Math.max(0, Math.round(performance.now() - sentAt));
      clearTimeout(deadline);
      sentAt = null;
      return latency;
    },
  };
}
