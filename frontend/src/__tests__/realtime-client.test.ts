import { realtimeUrl, trackingChannel, readPosition, mergePositions } from '@/lib/realtime-client';
const keys = [
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_TRACKING_WS',
  'NEXT_PUBLIC_NOTIFICATIONS_WS',
  'WS_BASE_URL',
] as const;
const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
beforeEach(() => {
  keys.forEach((key) => delete process.env[key]);
  process.env.NEXT_PUBLIC_API_URL = 'https://api.example.test/api/v1';
});
afterEach(() => {
  keys.forEach((key) => {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  });
});
it.each(['true', 'false'])(
  'treats the historical tracking flag %s as a flag rather than a URL',
  (flag) => {
    process.env.NEXT_PUBLIC_TRACKING_WS = flag;
    expect(realtimeUrl('tracking', 'token', 'dashboard')).toBe(
      'wss://api.example.test/api/v1/tracking/ws/dashboard?token=token'
    );
  }
);
it.each([
  'https://ws.example.test/api/v1/tracking/ws',
  'wss://ws.example.test/api/v1/tracking/ws/',
])('supports an explicit endpoint URL %s', (url) => {
  process.env.NEXT_PUBLIC_TRACKING_WS = url;
  expect(realtimeUrl('tracking', 'token', 'dashboard')).toBe(
    'wss://ws.example.test/api/v1/tracking/ws/dashboard?token=token'
  );
});
it('supports relative REST configuration and URL-encodes the token and channel', () => {
  process.env.NEXT_PUBLIC_API_URL = '/api/v1';
  const channel = 'rider:123E4567-E89B-42D3-A456-426614174000';
  const url = new URL(realtimeUrl('tracking', 'opaque+token&secret=1', channel));
  expect(url.pathname).toBe('/api/v1/tracking/ws/rider%3A123e4567-e89b-42d3-a456-426614174000');
  expect(url.searchParams.get('token')).toBe('opaque+token&secret=1');
  expect(url.searchParams.has('secret')).toBe(false);
});
it('builds the actual notifications endpoint without a duplicate suffix', () => {
  process.env.NEXT_PUBLIC_NOTIFICATIONS_WS = 'wss://ws.example.test/api/v1/notifications/ws';
  expect(realtimeUrl('notifications', 'token')).toBe(
    'wss://ws.example.test/api/v1/notifications/ws?token=token'
  );
});
it.each([
  'ftp://api.example.test/api/v1',
  'wss://user:private@api.example.test/api/v1',
  'wss://api.example.test/api/v1?token=private',
  'wss://api.example.test/api/v1#private',
  'http://[invalid',
])('rejects an unsafe URL without reflecting its contents: %s', (url) => {
  process.env.NEXT_PUBLIC_TRACKING_WS = url;
  expect(() => realtimeUrl('tracking', 'token', 'dashboard')).toThrow(
    'Configuración de tiempo real no válida'
  );
});
it.each([
  'dashboardx',
  'rider:bad',
  'order:bad',
  'RIDER:123e4567-e89b-42d3-a456-426614174000',
  '../dashboard',
  ' dashboard',
])('rejects unsupported channel %s', (channel) => {
  expect(trackingChannel(channel)).toBeNull();
  expect(() => realtimeUrl('tracking', 'token', channel)).toThrow('Canal');
});
it('keeps order channels scoped to a canonical UUID', () => {
  expect(trackingChannel('order:123E4567-E89B-42D3-A456-426614174000')).toBe(
    'order:123e4567-e89b-42d3-a456-426614174000'
  );
});
it.each([
  { lat: NaN, lng: 1 },
  { lat: 91, lng: 1 },
  { lat: 1, lng: 181 },
  { lat: '1', lng: 1 },
  { lat: null, lng: 1 },
  { lat: 1, lng: Infinity },
])('rejects invalid coordinates %p', (coords) => {
  expect(readPosition({ riderId: 'r', ...coords })).toBeNull();
});
it('accepts zero coordinates and ignores invalid optional measurements', () => {
  expect(
    readPosition({
      riderId: 'r',
      lat: 0,
      lng: 0,
      speedKmh: -1,
      accuracyMeters: 'x',
      headingDegrees: 400,
    })
  ).toEqual({ riderId: 'r', lat: 0, lng: 0, timestamp: undefined });
});
it.each(['', 'bad id', 'bad\u0000id', 'x'.repeat(129)])(
  'rejects malformed rider ID %s',
  (riderId) => {
    expect(readPosition({ riderId, lat: 1, lng: 1 })).toBeNull();
  }
);
it('rejects invalid timestamps and retains accepted measurements', () => {
  expect(readPosition({ riderId: 'r', lat: 1, lng: 1, timestamp: 'invalid' })).toBeNull();
  expect(
    readPosition({
      riderId: 'r',
      lat: 1,
      lng: 1,
      speedKmh: 0,
      headingDegrees: 0,
      accuracyMeters: 1,
    })
  ).toMatchObject({ speedKmh: 0, headingDegrees: 0, accuracyMeters: 1 });
});
it('does not rewind a known timestamp and bounds the most recently updated riders', () => {
  const newer = { riderId: 'r', lat: 2, lng: 2, timestamp: '2026-10-27T10:00:00Z' };
  expect(mergePositions([newer], [{ riderId: 'r', lat: 0, lng: 0 }], 10)).toEqual([newer]);
  expect(
    mergePositions([newer], [{ ...newer, lat: 1, timestamp: '2026-10-27T09:00:00Z' }], 10)
  ).toEqual([newer]);
  expect(
    mergePositions(
      [newer],
      [
        { riderId: 'b', lat: 1, lng: 1 },
        { riderId: 'c', lat: 1, lng: 1 },
      ],
      2
    ).map((p) => p.riderId)
  ).toEqual(['b', 'c']);
});

it('normalizes the backend UTC-naive timestamp and preserves explicit timezone offsets', () => {
  expect(
    readPosition({ riderId: 'r', lat: 1, lng: 2, timestamp: '2026-10-27T10:00:00.123456' })
      ?.timestamp
  ).toBe('2026-10-27T10:00:00.123456Z');
  expect(
    readPosition({ riderId: 'r', lat: 1, lng: 2, timestamp: '2026-10-27T06:00:00-04:00' })
      ?.timestamp
  ).toBe('2026-10-27T06:00:00-04:00');
});
