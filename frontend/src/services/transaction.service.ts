import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { normalizeTransaction, normalizeTransactionPage, prepareTransactionQuery, transactionId, TRANSACTION_TYPES, TRANSACTION_RESPONSE_STATUSES } from '@/lib/transaction-contract';

export type TransactionType = typeof TRANSACTION_TYPES[number];
export type TransactionStatus = typeof TRANSACTION_RESPONSE_STATUSES[number];
export interface Transaction {
  id: string; rider_id: string | null; transaction_type: TransactionType; type: TransactionType;
  amount: number; currency: string | null; status: TransactionStatus; description: string | null;
  reference_id: string | null; created_at: string | null; updated_at: string | null; processed_at: string | null;
  balance_before: number | null; balance_after: number | null;
  source_type: string | null; source_id: string | null; idempotency_key: string | null; created_by_user_id: string | null;
}
export interface TransactionFilters {
  type?: TransactionType | 'ALL'; status?: TransactionStatus | 'ALL'; rider_id?: string;
  date_from?: string; date_to?: string; limit?: number; page?: number; offset?: number;
}

export const transactionService = {
  /** A bounded server page; the array carries no global total. */
  getAll: async (params?: Readonly<TransactionFilters>): Promise<Transaction[]> => {
    const task = capturePrivateTask(), captured = prepareTransactionQuery(params);
    const query = new URLSearchParams();
    for (const name of ['type', 'status', 'rider_id', 'date_from', 'date_to'] as const) if (captured[name] !== undefined) query.set(name, captured[name]!);
    query.set('limit', String(captured.limit)); query.set('offset', String(captured.offset));
    try {
      const response = await api.get<unknown>(`/financial/transactions?${query}`);
      task.assertCurrent(); return normalizeTransactionPage(response, captured);
    } catch (error) { task.assertCurrent(); throw error; }
  },
  getById: async (value: string): Promise<Transaction> => {
    const task = capturePrivateTask(), id = transactionId(typeof value === 'string' ? value.trim() : value);
    try {
      const response = await api.get<unknown>(`/financial/transactions/${encodeURIComponent(id)}`);
      task.assertCurrent(); return normalizeTransaction(response, id);
    } catch (error) { task.assertCurrent(); throw error; }
  },
};
