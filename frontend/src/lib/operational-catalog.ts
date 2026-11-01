import { DeliveryStatus } from '@/types/delivery';
import { api } from '@/lib/api';
import type { Order as HttpOrder, OrderListParams } from '@/services/order.service';
import type { Rider } from '@/types/user';

export const ORDER_STATUSES = ['PENDIENTE', 'ASIGNADO', 'EN_RECOLECCION', 'RECOLECTADO', 'EN_RUTA', 'ENTREGADO', 'FALLIDO', 'CANCELADO'] as const;
export const CATALOG_PAGE_SIZE = 200;
export const CATALOG_MAX_PAGES = 10;
export const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Respuesta operativa mal formada');
  return value as Record<string, unknown>;
};
export const text = (value: unknown): string | undefined => typeof value === 'string' ? value : undefined;
export const numeric = (value: unknown): number | undefined => {
  if (typeof value !== 'number' && !(typeof value === 'string' && value.trim())) return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
};
export const identifier = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Identidad operativa ausente');
  return value;
};

/** IDs of the order, rider and linked delivery must describe the same assignment. */
export function validateHttpOrder(value: unknown, expectedId?: string): HttpOrder {
  const o = record(value);
  const id = identifier(o.id);
  if (expectedId !== undefined && id !== expectedId) throw new Error('La respuesta pertenece a otro pedido');
  if (!ORDER_STATUSES.includes(o.status as never)) throw new Error('Estado de pedido desconocido');
  const riderIds = [o.assigned_rider_id, o.rider_id];
  if (o.assigned_rider != null) riderIds.push(identifier(record(o.assigned_rider).id));
  if (o.rider != null) riderIds.push(identifier(record(o.rider).id));
  if (o.delivery != null) {
    const d = record(o.delivery);
    identifier(d.id);
    if (!Object.values(DeliveryStatus).includes(d.status as DeliveryStatus)) throw new Error('Estado de entrega desconocido');
    if (d.order_id !== id) throw new Error('La entrega pertenece a otro pedido');
    riderIds.push(d.rider_id);
  }
  const defined = riderIds.filter(v => v !== undefined);
  if (defined.some(v => v !== null && (typeof v !== 'string' || !v.trim())) ||
      new Set(defined).size > 1) throw new Error('Identidades de asignación contradictorias');
  if (o.items != null && !Array.isArray(o.items)) throw new Error('Artículos mal formados');
  return o as unknown as HttpOrder;
}

export function validateRider(value: unknown, expectedId?: string): Rider {
  const r = record(value), id = identifier(r.id);
  if (expectedId !== undefined && id !== expectedId) throw new Error('La respuesta pertenece a otro repartidor');
  if (r.user != null && r.user_id !== undefined && record(r.user).id !== r.user_id) {
    throw new Error('Identidad de usuario contradictoria');
  }
  if (r.status != null && !['PENDIENTE', 'ACTIVO', 'INACTIVO', 'OCUPADO', 'SUSPENDIDO'].includes(String(r.status))) throw new Error('Estado de repartidor desconocido');
  if (r.is_online != null && typeof r.is_online !== 'boolean') throw new Error('Disponibilidad de repartidor mal formada');
  // Do not manufacture User role, activity or audit dates for a Rider summary.
  return { ...r } as unknown as Rider;
}

export function uniqueArray<T>(value: unknown, adapt: (row: unknown) => T & { id: string }): T[] {
  if (!Array.isArray(value)) throw new Error('Se esperaba un array del servidor');
  const seen = new Set<string>();
  return value.map(row => {
    const result = adapt(row);
    if (seen.has(result.id)) throw new Error('El catálogo contiene identidades duplicadas; vuelve a cargar');
    seen.add(result.id);
    return result;
  });
}

/** Atomic bounded read: never return a truncated catalog or continue in another session. */
export async function readOrderCatalog(params: OrderListParams = {}, assertCurrent: () => void): Promise<HttpOrder[]> {
  if (params.customer_id) throw new Error('El servidor no informa customer_id para filtrar');
  const size = params.limit ?? CATALOG_PAGE_SIZE;
  if (!Number.isInteger(size) || size < 1 || size > CATALOG_PAGE_SIZE) throw new Error('limit debe estar entre 1 y 200');
  if (params.page !== undefined && params.page !== 1 || params.offset !== undefined && params.offset !== 0) {
    throw new Error('El catálogo completo debe comenzar en offset 0');
  }
  if (params.status && !ORDER_STATUSES.includes(params.status)) throw new Error('Estado de filtro desconocido');
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.rider_id) query.set('rider_id', params.rider_id);
  query.set('limit', String(size));
  const result: HttpOrder[] = [], seen = new Set<string>();
  for (let page = 0; page < CATALOG_MAX_PAGES; page++) {
    assertCurrent();
    query.set('offset', String(page * size));
    const raw = await api.get<unknown>(`/orders?${query}`);
    assertCurrent();
    const rows = uniqueArray(raw, row => validateHttpOrder(row));
    if (rows.length > size) throw new Error('El servidor excedió el tamaño de página solicitado');
    for (const row of rows) {
      if (seen.has(row.id)) throw new Error('El catálogo cambió entre páginas o contiene duplicados; vuelve a cargar');
      if (params.status && row.status !== params.status || params.rider_id && row.assigned_rider_id !== params.rider_id) {
        throw new Error('El servidor devolvió pedidos fuera del filtro solicitado');
      }
      seen.add(row.id); result.push(row);
    }
    if (rows.length < size) {
      const from = params.date_from ? Date.parse(params.date_from) : undefined;
      const to = params.date_to ? Date.parse(params.date_to) : undefined;
      if (from !== undefined && !Number.isFinite(from) || to !== undefined && !Number.isFinite(to)) throw new Error('Fecha de filtro inválida');
      return result.filter(row => {
        const time = row.created_at ? Date.parse(row.created_at) : NaN;
        return (from === undefined || time >= from) && (to === undefined || time <= to);
      });
    }
  }
  throw new Error(`Catálogo incompleto: se alcanzó el límite de ${CATALOG_MAX_PAGES} páginas. Acota por estado o repartidor.`);
}

export async function readRiderCatalog(params: { status_filter?: string; is_online?: boolean }, assertCurrent: () => void): Promise<Rider[]> {
  assertCurrent();
  const q = new URLSearchParams();
  if (params.status_filter) q.set('status_filter', params.status_filter);
  if (params.is_online !== undefined) q.set('is_online', String(params.is_online));
  const raw = await api.get<unknown>(`/riders${q.toString() ? `?${q}` : ''}`);
  assertCurrent();
  const riders = uniqueArray(raw, row => validateRider(row));
  const users = new Set<string>();
  for (const r of riders) {
    if (r.user_id !== undefined) {
      const user = identifier(r.user_id);
      if (users.has(user)) throw new Error('Un usuario aparece con identidades de repartidor contradictorias');
      users.add(user);
    }
  }
  if (riders.some(r => params.status_filter && r.status !== params.status_filter || params.is_online !== undefined && r.is_online !== params.is_online)) {
    throw new Error('El servidor devolvió repartidores fuera del filtro solicitado');
  }
  return riders;
}
