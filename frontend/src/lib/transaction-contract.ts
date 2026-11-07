import { summaryDate } from '@/lib/financial-summary-contract';
import type { Transaction, TransactionFilters } from '@/services/transaction.service';

export const TRANSACTION_TYPES = ['PAGO_ENTREGA', 'PAGO_INTENTO_FALLIDO', 'BONO_RENDIMIENTO', 'PENALIZACION', 'AJUSTE_MANUAL', 'INGRESO', 'RETIRO', 'BONO', 'DESCUENTO', 'AJUSTE', 'DELIVERY_BONUS', 'FAILED_ATTEMPT_BONUS', 'WITHDRAWAL_REQUEST', 'WITHDRAWAL_COMPLETION', 'STRIPE_PAYOUT', 'STRIPE_INSTANT', 'BANK_TRANSFER', 'WALLET_ADJUSTMENT'] as const;
export const TRANSACTION_STATUSES = ['PENDIENTE', 'PROCESADO', 'PAGADO', 'RECHAZADO'] as const;
export const TRANSACTION_RESPONSE_STATUSES = [...TRANSACTION_STATUSES, 'APROBADA', 'PROCESANDO'] as const;
const invalid = (): never => { throw new Error('La transacción está incompleta o no coincide con la consulta'); };
const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
export const transactionId = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim()) return invalid();
  if (/^(?:[a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/i.test(value)) {
    const hex = value.replace(/-/g, '').toLowerCase();
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return value;
};
const text = (value: unknown): string | null => value == null ? null : typeof value === 'string' ? value : invalid();
const date = (value: unknown): string | null => {
  if (value == null) return null;
  try { return summaryDate(value).iso; } catch { return invalid(); }
};
const money = (value: unknown): number => {
  if ((typeof value !== 'number' && typeof value !== 'string') || !/^-?\d+(?:\.\d{1,2})?$/.test(String(value))) throw new Error('Importe financiero inválido');
  const cents = Math.round(Number(value) * 100);
  if (!Number.isSafeInteger(cents)) throw new Error('Importe financiero inválido');
  return cents === 0 ? 0 : cents / 100;
};
const optionalMoney = (value: unknown) => value == null ? null : money(value);

export function normalizeTransaction(value: unknown, expectedId?: string): Transaction {
  const data = object(value), id = transactionId(data.id);
  if (expectedId !== undefined && transactionId(expectedId) !== id) return invalid();
  const primary = data.transaction_type == null ? undefined : transactionId(data.transaction_type);
  const alias = data.type == null ? undefined : transactionId(data.type);
  const type = primary ?? alias;
  if (!type || !TRANSACTION_TYPES.includes(type as never) || primary && alias && primary !== alias || !TRANSACTION_RESPONSE_STATUSES.includes(data.status as never)) return invalid();
  const currency = data.currency == null ? null : typeof data.currency === 'string' && /^[A-Z]{3}$/.test(data.currency) ? data.currency : invalid();
  return {
    id, rider_id: data.rider_id == null ? null : transactionId(data.rider_id),
    transaction_type: type as Transaction['type'], type: type as Transaction['type'], status: data.status as Transaction['status'],
    amount: money(data.amount), currency, description: text(data.description), reference_id: text(data.reference_id),
    created_at: date(data.created_at), updated_at: date(data.updated_at), processed_at: date(data.processed_at),
    balance_before: optionalMoney(data.balance_before), balance_after: optionalMoney(data.balance_after),
    source_type: text(data.source_type), source_id: text(data.source_id), idempotency_key: text(data.idempotency_key),
    created_by_user_id: data.created_by_user_id == null ? null : transactionId(data.created_by_user_id),
  };
}

export interface PreparedTransactionQuery {
  type?: Transaction['type']; status?: typeof TRANSACTION_STATUSES[number]; rider_id?: string;
  date_from?: string; date_to?: string; limit: number; offset: number;
}
export function prepareTransactionQuery(params?: Readonly<TransactionFilters>): PreparedTransactionQuery {
  const input = { ...params };
  if (Object.keys(input).some(key => !['type', 'status', 'rider_id', 'date_from', 'date_to', 'limit', 'page', 'offset'].includes(key))) return invalid();
  if (input.type !== undefined && input.type !== 'ALL' && !TRANSACTION_TYPES.includes(input.type)) return invalid();
  if (input.status !== undefined && input.status !== 'ALL' && !TRANSACTION_STATUSES.includes(input.status as never)) return invalid();
  const query: PreparedTransactionQuery = {
    type: input.type === 'ALL' ? undefined : input.type,
    status: input.status === 'ALL' ? undefined : input.status as PreparedTransactionQuery['status'],
    limit: Number.isFinite(input.limit) ? Math.min(Math.max(Math.trunc(input.limit!), 1), 500) : 100,
    offset: 0,
  };
  if (input.rider_id !== undefined) query.rider_id = transactionId(typeof input.rider_id === 'string' ? input.rider_id.trim() : input.rider_id);
  if (input.page !== undefined && input.offset !== undefined) return invalid();
  if (input.page !== undefined) {
    if (!Number.isSafeInteger(input.page) || input.page < 1) return invalid();
    query.offset = (input.page - 1) * query.limit;
  } else if (input.offset !== undefined) {
    if (!Number.isFinite(input.offset) || input.offset < 0) return invalid();
    query.offset = Math.trunc(input.offset);
  }
  if (!Number.isSafeInteger(query.offset)) return invalid();
  for (const field of ['date_from', 'date_to'] as const) {
    if (input[field] !== undefined) {
      if (typeof input[field] !== 'string' || !input[field]!.trim()) return invalid();
      const raw = input[field]!.trim();
      let parsed: ReturnType<typeof summaryDate>;
      try { parsed = summaryDate(raw); } catch { return invalid(); }
      // This endpoint treats a date-only end as midnight, not end-of-day.
      query[field] = raw.length === 10 ? raw : new Date(parsed.time).toISOString();
    }
  }
  if (query.date_from && query.date_to && summaryDate(query.date_from).time > summaryDate(query.date_to).time) return invalid();
  return query;
}

export function normalizeTransactionPage(value: unknown, query: PreparedTransactionQuery): Transaction[] {
  if (!Array.isArray(value) || value.length > query.limit) return invalid();
  const ids = new Set<string>();
  return value.map(value => {
    const row = normalizeTransaction(value);
    if (ids.has(row.id) || query.type && row.type !== query.type || query.status && row.status !== query.status || query.rider_id && row.rider_id !== query.rider_id) return invalid();
    if (query.date_from || query.date_to) {
      if (!row.created_at || query.date_from && Date.parse(row.created_at) < summaryDate(query.date_from).time || query.date_to && Date.parse(row.created_at) > summaryDate(query.date_to).time) return invalid();
    }
    ids.add(row.id); return row;
  });
}

export const transactionDateLabel = (value: string | null | undefined): string => value ? new Intl.DateTimeFormat('es-VE', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value)) + ' UTC' : 'Fecha no informada';
export function transactionCsv(rows: Transaction[], context: { type: string; status: string; offset: number; search: string }) {
  return rows.map(row => ({
    id: row.id, rider_id: row.rider_id ?? '', fecha_creacion_utc: row.created_at ?? '', fecha_actualizacion_utc: row.updated_at ?? '',
    tipo: row.type, estado: row.status, importe_registrado: row.amount, moneda: row.currency ?? '', descripcion: row.description ?? '',
    referencia: row.reference_id ?? '', saldo_anterior: row.balance_before, saldo_posterior: row.balance_after,
    origen_tipo: row.source_type ?? '', origen_id: row.source_id ?? '',
    filtro_tipo: context.type, filtro_estado: context.status, desplazamiento_consulta: context.offset, busqueda_local: context.search,
    alcance: 'Solo coincidencias de la página cargada; no es el historial completo',
  }));
}
