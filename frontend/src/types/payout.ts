import type { Rider } from './user';

/**
 * Estados posibles de un pago/retiro (Payout)
 */
export type PayoutStatus = 'pending' | 'approved' | 'paid' | 'rejected' | 'cancelled';

/**
 * Método de pago para el retiro
 */
export type PayoutMethod = 'bank_transfer' | 'cash' | 'digital_wallet' | 'crypto';

/**
 * Interfaz principal para un Payout (Retiro/Liquidación)
 * ACTUALIZADO: Usa snake_case para coincidir con la respuesta del Backend
 */
export interface Payout {
  id: string;
  rider_id: string;          // ✅ Cambiado de riderId
  
  // Montos
  total_amount: number;      // ✅ Cambiado de totalAmount
  base_earnings?: number;    // ✅ Cambiado de baseEarnings
  tips?: number;             // ✅ Cambiado de tips
  bonuses?: number;          // ✅ Cambiado de bonuses
  deductions?: number;       // ✅ Cambiado de deductions
  net_amount?: number;       // ✅ Cambiado de netAmount
  
  // Período cubierto
  period_start?: string;     // ✅ Cambiado de periodStart
  period_end?: string;       // ✅ Cambiado de periodEnd
  
  // Conteo y detalles
  orders_count: number;      // ✅ Cambiado de ordersCount
  
  // Estado y método
  status: PayoutStatus;
  payment_method?: PayoutMethod; // ✅ Cambiado de paymentMethod
  
  // Información bancaria (si aplica)
  bank_name?: string;        // ✅ Cambiado de bankName
  account_number?: string;   // ✅ Cambiado de accountNumber
  account_type?: 'checking' | 'savings'; // ✅ Cambiado de accountType
  
  // Metadatos
  request_notes?: string;    // ✅ Cambiado de requestNotes
  rejection_reason?: string; // ✅ Cambiado de rejectionReason
  processed_by?: string;     // ✅ Cambiado de processedBy
  processed_at?: string;     // ✅ Cambiado de processedAt
  paid_at?: string;          // ✅ Cambiado de paidAt
  
  // Timestamps (Requeridos por el error)
  created_at: string;        // ✅ Agregado y cambiado de createdAt
  updated_at: string;        // ✅ Agregado y cambiado de updatedAt
}

/**
 * Payout con información ampliada del repartidor
 * Usado en listados y vistas administrativas
 */
export interface PayoutWithRider extends Payout {
  rider?: Rider;             // Objeto completo del repartidor (opcional)
  rider_name?: string;       // Nombre calculado (opcional)
  rider_email?: string;      // Email calculado (opcional)
}

/**
 * Detalle de una orden incluida en un payout
 */
export interface PayoutOrderItem {
  order_id: string;
  order_number: string;
  delivery_date: string;
  base_pay: number;
  tip: number;
  bonus: number;
  deduction: number;
  total: number;
  status: 'completed' | 'cancelled' | 'refunded';
}

/**
 * Desglose detallado de un payout
 */
export interface PayoutDetail extends Payout {
  items: PayoutOrderItem[];
  calculation_breakdown: {
    subtotal: number;
    taxes: number;
    platform_fee: number;
    final_total: number;
  };
}

/**
 * DTO para crear una solicitud de retiro
 */
export interface CreatePayoutRequest {
  rider_id: string;
  amount: number;
  payment_method: PayoutMethod;
  bank_name?: string;
  account_number?: string;
  account_type?: 'checking' | 'savings';
  notes?: string;
}

/**
 * DTO para aprobar/rechazar un payout
 */
export interface UpdatePayoutStatusRequest {
  status: 'approved' | 'rejected' | 'paid' | 'cancelled';
  rejection_reason?: string;
  payment_method?: PayoutMethod;
  processed_notes?: string;
}

/**
 * Filtros disponibles para listar payouts
 */
export interface PayoutFilters {
  status?: PayoutStatus | 'all';
  rider_id?: string;
  start_date?: string;
  end_date?: string;
  payment_method?: PayoutMethod;
  search?: string;
}

/**
 * Resumen estadístico de payouts
 */
export interface PayoutMetrics {
  total_pending: number;
  total_approved: number;
  total_paid: number;
  total_rejected: number;
  total_amount_pending: number;
  total_amount_paid: number;
  average_payout: number;
  count_by_status: Record<PayoutStatus, number>;
}