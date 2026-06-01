import { api } from '@/lib/api';

export type PayoutStatus = 'PENDIENTE' | 'PROCESADO' | 'RECHAZADO' | 'CANCELADO';
export type PayoutMethod = 'TRANSFERENCIA' | 'EFECTIVO' | 'BILLETERA_DIGITAL';

export interface Payout {
  id: string;
  rider_id: string;
  amount: number;
  status: PayoutStatus;
  method: PayoutMethod;
  requested_at: string;
  processed_at?: string | null;
  bank_account_last4?: string | null;
  reference_code?: string | null;
  rejection_reason?: string | null;
}

export interface PayoutRequestInput {
  amount: number;
  method: PayoutMethod;
  bank_account_id?: string;
}

export interface PayoutBalance {
  available: number;
  pending: number;
  currency?: string;
}

export interface PayoutFilters {
  rider_id?: string;
  limit?: number;
  status?: PayoutStatus;
}

export const payoutService = {
  /**
   * Obtener historial de retiros con filtros opcionales.
   * Maneja errores de red y valida parámetros.
   */
  getAll: async (params?: Readonly<PayoutFilters>): Promise<Payout[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.rider_id) queryParams.append('rider_id', params.rider_id);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.status) queryParams.append('status', params.status);

      const query = queryParams.toString() ? `?${queryParams}` : '';
      return await api.get<Payout[]>(`/payouts${query}`);
    } catch (error) {
      console.error('[PayoutService] Error fetching payouts:', error);
      throw error;
    }
  },

  /**
   * Solicitar un nuevo retiro.
   * Valida que el monto sea positivo antes de enviar.
   */
  requestPayout: async (data: PayoutRequestInput): Promise<Payout> => {
    try {
      if (!data.amount || data.amount <= 0) {
        throw new Error('[PayoutService] El monto del retiro debe ser mayor a cero');
      }
      if (!data.method) {
        throw new Error('[PayoutService] Método de pago requerido');
      }

      return await api.post<Payout>('/payouts/request', data);
    } catch (error) {
      console.error('[PayoutService] Error requesting payout:', error);
      throw error;
    }
  },

  /**
   * Obtener saldo disponible para retiro.
   * Valida que el ID del repartidor exista.
   */
  getAvailableBalance: async (riderId: string): Promise<PayoutBalance> => {
    if (!riderId) {
      throw new Error('[PayoutService] ID de repartidor requerido para consultar saldo');
    }

    try {
      return await api.get<PayoutBalance>(`/payouts/balance?rider_id=${riderId}`);
    } catch (error) {
      console.error(`[PayoutService] Error fetching balance for rider ${riderId}:`, error);
      throw error;
    }
  },

  /**
   * Aprobar un pago pendiente (Solo admin).
   */
  approve: async (id: string): Promise<Payout> => {
    if (!id) {
      throw new Error('[PayoutService] ID de pago requerido para aprobar');
    }

    try {
      return await api.patch<Payout>(`/payouts/${id}/approve`);
    } catch (error) {
      console.error(`[PayoutService] Error approving payout ${id}:`, error);
      throw error;
    }
  },

  /**
   * Rechazar un pago con motivo (Solo admin).
   */
  reject: async (id: string, reason: string): Promise<Payout> => {
    if (!id) {
      throw new Error('[PayoutService] ID de pago requerido para rechazar');
    }
    if (!reason || reason.trim().length === 0) {
      throw new Error('[PayoutService] Motivo de rechazo requerido');
    }

    try {
      return await api.patch<Payout>(`/payouts/${id}/reject`, { rejection_reason: reason });
    } catch (error) {
      console.error(`[PayoutService] Error rejecting payout ${id}:`, error);
      throw error;
    }
  },

  getById: async (id: string): Promise<Payout> => {
    if (!id) throw new Error('[PayoutService] ID de pago requerido');
    try {
      return await api.get<Payout>(`/payouts/${id}`);
    } catch (error) {
      console.error(`[PayoutService] Error fetching payout ${id}:`, error);
      throw error;
    }
  },
};