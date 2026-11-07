'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { capturePrivateTask } from '@/lib/private-task';
import { transactionService, type Transaction } from '@/services/transaction.service';

export function useTransactionDetail(id: string) {
  const [data, setData] = useState<Transaction | null>(null), [isLoading, setIsLoading] = useState(true), [error, setError] = useState<string | null>(null);
  const alive = useRef(false), sequence = useRef(0);
  const load = useCallback(async () => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && ticket === sequence.current && (!task || task.isCurrent());
    setIsLoading(true); setError(null);
    try {
      task = capturePrivateTask();
      const result = await transactionService.getById(id);
      task.assertCurrent(); if (current()) setData(result);
    } catch { if (current()) setError('No se pudo comprobar la transacción solicitada. Se conserva el último registro confirmado, si existe.'); }
    finally { if (current()) setIsLoading(false); }
  }, [id]);
  useEffect(() => { const requestSequence = sequence; alive.current = true; setData(null); void load(); return () => { alive.current = false; requestSequence.current++; }; }, [load]);
  return { data, isLoading, error, refresh: load };
}
