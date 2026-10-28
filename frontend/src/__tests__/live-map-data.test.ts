import { riderSnapshot, orderSnapshot, mergeMapPositions } from '@/lib/live-map-data';
it('accepts numeric zero and numeric string coordinates without treating missing values as zero', () => {
  const out = riderSnapshot([
    { id: 'zero', last_lat: 0, last_lng: '0', is_online: true },
    { id: 'missing', last_lat: null, last_lng: null, is_online: true },
    { id: 'blank', last_lat: '', last_lng: '', is_online: true },
  ]);
  expect(out.riders.map((r) => r.id)).toEqual(['zero']);
  expect(out.riders[0]).toMatchObject({ lat: 0, lng: 0, status: 'ONLINE' });
  expect(out.onlineWithoutLocation).toBe(2);
});
it.each([
  { last_lat: 91, last_lng: 1 },
  { last_lat: 1, last_lng: 181 },
  { last_lat: Infinity, last_lng: 1 },
  { last_lat: 'invalid', last_lng: 1 },
])('drops coordinates outside the map domain: %p', (location) => {
  expect(riderSnapshot([{ id: 'r', ...location, is_online: true }]).riders).toEqual([]);
});
it('preserves safe rider metadata and does not invent a current timestamp', () => {
  expect(
    riderSnapshot([
      {
        id: 'r',
        last_lat: 1,
        last_lng: 2,
        is_online: true,
        current_order_id: 'o',
        phone: '123',
        first_name: 'Test',
        last_name: 'Rider',
        last_location_at: 'invalid',
      },
    ]).riders[0]
  ).toMatchObject({
    name: 'Test Rider',
    status: 'BUSY',
    phone: '123',
    lastUpdate: '--:--',
    positionTimestamp: null,
  });
});
it('keeps picked-up orders visible, canonical zero coordinates and excludes terminal orders', () => {
  const out = orderSnapshot([
    {
      id: 'o',
      status: 'RECOLECTADO',
      delivery_latitude: 0,
      delivery_longitude: 0,
      delivery_lat: 5,
      delivery_lng: 5,
    },
    { id: 'terminal', status: 'ENTREGADO', delivery_lat: 1, delivery_lng: 1 },
    { id: 'invalid', status: 'EN_RUTA', delivery_lat: null, delivery_lng: null },
  ]);
  expect(out).toEqual([{ id: 'o', status: 'RECOLECTADO', lat: 0, lng: 0, customer: 'Cliente' }]);
});
it('keeps a newer live position when a slower REST snapshot arrives', () => {
  const base = riderSnapshot([
    {
      id: 'r',
      last_lat: 1,
      last_lng: 1,
      last_location_at: '2026-10-27T09:00:00Z',
      phone: '123',
      is_online: true,
    },
  ]).riders;
  const merged = mergeMapPositions(base, [
    { riderId: 'r', lat: 2, lng: 2, timestamp: '2026-10-27T10:00:00Z' },
  ]);
  expect(merged[0]).toMatchObject({
    lat: 2,
    lng: 2,
    phone: '123',
    positionTimestamp: '2026-10-27T10:00:00Z',
  });
});
it('does not rewind newer REST data with an older or undated live point', () => {
  const base = riderSnapshot([
    {
      id: 'r',
      last_lat: 3,
      last_lng: 3,
      last_location_at: '2026-10-27T11:00:00Z',
      is_online: true,
    },
  ]).riders;
  expect(
    mergeMapPositions(base, [
      { riderId: 'r', lat: 1, lng: 1, timestamp: '2026-10-27T10:00:00Z' },
    ])[0].lat
  ).toBe(3);
  expect(mergeMapPositions(base, [{ riderId: 'r', lat: 1, lng: 1 }])[0].lat).toBe(3);
});
it('can show an authorized live rider absent in REST without fabricating timestamp or contact data', () => {
  const out = mergeMapPositions([], [{ riderId: 'new', lat: 1, lng: 1 }]);
  expect(out[0]).toMatchObject({ id: 'new', name: 'Repartidor', lastUpdate: '--:--' });
  expect(out[0].phone).toBeUndefined();
});

it('compares the UTC-naive REST snapshot and offset-aware live point as UTC instants', () => {
  const base = riderSnapshot([{ id: 'r', last_lat: 3, last_lng: 3, is_online: true, last_location_at: '2026-10-27T11:00:00' }]).riders;
  expect(base[0].positionTimestamp).toBe('2026-10-27T11:00:00Z');
  expect(mergeMapPositions(base, [{ riderId: 'r', lat: 1, lng: 1, timestamp: '2026-10-27T06:00:00-04:00' }])[0].lat).toBe(3);
});
