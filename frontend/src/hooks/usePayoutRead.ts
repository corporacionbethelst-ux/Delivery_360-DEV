import { useCallback, useEffect, useRef } from 'react';
import { capturePrivateTask } from '@/lib/private-task';

/** A caller must check this scope before each subsequent request and before publishing. */
export function usePayoutRead() {
  const alive = useRef(false), sequence = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  return useCallback(() => {
    const request = ++sequence.current;
    try {
      const task = capturePrivateTask();
      return () => alive.current && request === sequence.current && task.isCurrent();
    } catch {
      return () => false;
    }
  }, []);
}
