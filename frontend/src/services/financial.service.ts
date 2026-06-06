import { api } from '@/lib/api';

export interface FinancialSummary {
  period: string;
  period_start?: string;
  period_end?: string;
  total_revenue: number;
  gross_order_value?: number;
  completed_deliveries?: number;
  total_transactions: number;
  total_costs: number;
  net_margin: number;
  total_rider_payouts: number;
  other_costs?: number;
  avg_per_delivery: number;
  cash_payouts_processed?: number;
  rider_earnings_accrued?: number;
  rider_deductions?: number;
}

export interface RiderEarnings {
  rider_id: string;
  rider_name: string;
  total_earned: number;
  completed_deliveries: number;
  pending_payout: number;
  last_payout_date?: string;
}

// Parámetros opcionales para resumen financiero
export interface FinancialSummaryParams {
  period?: 'today' | 'week' | 'month';
  start_date?: string;
  end_date?: string;
}

export const financialService = {
  /**
   * Obtener resumen financiero global o filtrado por fechas.
   * CORREGIDO: Ahora devuelve response.data correctamente.
   */
  getSummary: async (params?: FinancialSummaryParams): Promise<FinancialSummary> => {
    const queryParams = new URLSearchParams();
    
    if (params?.period) queryParams.append('period', params.period);
    if (params?.start_date) queryParams.append('start_date', params.start_date);
    if (params?.end_date) queryParams.append('end_date', params.end_date);

    const query = queryParams.toString() ? `?${queryParams}` : '';
    
    try {
      const response = await api.get<FinancialSummary>(`/financial/summary${query}`);
      return response; // api.get ya retorna T (los datos), no la respuesta de axios completa
    } catch (error) {
      console.error('[FinancialService] Error fetching summary:', error);
      throw error;
    }
  },

  /**
   * Obtener ganancias de repartidores, opcionalmente filtrado por ID.
   * CORREGIDO: Ahora devuelve response.data correctamente.
   */
  getRiderEarnings: async (riderId?: string): Promise<RiderEarnings[]> => {
    try {
      const params = riderId ? `?rider_id=${riderId}` : '';
      const response = await api.get<RiderEarnings[]>(`/financial/riders${params}`);
      return response;
    } catch (error) {
      console.error('[FinancialService] Error fetching rider earnings:', error);
      throw error;
    }
  },

  /**
   * Solicitar retiro de ganancias para el repartidor actual.
   * NUEVO MÉTODO: Esencial para la página de withdraw.
   */
  requestPayout: async (amount: number): Promise<{ message: string; transaction_id: string }> => {
    if (amount <= 0) throw new Error('[FinancialService] El monto debe ser mayor a 0');
    
    try {
      return await api.post('/financial/payouts/request', { amount });
    } catch (error) {
      console.error('[FinancialService] Error requesting payout:', error);
      throw error;
    }
  },

  /**
   * Obtener historial de transacciones/pagos.
   * NUEVO MÉTODO: Útil para la página de historial.
   */
  getTransactions: async (limit: number = 20): Promise<any[]> => {
    try {
      return await api.get(`/financial/transactions?limit=${limit}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching transactions:', error);
      throw error;
    }
  }
};