import type { MapRider, MapOrder } from '@/components/maps/DeliveryMap';
import { normalizeTrackingTimestamp } from '@/lib/realtime-client';
import type { RiderPosition } from '@/lib/realtime-client';
export interface SnapshotRider extends MapRider {
  positionTimestamp?: string | null;
}
function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}
function coordinate(value: unknown, bound: number): number | null {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null;
  const n = Number(value);
  return Number.isFinite(n) && Math.abs(n) <= bound ? n : null;
}
function timestamp(value: unknown): string | null {
  return normalizeTrackingTimestamp(value);
}
function time(value: string | null): string {
  return value
    ? new Date(value).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : '--:--';
}
export function riderSnapshot(values: readonly unknown[]): {
  riders: SnapshotRider[];
  onlineWithoutLocation: number;
} {
  const riders: SnapshotRider[] = [];
  let onlineWithoutLocation = 0;
  for (const value of values) {
    const row = object(value);
    if (!row) continue;
    const lat = coordinate(row.last_lat, 90),
      lng = coordinate(row.last_lng, 180);
    if (lat === null || lng === null) {
      if (row.is_online === true) ++onlineWithoutLocation;
      continue;
    }
    if (typeof row.id !== 'string' || !row.id) continue;
    const positionTimestamp = timestamp(row.last_location_at);
    const orderId = typeof row.current_order_id === 'string' ? row.current_order_id : undefined;
    const name = [row.first_name, row.last_name]
      .filter((v) => typeof v === 'string')
      .join(' ')
      .trim();
    riders.push({
      id: row.id,
      name: name || 'Repartidor',
      lat,
      lng,
      status: row.is_online === true ? (orderId ? 'BUSY' : 'ONLINE') : 'OFFLINE',
      lastUpdate: time(positionTimestamp),
      positionTimestamp,
      orderId,
      phone: typeof row.phone === 'string' ? row.phone : undefined,
    });
  }
  return { riders, onlineWithoutLocation };
}
export function orderSnapshot(values: readonly unknown[]): MapOrder[] {
  const active = new Set([
    'EN_RUTA',
    'PENDIENTE',
    'ASIGNADO',
    'EN_CAMINO',
    'EN_RECOLECCION',
    'RECOLECTADO',
  ]);
  const orders: MapOrder[] = [];
  for (const value of values) {
    const row = object(value);
    if (!row || typeof row.status !== 'string' || !active.has(row.status)) continue;
    const lat = coordinate(row.delivery_latitude ?? row.delivery_lat, 90),
      lng = coordinate(row.delivery_longitude ?? row.delivery_lng, 180);
    const id = typeof row.external_id === 'string' && row.external_id ? row.external_id : row.id;
    if (lat === null || lng === null || typeof id !== 'string' || !id) continue;
    orders.push({
      id,
      lat,
      lng,
      status: row.status,
      customer:
        typeof row.customer_name === 'string' && row.customer_name ? row.customer_name : 'Cliente',
    });
  }
  return orders;
}
export function mergeMapPositions(
  base: SnapshotRider[],
  positions: RiderPosition[]
): SnapshotRider[] {
  if (!positions.length) return base;
  const byId = new Map(positions.map((p) => [p.riderId, p]));
  const known = new Set(base.map((r) => r.id));
  const merged = base.map((rider) => {
    const live = byId.get(rider.id);
    if (!live) return rider;
    if (
      rider.positionTimestamp &&
      (!live.timestamp || Date.parse(live.timestamp) < Date.parse(rider.positionTimestamp))
    )
      return rider;
    return {
      ...rider,
      lat: live.lat,
      lng: live.lng,
      positionTimestamp: live.timestamp ?? null,
      lastUpdate: live.timestamp ? time(live.timestamp) : rider.lastUpdate,
    };
  });
  for (const live of positions)
    if (!known.has(live.riderId)) {
      merged.push({
        id: live.riderId,
        name: 'Repartidor',
        lat: live.lat,
        lng: live.lng,
        status: 'ONLINE',
        positionTimestamp: live.timestamp ?? null,
        lastUpdate: time(live.timestamp ?? null),
      });
    }
  return merged;
}
