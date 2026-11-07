import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { normalizeFinancialSummary, prepareSummaryQuery } from '@/lib/financial-summary-contract';

export type FinancialPeriod = 'today' | 'week' | 'month';

export interface FinancialSummary {
  period: FinancialPeriod | 'custom';
  period_start?: string | null;
  period_end?: string | null;
  currency?: string | null;
  total_revenue: number;
  gross_order_value?: number | null;
  completed_deliveries?: number | null;
  total_transactions: number;
  total_costs: number;
  net_margin: number;
  total_rider_payouts: number;
  other_costs?: number | null;
  avg_per_delivery: number;
  cash_payouts_processed?: number | null;
  rider_earnings_accrued?: number | null;
  rider_deductions?: number | null;
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
  period?: FinancialPeriod;
  start_date?: string;
  end_date?: string;
}


export interface FinancialTransaction {
  id: string;
  rider_id: string;
  amount: number;
  balance_before?: number | null;
  balance_after?: number | null;
  transaction_type: string;
  type: string;
  description: string;
  reference_id?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  idempotency_key?: string | null;
  created_by_user_id?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RiderEarningsBreakdown {
  rider_id: string;
  items: FinancialTransaction[];
}

export interface FinancialReconciliation {
  period_start?: string | null;
  period_end?: string | null;
  gross_order_value: number;
  delivery_revenue: number;
  completed_orders: number;
  ledger_transactions: number;
  rider_earnings: number;
  rider_deductions: number;
  adjustments: number;
  net_rider_liability: number;
  pending_payouts: number;
  processed_payouts: number;
  rejected_payouts: number;
  available_liability: number;
  total_costs: number;
  net_margin_after_rider_costs: number;
  payout_count: number;
  currency?: string;
}

export interface FinancialOrderReportRow {
  id: string;
  external_id?: string | null;
  created_at?: string | null;
  ordered_at?: string | null;
  delivered_at?: string | null;
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_email?: string | null;
  pickup_address?: string | null;
  delivery_address?: string | null;
  status: string;
  priority?: string | null;
  subtotal: number;
  delivery_fee: number;
  total: number;
  payment_method?: string | null;
  payment_status?: string | null;
  rider_id?: string | null;
}

export interface FinancialOrdersReport {
  period_start?: string | null;
  period_end?: string | null;
  total_revenue: number;
  gross_order_value: number;
  total_orders: number;
  completed_orders: number;
  active_customers: number;
  status_counts: Record<string, number>;
  rows: FinancialOrderReportRow[];
}

export interface FinancialReportParams {
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface RiderEarningsBreakdownParams extends FinancialReportParams {
  type?: string;
}

const boundedLimit = (value: number | undefined, maximum: number, fallback: number): number =>
  Number.isFinite(value) ? Math.min(Math.max(Math.trunc(value as number), 1), maximum) : fallback;

export const financialService = {
  /** Validate the actual summary contract within the session and query that requested it. */
  getSummary: async (params?: Readonly<FinancialSummaryParams>): Promise<FinancialSummary> => {
    const task = capturePrivateTask();
    const queryParamsSnapshot = prepareSummaryQuery(params);
    const queryParams = new URLSearchParams();
    
    if (queryParamsSnapshot.period) queryParams.append('period', queryParamsSnapshot.period);
    if (queryParamsSnapshot.start_date) queryParams.append('start_date', queryParamsSnapshot.start_date);
    if (queryParamsSnapshot.end_date) queryParams.append('end_date', queryParamsSnapshot.end_date);

    const query = queryParams.toString() ? `?${queryParams}` : '';
    
    try {
      const response = await api.get<unknown>(`/financial/summary${query}`);
      task.assertCurrent();
      return normalizeFinancialSummary(response, queryParamsSnapshot);
    } catch (error) {
      task.assertCurrent();
      throw error;
    }
  },

  /**
   * Obtener ganancias reales del repartidor autenticado.
   */
  getMyEarnings: async (): Promise<RiderEarnings> => {
    try {
      return await api.get<RiderEarnings>('/financial/riders/me');
    } catch (error) {
      console.error('[FinancialService] Error fetching current rider earnings:', error);
      throw error;
    }
  },

  /**
   * Obtener ganancias de repartidores, opcionalmente filtrado por ID.
   * Este método queda para pantallas administrativas; el flujo rider usa getMyEarnings().
   */
  getRiderEarnings: async (riderId?: string): Promise<RiderEarnings[]> => {
    try {
      const params = riderId ? `?rider_id=${encodeURIComponent(riderId)}` : '';
      return await api.get<RiderEarnings[]>(`/financial/riders${params}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching rider earnings:', error);
      throw error;
    }
  },



  /**
   * Desglose auditable de ganancias/retiros del rider autenticado.
   */
  getMyEarningsBreakdown: async (params?: RiderEarningsBreakdownParams): Promise<RiderEarningsBreakdown> => {
    const queryParams = new URLSearchParams();
    if (params?.type) queryParams.append('type', params.type);
    if (params?.date_from) queryParams.append('date_from', params.date_from);
    if (params?.date_to) queryParams.append('date_to', params.date_to);
    if (params?.limit !== undefined) queryParams.append('limit', String(boundedLimit(params.limit, 500, 100)));
    if (Number.isFinite(params?.offset) && Number(params?.offset) >= 0) {
      queryParams.append('offset', String(Math.trunc(Number(params?.offset))));
    }

    const query = queryParams.toString() ? `?${queryParams}` : '';

    try {
      return await api.get<RiderEarningsBreakdown>(`/financial/riders/me/earnings${query}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching rider earnings breakdown:', error);
      throw error;
    }
  },


  /**
   * Obtener reporte real de órdenes para estadísticas y exportación CSV.
   */
  getOrdersReport: async (params?: FinancialReportParams): Promise<FinancialOrdersReport> => {
    const queryParams = new URLSearchParams();

    if (params?.date_from) queryParams.append('date_from', params.date_from);
    if (params?.date_to) queryParams.append('date_to', params.date_to);
    if (params?.limit !== undefined) queryParams.append('limit', String(boundedLimit(params.limit, 5000, 1000)));
    if (Number.isFinite(params?.offset) && Number(params?.offset) >= 0) {
      queryParams.append('offset', String(Math.trunc(Number(params?.offset))));
    }

    const query = queryParams.toString() ? `?${queryParams}` : '';

    try {
      return await api.get<FinancialOrdersReport>(`/financial/reports/orders${query}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching orders report:', error);
      throw error;
    }
  },

  /**
   * Obtener conciliación financiera real para gerencia.
   */
  getReconciliation: async (params?: FinancialReportParams): Promise<FinancialReconciliation> => {
    const queryParams = new URLSearchParams();
    if (params?.date_from) queryParams.append('date_from', params.date_from);
    if (params?.date_to) queryParams.append('date_to', params.date_to);

    const query = queryParams.toString() ? `?${queryParams}` : '';

    try {
      return await api.get<FinancialReconciliation>(`/financial/reconciliation${query}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching reconciliation:', error);
      throw error;
    }
  },


  /**
   * Obtener historial de transacciones/pagos.
   * NUEVO MÉTODO: Útil para la página de historial.
   */
  getTransactions: async (limit: number = 20): Promise<FinancialTransaction[]> => {
    try {
      return await api.get(`/financial/transactions?limit=${boundedLimit(limit, 500, 20)}`);
    } catch (error) {
      console.error('[FinancialService] Error fetching transactions:', error);
      throw error;
    }
  }
};
