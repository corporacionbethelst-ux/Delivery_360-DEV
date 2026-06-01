import { api } from '@/lib/api';

export type TransactionType = 'INGRESO' | 'PAGO_RIDER' | 'REEMBOLSO' | 'AJUSTE';
export type TransactionStatus = 'COMPLETADA' | 'PENDIENTE' | 'FALLIDA';

export interface Transaction {
  id: string;
  type: TransactionType;
  amount: number;
  currency: string;
  status: TransactionStatus;
  description: string;
  reference_id?: string | null; // ID de orden o payout asociado
  user_id?: string | null; // Quién la generó
  created_at: string;
  processed_at?: string | null;
  metadata?: Record<string, any>;
}

export interface TransactionFilters {
  type?: TransactionType;
  status?: TransactionStatus;
  date_from?: string;
  date_to?: string;
  limit?: number;
  page?: number;
}

export const transactionService = {
  /**
   * Listar transacciones con filtros.
   */
  getAll: async (params?: Readonly<TransactionFilters>): Promise<Transaction[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.type) queryParams.append('type', params.type);
      if (params?.status) queryParams.append('status', params.status);
      if (params?.date_from) queryParams.append('date_from', params.date_from);
      if (params?.date_to) queryParams.append('date_to', params.date_to);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.page) queryParams.append('page', String(params.page));

      const query = queryParams.toString() ? `?${queryParams}` : '';
      return await api.get<Transaction[]>(`/transactions${query}`);
    } catch (error) {
      console.error('[TransactionService] Error fetching transactions:', error);
      throw error;
    }
  },

  /**
   * Obtener detalle de una transacción.
   */
  getById: async (id: string): Promise<Transaction> => {
    if (!id) throw new Error('[TransactionService] ID de transacción requerido');
    try {
      return await api.get<Transaction>(`/transactions/${id}`);
    } catch (error) {
      console.error(`[TransactionService] Error fetching transaction ${id}:`, error);
      throw error;
    }
  }
};