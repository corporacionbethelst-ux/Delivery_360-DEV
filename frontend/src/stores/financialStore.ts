import { capturePrivateTask, resetOnSessionChange } from '@/lib/private-task';
// Financial Store - Zustand para gestión financiera
import { create } from 'zustand';
import type { Transaction, FinancialReportDetailed, FinancialFilters } from '@/types/financial';
import { api } from '@/lib/api'; // ✅ IMPORTANTE: Usar el export named 'api' de api.ts
import { financialService, type FinancialPeriod } from '@/services/financial.service';
import { FINANCIAL_PERIODS } from '@/lib/financial-summary-contract';

// Resumen simplificado para el dashboard
export interface FinancialSummary {
  totalRevenue: number;
  totalCosts: number;
  netProfit: number;
  riderPayments: number;
  netCommission: number | null;
  pendingPayouts: number | null;
  activeDeliveries: number | null;
  pendingPayments: number | null;
  period: FinancialPeriod;
}

export interface PaymentRule {
  id: string;
  name: string;
  baseRate: number;
  perKmRate: number;
  priorityMultiplier: number;
}

interface FinancialState {
  // Estado
  summary: FinancialSummary | null;
  report: FinancialReportDetailed | null;
  transactions: Transaction[];
  rules: PaymentRule[];
  
  // Estados de carga
  isLoading: boolean;
  loading: boolean;
  error: string | null;
  
  // Acciones Principales
  fetchSummary: () => Promise<void>;
  getFinancialReport: (filters?: Partial<FinancialFilters>) => Promise<FinancialReportDetailed | null>;
  getTransactions: (filters?: Partial<FinancialFilters>) => Promise<Transaction[]>;
  
  // ALIAS: Función requerida por ManagerFinancialPage
  getDailySummary: (period: string) => Promise<FinancialSummary | null>;
  
  // Gestión de Reglas
  fetchPaymentRules: () => Promise<void>;
  updatePaymentRule: (id: string, data: Partial<PaymentRule>) => Promise<void>;
}

let summarySequence = 0;
export const useFinancialStore = create<FinancialState>((set, get) => ({
  summary: null,
  report: null,
  transactions: [],
  rules: [],
  isLoading: false,
  loading: false,
  error: null,

  // Fetch resumen general
  fetchSummary: async () => {
    await get().getDailySummary('today');
  },

  // Obtener reporte detallado
  getFinancialReport: async (filters?: Partial<FinancialFilters>) => {
    const task = capturePrivateTask();
    set({ loading: true, error: null });
    try {
      const params = new URLSearchParams();
      if (filters?.dateFrom) params.append('dateFrom', filters.dateFrom.toISOString());
      if (filters?.dateTo) params.append('dateTo', filters.dateTo.toISOString());
      if (filters?.statuses) params.append('statuses', filters.statuses.join(','));
      
      const queryString = params.toString() ? `?${params}` : '';
      
      // ✅ CORRECCIÓN: Sin .data, asignación directa
      const data = await api.get<FinancialReportDetailed>(`/financial/report${queryString}`);
      task.assertCurrent();
      
      set({ report: data, loading: false });
      return data;
    } catch (error: any) {
      task.assertCurrent();
      console.error('[FinancialStore] Error fetching report:', error);
      set({ error: error.message || 'Error al obtener reporte financiero', loading: false });
      return null;
    }
  },

  // Both summary entry points use the same real HTTP contract and read sequence.
  getDailySummary: async (period: string) => {
    const task = capturePrivateTask();
    const ticket = ++summarySequence;
    set({ isLoading: true, error: null });
    try {
      if (!FINANCIAL_PERIODS.includes(period as FinancialPeriod)) throw new Error('Período financiero inválido');
      const data = await financialService.getSummary({ period: period as FinancialPeriod });
      task.assertCurrent();
      if (ticket !== summarySequence) return null;
      const summary: FinancialSummary = {
        period: period as FinancialPeriod,
        totalRevenue: data.total_revenue, totalCosts: data.total_costs,
        netProfit: data.net_margin, riderPayments: data.total_rider_payouts,
        netCommission: null, pendingPayouts: null, activeDeliveries: null, pendingPayments: null,
      };
      set({ summary, isLoading: false });
      return summary;
    } catch (error) {
      task.assertCurrent();
      if (ticket === summarySequence) set({ error: 'No se pudo comprobar el resumen financiero. Se conservan los últimos datos disponibles.', isLoading: false });
      return null;
    }
  },

  // Obtener transacciones
  getTransactions: async (filters?: Partial<FinancialFilters>) => {
    const task = capturePrivateTask();
    set({ loading: true, error: null });
    try {
      const params = new URLSearchParams();
      if (filters?.dateFrom) params.append('dateFrom', filters.dateFrom.toISOString());
      if (filters?.dateTo) params.append('dateTo', filters.dateTo.toISOString());
      if (filters?.statuses) params.append('statuses', filters.statuses.join(','));

      const queryString = params.toString() ? `?${params}` : '';
      
      // ✅ CORRECCIÓN: Sin .data
      const data = await api.get<Transaction[]>(`/financial/transactions${queryString}`);
      task.assertCurrent();
      
      set({ transactions: data, loading: false });
      return data;
    } catch (error: any) {
      task.assertCurrent();
      console.error('[FinancialStore] Error fetching transactions:', error);
      set({ error: error.message || 'Error al obtener transacciones', loading: false });
      return [];
    }
  },

  fetchPaymentRules: async () => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      // ✅ CORRECCIÓN: Sin .data
      const data = await api.get<PaymentRule[]>('/financial/rules');
      task.assertCurrent();
      set({ rules: data, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      console.error('[FinancialStore] Error fetching rules:', error);
      set({ error: error.message || 'Error al obtener reglas de pago', isLoading: false });
    }
  },

  updatePaymentRule: async (id: string, data: Partial<PaymentRule>) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      await api.put(`/financial/rules/${id}`, data);
      task.assertCurrent();
      // Recargar reglas después de actualizar
      const updatedData = await api.get<PaymentRule[]>('/financial/rules');
      task.assertCurrent();
      set({ rules: updatedData, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      console.error('[FinancialStore] Error updating rule:', error);
      set({ error: error.message || 'Error al actualizar regla', isLoading: false });
      throw error;
    }
  },
}));

export default useFinancialStore;
resetOnSessionChange(useFinancialStore);
