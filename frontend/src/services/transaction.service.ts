import { api } from '@/lib/api';

/**
 * Tipos de transacción actualizados para coincidir con el Backend (Seed Data y Modelos).
 * Se han agregado los tipos faltantes que causaban el error.
 */
export type TransactionType = 
  | 'PAGO_ENTREGA'           // Pago por entrega completada
  | 'PAGO_INTENTO_FALLIDO'   // Pago por intento fallido bonificable
  | 'BONO'                   // Genérico (legacy)
  | 'BONO_RENDIMIENTO'       // Bono por productividad/metras
  | 'DESCUENTO'              // Genérico (legacy)
  | 'PENALIZACION'           // Descuento por incidencia negativa
  | 'AJUSTE'                 // Genérico (legacy)
  | 'AJUSTE_MANUAL'          // Ajuste administrativo manual
  | 'RETIRO'                 // Retiro de fondos
  | 'INGRESO';               // Depósito de fondos

export type TransactionStatus = 
  | 'PENDIENTE' 
  | 'PROCESADO' 
  | 'PAGADO' 
  | 'RECHAZADO'
  | 'APROBADA'      // Alias para compatibilidad
  | 'PROCESANDO';   // Alias para compatibilidad

type ApiTransaction = {
  id: string;
  rider_id?: string | null;
  amount: number;
  transaction_type?: TransactionType;
  type?: TransactionType;
  description?: string | null;
  reference_id?: string | null;
  status: TransactionStatus;
  created_at: string;
  updated_at?: string | null;
  processed_at?: string | null;
  balance_after?: number | null;
};

export interface Transaction {
  id: string;
  rider_id?: string | null;
  user_id?: string | null; // Alias visual legado
  transaction_type: TransactionType;
  type: TransactionType; // Alias compatible
  amount: number;
  currency: string;
  status: TransactionStatus;
  description: string;
  reference_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  processed_at?: string | null;
  balance_after?: number | null;
  metadata?: Record<string, unknown>;
}

export interface TransactionFilters {
  type?: TransactionType | 'ALL';
  status?: TransactionStatus | 'ALL';
  rider_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  page?: number;
  offset?: number;
}

/**
 * Set actualizado con TODOS los tipos válidos soportados por el backend.
 * Esto evita que el filtro rechace transacciones legítimas como 'BONO_RENDIMIENTO'.
 */
const VALID_TYPES = new Set<TransactionType>([
  'PAGO_ENTREGA',
  'PAGO_INTENTO_FALLIDO',
  'BONO',
  'BONO_RENDIMIENTO',
  'DESCUENTO',
  'PENALIZACION',
  'AJUSTE',
  'AJUSTE_MANUAL',
  'RETIRO',
  'INGRESO'
]);

const VALID_STATUSES = new Set<TransactionStatus>([
  'PENDIENTE',
  'PROCESADO',
  'PAGADO',
  'RECHAZADO',
  'APROBADA',
  'PROCESANDO'
]);

const clampLimit = (limit?: number): number | undefined => {
  if (!Number.isFinite(limit)) return undefined;
  return Math.min(Math.max(Math.trunc(limit as number), 1), 500);
};

const normalizeTransaction = (transaction: ApiTransaction): Transaction => {
  // Priorizar transaction_type, fallback a type
  const transactionType = transaction.transaction_type || transaction.type;

  // Validación suave: Si el tipo no está en la lista blanca, lo aceptamos pero lanzamos warning.
  // Esto evita que la UI se rompa si el backend agrega un nuevo tipo en el futuro.
  if (!transactionType || !VALID_TYPES.has(transactionType)) {
    console.warn(`[TransactionService] Tipo de transacción desconocido recibido: ${transactionType}. Se procesará como válido.`);
    // No lanzamos error, asumimos que es un tipo válido no listado explícitamente aún
  }

  // Normalización de estado si viene en formato ligeramente distinto
  let normalizedStatus = transaction.status;
  if (!VALID_STATUSES.has(normalizedStatus)) {
     console.warn(`[TransactionService] Estado desconocido: ${normalizedStatus}. Se mantiene tal cual.`);
  }

  return {
    id: transaction.id,
    rider_id: transaction.rider_id ?? null,
    user_id: transaction.rider_id ?? null,
    transaction_type: transactionType as TransactionType,
    type: transactionType as TransactionType,
    amount: Number(transaction.amount || 0),
    currency: 'COP',
    status: normalizedStatus,
    description: transaction.description || 'Sin descripción',
    reference_id: transaction.reference_id ?? null,
    created_at: transaction.created_at,
    updated_at: transaction.updated_at ?? null,
    processed_at: transaction.processed_at ?? null,
    balance_after: transaction.balance_after ?? null,
    metadata: {},
  };
};

const buildTransactionQuery = (params?: Readonly<TransactionFilters>): string => {
  const queryParams = new URLSearchParams();

  // Solo filtrar si el tipo es válido y no es 'ALL'
  if (params?.type && params.type !== 'ALL' && VALID_TYPES.has(params.type)) {
    queryParams.append('type', params.type);
  }

  if (params?.status && params.status !== 'ALL' && VALID_STATUSES.has(params.status)) {
    queryParams.append('status', params.status);
  }

  if (params?.rider_id?.trim()) queryParams.append('rider_id', params.rider_id.trim());
  if (params?.date_from?.trim()) queryParams.append('date_from', params.date_from.trim());
  if (params?.date_to?.trim()) queryParams.append('date_to', params.date_to.trim());

  const limit = clampLimit(params?.limit);
  if (limit) queryParams.append('limit', String(limit));

  const offset = params?.offset ?? (params?.page && params.page > 1 && limit ? (params.page - 1) * limit : undefined);
  if (Number.isFinite(offset) && Number(offset) >= 0) queryParams.append('offset', String(Math.trunc(Number(offset))));

  const query = queryParams.toString();
  return query ? `?${query}` : '';
};

export const transactionService = {
  /**
   * Listar transacciones financieras reales desde /financial/transactions.
   */
  getAll: async (params?: Readonly<TransactionFilters>): Promise<Transaction[]> => {
    try {
      const response = await api.get<ApiTransaction[]>(`/financial/transactions${buildTransactionQuery(params)}`);
      
      // Mapeo seguro con normalización
      return response.map(normalizeTransaction);
    } catch (error) {
      console.error('[TransactionService] Error fetching transactions:', error);
      throw error;
    }
  },

  /**
   * Obtener detalle real de una transacción financiera.
   */
  getById: async (id: string): Promise<Transaction> => {
    const transactionId = id?.trim();
    if (!transactionId) throw new Error('[TransactionService] ID de transacción requerido');

    try {
      const response = await api.get<ApiTransaction>(`/financial/transactions/${transactionId}`);
      return normalizeTransaction(response);
    } catch (error) {
      console.error(`[TransactionService] Error fetching transaction ${transactionId}:`, error);
      throw error;
    }
  }
};