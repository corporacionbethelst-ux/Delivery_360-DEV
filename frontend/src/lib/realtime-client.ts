/** Wire formats and URL construction shared by the real tracking and inbox endpoints. */
export function trackingChannel(value: string): string | null {
  if (value === 'dashboard') return value;
  const match =
    /^(rider|order):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(value);
  return match && ['rider', 'order'].includes(match[1])
    ? `${match[1]}:${match[2].toLowerCase()}`
    : null;
}
export function realtimeUrl(
  kind: 'tracking' | 'notifications',
  token: string,
  channel = ''
): string {
  const explicit =
    kind === 'tracking'
      ? process.env.NEXT_PUBLIC_TRACKING_WS
      : process.env.NEXT_PUBLIC_NOTIFICATIONS_WS;
  // TRACKING_WS also historically acts as a boolean feature flag in the map page.
  const configured =
    explicit && !['true', 'false'].includes(explicit.toLowerCase())
      ? explicit
      : process.env.WS_BASE_URL;
  const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
  const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
  let url: URL;
  try {
    url = new URL(configured || api, origin);
  } catch {
    throw new Error('Configuración de tiempo real no válida');
  }
  if (url.protocol === 'http:') url.protocol = 'ws:';
  if (url.protocol === 'https:') url.protocol = 'wss:';
  if (
    !['ws:', 'wss:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !token ||
    (typeof window !== 'undefined' &&
      window.location.protocol === 'https:' &&
      url.protocol !== 'wss:')
  ) {
    throw new Error('Configuración de tiempo real no válida');
  }
  const base = url.pathname
    .replace(kind === 'tracking' ? /\/tracking\/ws\/?$/ : /\/notifications\/ws\/?$/, '')
    .replace(/\/$/, '');
  if (kind === 'tracking') {
    const logical = trackingChannel(channel);
    if (!logical) throw new Error('Canal de tracking no válido');
    url.pathname = `${base}/tracking/ws/${encodeURIComponent(logical)}`;
  } else url.pathname = `${base}/notifications/ws`;
  url.searchParams.set('token', token);
  return url.toString();
}
/** The tracking writer stores UTC without tzinfo; preserve that meaning in every browser timezone. */
export function normalizeTrackingTimestamp(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(value)
  )
    return null;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return Number.isFinite(Date.parse(normalized)) ? normalized : null;
}
export interface RiderPosition {
  riderId: string;
  lat: number;
  lng: number;
  speedKmh?: number | null;
  headingDegrees?: number | null;
  accuracyMeters?: number | null;
  timestamp?: string | null;
}
export function readPosition(input: unknown): RiderPosition | null {
  if (!input || typeof input !== 'object') return null;
  const p = input as Record<string, unknown>;
  const number = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
  if (
    typeof p.riderId !== 'string' ||
    !p.riderId ||
    p.riderId.length > 128 ||
    /[^\x21-\x7e]/.test(p.riderId) ||
    !number(p.lat) ||
    Math.abs(p.lat) > 90 ||
    !number(p.lng) ||
    Math.abs(p.lng) > 180
  )
    return null;
  if (p.timestamp != null && !normalizeTrackingTimestamp(p.timestamp)) return null;
  const out: RiderPosition = {
    riderId: p.riderId,
    lat: p.lat,
    lng: p.lng,
    timestamp:
      p.timestamp == null
        ? (p.timestamp as null | undefined)
        : normalizeTrackingTimestamp(p.timestamp),
  };
  if (number(p.speedKmh) && p.speedKmh >= 0) out.speedKmh = p.speedKmh;
  if (number(p.headingDegrees) && p.headingDegrees >= 0 && p.headingDegrees <= 360)
    out.headingDegrees = p.headingDegrees;
  if (number(p.accuracyMeters) && p.accuracyMeters >= 0) out.accuracyMeters = p.accuracyMeters;
  return out;
}
export function mergePositions(
  previous: RiderPosition[],
  incoming: RiderPosition[],
  limit: number
): RiderPosition[] {
  const map = new Map(previous.map((p) => [p.riderId, p]));
  for (const position of incoming) {
    const old = map.get(position.riderId);
    if (
      old?.timestamp &&
      (!position.timestamp ||
        Date.parse(normalizeTrackingTimestamp(position.timestamp) ?? position.timestamp) <
          Date.parse(normalizeTrackingTimestamp(old.timestamp) ?? old.timestamp))
    )
      continue;
    map.delete(position.riderId);
    map.set(position.riderId, position);
  }
  return Array.from(map.values()).slice(-limit);
}
export function boundedInteger(value: number, fallback: number, min: number, max: number): number {
  return Number.isInteger(value) && value >= min && value <= max ? value : fallback;
}
