import { capturePrivateTask } from '@/lib/private-task';
import { normalizePayout, normalizePayoutBalance, normalizePayoutHistory, payoutCents, payoutId, payoutKey, payoutMethod } from '@/lib/payout-contract';
import { api } from '@/lib/api';

// Six canonical backend states plus two values kept for historical responses.
export type PayoutStatus = 'PENDIENTE' | 'APROBADO' | 'EN_PROCESO' | 'COMPLETADO' | 'RECHAZADO' | 'FALLIDO' | 'PROCESADO' | 'CANCELADO';
export type PayoutMethod = 'TRANSFERENCIA' | 'EFECTIVO' | 'BILLETERA_DIGITAL';

export interface Payout {
  id: string;
  rider_id: string;
  amount: number;
  total_amount: number;
  status: PayoutStatus;
  method: PayoutMethod;
  payment_method?: PayoutMethod;
  requested_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  processed_at?: string | null;
  bank_account_last4?: string | null;
  reference_code?: string | null;
  rejection_reason?: string | null;
  balance_before?: number | null;
  balance_after?: number | null;
  requested_by_user_id?: string | null;
  processed_by_user_id?: string | null;
  idempotency_key?: string | null;
  orders_count?: number;
  period?: string | null;
  period_start?: string | null;
  period_end?: string | null;
}

export interface PayoutRequestInput {
  amount: number;
  method: PayoutMethod;
  bank_account_last4?: string;
  bank_account_id?: string;
  idempotency_key: string;
}

export interface PayoutStatusHistory {
  id: string;
  payout_id: string;
  old_status?: PayoutStatus | null;
  new_status: PayoutStatus;
  reason?: string | null;
  changed_by_user_id?: string | null;
  balance_before?: number | null;
  balance_after?: number | null;
  created_at?: string | null;
}

export interface PayoutBalance {
  available: number;
  pending: number;
  processed?: number;
  total_earned?: number;
  currency?: string;
}

export interface PayoutFilters {
  rider_id?: string;
  limit?: number;
  offset?: number;
  status?: PayoutStatus | 'ALL' | 'all';
}

export interface PayoutPageFilters extends Omit<PayoutFilters, 'offset'> { cursor?: string | null }
export interface PayoutPage { items: Payout[]; next_cursor: string | null }
const pageLimit = (limit?: number) => Number.isFinite(limit) ? Math.min(Math.max(Math.trunc(limit!), 1), 200) : 50;
const validCursor = (value: unknown): value is string => typeof value === 'string' && value.length <= 2048 && /^[A-Za-z0-9_-]+\.[0-9a-f]{64}$/.test(value);
function normalizeList(response: unknown, query?: Readonly<PayoutFilters>): Payout[] {
  if (!Array.isArray(response)) throw new Error('Historial de retiros mal formado');
  if (response.length > pageLimit(query?.limit)) throw new Error('La respuesta excedió la página de retiros solicitada');
  const ids = new Set<string>();
  return response.map(value => {
    const p = normalizePayout(value);
    if (ids.has(p.id) || query?.rider_id?.trim() && p.rider_id !== query.rider_id.trim() ||
        query?.status && !['ALL', 'all'].includes(query.status) && p.status !== query.status) {
      throw new Error('El historial contiene identidades duplicadas o datos fuera del filtro');
    }
    ids.add(p.id);
    return p;
  });
}

async function privateRequest<T>(request: () => Promise<T>): Promise<T> {
  const task = capturePrivateTask();
  try {
    const response = await request();
    task.assertCurrent();
    return response;
  } catch (error) {
    task.assertCurrent();
    throw error;
  }
}

const buildQuery = (params?: Readonly<PayoutFilters>): string => {
  const queryParams = new URLSearchParams();

  if (params?.status && !['ALL', 'all', 'PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO'].includes(params.status)) throw new Error('El servidor no admite ese filtro de estado');
  if (params?.rider_id?.trim()) queryParams.append('rider_id', params.rider_id.trim());
  if (params?.status && params.status !== 'ALL' && params.status !== 'all') queryParams.append('status', params.status);

  if (Number.isFinite(params?.limit)) {
    queryParams.append('limit', String(Math.min(Math.max(Math.trunc(params?.limit as number), 1), 200)));
  }

  if (Number.isFinite(params?.offset) && Number(params?.offset) >= 0) {
    queryParams.append('offset', String(Math.trunc(Number(params?.offset))));
  }

  const query = queryParams.toString();
  return query ? `?${query}` : '';
};

export const createPayoutIdempotencyKey = (): string => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `payout-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export const payoutHttpStatus = (error: unknown): number | undefined => {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = error.response;
    if (typeof response === 'object' && response !== null && 'status' in response && typeof response.status === 'number') {
      return response.status;
    }
  }
  return undefined;
};

export const payoutService = {
  /** 404 is only a point-in-time absence, never permission to discard the retry key. */
  findRequestByKey: async (key: string): Promise<Payout | null> => {
    payoutKey(key);
    return privateRequest(async () => {
      try {
        const p = normalizePayout(await api.get<unknown>(`/payouts/request-status?idempotency_key=${encodeURIComponent(key)}`));
        if (p.idempotency_key !== key) throw new Error('La respuesta identifica otra solicitud de retiro');
        return p;
      } catch (error) {
        if (payoutHttpStatus(error) === 404) return null;
        throw error;
      }
    });
  },

  /** One explicit server page, without claiming a total or a complete catalog. */
  getAll: async (params?: Readonly<PayoutFilters>): Promise<Payout[]> => {
    const query = params ? { ...params } : undefined;
    return privateRequest(async () => {
      const response = await api.get<unknown>(`/payouts${buildQuery(query)}`);
      return normalizeList(response, query);
    });
  },

  /** Opaque continuation from the server. Never fall back to offset after a failed cursor. */
  getPage: async (params?: Readonly<PayoutPageFilters>): Promise<PayoutPage> => {
    const query = { ...params, limit: pageLimit(params?.limit) };
    if ('offset' in query) throw new Error('La continuación de retiros no admite offset');
    if (query.cursor != null && !validCursor(query.cursor)) throw new Error('Continuación de retiros inválida');
    return privateRequest(async () => {
      const base = buildQuery(query);
      const response = await api.get<unknown>(`/payouts/page${base}${query.cursor ? `&cursor=${encodeURIComponent(query.cursor)}` : ''}`);
      if (!response || typeof response !== 'object' || Array.isArray(response)) throw new Error('Página de retiros mal formada');
      const page = response as Record<string, unknown>;
      const items = normalizeList(page.items, query);
      if (page.next_cursor !== null && (!validCursor(page.next_cursor) || page.next_cursor === query.cursor || items.length !== query.limit)) throw new Error('Continuación de retiros contradictoria');
      return { items, next_cursor: page.next_cursor as string | null };
    });
  },

  /** Callers must retain this key before sending so ambiguous retries cannot create a new request. */
  requestPayout: async (data: PayoutRequestInput): Promise<Payout> => {
    const cents = payoutCents(data.amount), method = payoutMethod(data.method), key = payoutKey(data.idempotency_key);
    if (cents > 9999999999) throw new Error('El retiro excede el máximo admitido');
    if (cents < 1000) throw new Error('El retiro mínimo es 10.00');
    if (data.bank_account_last4 !== undefined && !/^[0-9]{4}$/.test(data.bank_account_last4)) throw new Error('Los últimos cuatro dígitos son inválidos');
    if (data.bank_account_id !== undefined) throw new Error('La API actual no admite bank_account_id');
    return privateRequest(async () => {
      const p = normalizePayout(await api.post<unknown>('/payouts/request', { ...data }));
      if (p.idempotency_key !== key || payoutCents(p.amount) !== cents || p.method !== method ||
          (p.bank_account_last4 ?? undefined) !== data.bank_account_last4) throw new Error('El servidor no confirmó la misma solicitud de retiro');
      return p;
    });
  },

  getAvailableBalance: async (riderId?: string): Promise<PayoutBalance> => privateRequest(async () => {
    const query = riderId?.trim() ? `?rider_id=${encodeURIComponent(riderId.trim())}` : '';
    return normalizePayoutBalance(await api.get<unknown>(`/payouts/balance${query}`));
  }),

  approve: async (id: string): Promise<Payout> => {
    const requestedId = payoutId(id?.trim());
    return privateRequest(async () => {
      const p = normalizePayout(await api.patch<unknown>(`/payouts/${encodeURIComponent(requestedId)}/approve`), requestedId);
      if (p.status !== 'EN_PROCESO') throw new Error('El servidor no confirmó la aprobación del retiro');
      return p;
    });
  },

  reject: async (id: string, reason: string): Promise<Payout> => {
    const requestedId = payoutId(id?.trim()), rejectionReason = reason?.trim();
    if (!rejectionReason || rejectionReason.length > 500) throw new Error('Indica un motivo de rechazo de hasta 500 caracteres');
    return privateRequest(async () => {
      const p = normalizePayout(await api.patch<unknown>(`/payouts/${encodeURIComponent(requestedId)}/reject`, { rejection_reason: rejectionReason }), requestedId);
      if (p.status !== 'RECHAZADO' || p.rejection_reason !== rejectionReason) throw new Error('El servidor no confirmó el rechazo del retiro');
      return p;
    });
  },

  getHistory: async (id: string): Promise<PayoutStatusHistory[]> => {
    const requestedId = payoutId(id?.trim());
    return privateRequest(async () => normalizePayoutHistory(await api.get<unknown>(`/payouts/${encodeURIComponent(requestedId)}/history`), requestedId));
  },

  getById: async (id: string): Promise<Payout> => {
    const requestedId = payoutId(id?.trim());
    return privateRequest(async () => normalizePayout(await api.get<unknown>(`/payouts/${encodeURIComponent(requestedId)}`), requestedId));
  },
};
