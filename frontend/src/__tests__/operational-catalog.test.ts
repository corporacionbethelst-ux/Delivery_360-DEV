import { api } from '@/lib/api';
import { CATALOG_MAX_PAGES, readOrderCatalog, readRiderCatalog, validateHttpOrder, validateRider } from '@/lib/operational-catalog';
import { orderView, filterOrderViews, itemCount, canAssignOrder } from '@/lib/order-view';
import { useOrdersStore } from '@/stores/ordersStore';
import { useRidersStore } from '@/stores/ridersStore';
import { orderService } from '@/services/order.service';
import { riderService } from '@/services/rider.service';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import sample from './fixtures/order-assignment-response.json';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() } }));
const row = (id: string, extra = {}) => ({ id, status: 'PENDIENTE', ...extra });
const page = (prefix: string) => Array.from({ length: 200 }, (_, i) => row(`${prefix}-${i}`));
function deferred() { let resolve!: (value: any) => void, reject!: (error: Error) => void;
  const promise = new Promise<any>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'catalog-a', refresh_token: 'refresh-a' }); });
afterEach(() => clearStoredTokens());

it('reads actual limit/offset arrays to completion and counts only a complete filtered snapshot', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(page('first')).mockResolvedValueOnce([row('last')]);
  await useOrdersStore.getState().fetchOrders();
  expect(api.get).toHaveBeenNthCalledWith(1, '/orders?limit=200&offset=0');
  expect(api.get).toHaveBeenNthCalledWith(2, '/orders?limit=200&offset=200');
  expect(useOrdersStore.getState().orders).toHaveLength(201);
  expect(useOrdersStore.getState().pagination).toMatchObject({ total: 201, totalPages: 11 });
});
it('uses a single status/rider server filter, never a comma list or page/page_size', async () => {
  jest.mocked(api.get).mockResolvedValue([row('one', { assigned_rider_id: 'r', status: 'ASIGNADO' })]);
  await useOrdersStore.getState().fetchOrders({ status: ['ASIGNADO'], riderId: 'r' });
  const q = new URL(String(jest.mocked(api.get).mock.calls[0][0]), 'https://test').searchParams;
  expect(Object.fromEntries(q)).toEqual({ status: 'ASIGNADO', rider_id: 'r', limit: '200', offset: '0' });
});
it('applies multiple statuses and search after complete acquisition, not just to the first page', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(page('first')).mockResolvedValueOnce([row('target', { customer_name: 'Ana', status: 'EN_RUTA' })]);
  await useOrdersStore.getState().fetchOrders({ status: ['EN_RUTA', 'ENTREGADO'], search: 'Ana' });
  expect(useOrdersStore.getState().orders.map(o => o.id)).toEqual(['target']);
  expect(String(jest.mocked(api.get).mock.calls[0][0])).not.toContain('status=');
});
it.each([undefined, null, {}, { items: [] }, [{ id: 'missing-status' }], [row('x'), row('x')]])('rejects malformed or duplicate arrays (%j)', async raw => {
  jest.mocked(api.get).mockResolvedValue(raw);
  await expect(readOrderCatalog({}, () => {})).rejects.toThrow();
});
it.each(['network', 'malformed', 'duplicate', 'contradictory'])('keeps previous catalog and totals after a bad later page (%s)', async mode => {
  const previous = orderView(row('previous'));
  useOrdersStore.setState({ orders: [previous], pagination: { page: 1, pageSize: 20, total: 1, totalPages: 1 } });
  jest.mocked(api.get).mockResolvedValueOnce(page('first'));
  if (mode === 'network') jest.mocked(api.get).mockRejectedValueOnce(new Error('later page failed'));
  else jest.mocked(api.get).mockResolvedValueOnce(mode === 'malformed' ? { items: [] } : mode === 'duplicate' ? [row('first-0')] :
    [row('bad', { assigned_rider_id: 'a', rider_id: 'b' })]);
  await expect(useOrdersStore.getState().fetchOrders()).rejects.toThrow();
  expect(useOrdersStore.getState().orders).toEqual([previous]);
  expect(useOrdersStore.getState().pagination.total).toBe(1);
  expect(useOrdersStore.getState()).toMatchObject({ isLoading: false, error: expect.any(String) });
});
it('fails visibly at the bounded page cap without publishing a partial catalog', async () => {
  jest.mocked(api.get).mockImplementation(async url => page(String(url)));
  await expect(useOrdersStore.getState().fetchOrders()).rejects.toThrow(/incompleto/);
  expect(api.get).toHaveBeenCalledTimes(CATALOG_MAX_PAGES);
  expect(useOrdersStore.getState().orders).toEqual([]);
  expect(useOrdersStore.getState().pagination.total).toBeNull();
});
it.each([{ limit: 0 }, { limit: 201 }, { limit: 1.5 }, { page: 2 }, { offset: 20 }, { customer_id: 'x' }, { status: 'NOPE' }])('rejects unsupported catalog scope before HTTP (%j)', async params => {
  await expect(readOrderCatalog(params as never, () => {})).rejects.toThrow();
  expect(api.get).not.toHaveBeenCalled();
});
it('rejects a page larger than requested and a server filter that was ignored', async () => {
  jest.mocked(api.get).mockResolvedValue([row('a'), row('b')]);
  await expect(readOrderCatalog({ limit: 1 }, () => {})).rejects.toThrow(/tamaño/);
  jest.mocked(api.get).mockResolvedValue([row('a')]);
  await expect(readOrderCatalog({ status: 'ENTREGADO' }, () => {})).rejects.toThrow(/filtro/);
});
it('service getAll completes the catalog, with date filtering performed locally', async () => {
  jest.mocked(api.get).mockResolvedValueOnce([row('a', { created_at: '2026-10-31T10:00:00Z' }), row('b')]).mockResolvedValueOnce([]);
  expect(await orderService.getAll({ limit: 2, date_from: '2026-10-31' })).toMatchObject([{ id: 'a' }]);
  expect(api.get).toHaveBeenNthCalledWith(1, '/orders?limit=2&offset=0');
  expect(api.get).toHaveBeenNthCalledWith(2, '/orders?limit=2&offset=2');
});
it('stops before another page can use replacement account credentials', async () => {
  const pending = deferred(); jest.mocked(api.get).mockReturnValue(pending.promise);
  const request = useOrdersStore.getState().fetchOrders().catch(e => e);
  storeTokens({ access_token: 'catalog-b', refresh_token: 'refresh-b' });
  const replacement = orderView(row('b')); useOrdersStore.getState().setOrders([replacement]);
  pending.resolve(page('old'));
  expect(await request).toBeInstanceOf(SessionChangedError);
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(useOrdersStore.getState().orders).toEqual([replacement]);
});
it.each(['success', 'failure'])('does not publish an older list completion or error (%s)', async mode => {
  const old = deferred(); jest.mocked(api.get).mockReturnValueOnce(old.promise).mockResolvedValueOnce([row('new')]);
  const first = useOrdersStore.getState().fetchOrders().catch(e => e);
  await useOrdersStore.getState().fetchOrders();
  if (mode === 'success') old.resolve(page('old')); else old.reject(new Error('stale failure'));
  await first;
  expect(api.get).toHaveBeenCalledTimes(2);
  expect(useOrdersStore.getState()).toMatchObject({ orders: [{ id: 'new' }], error: null, isLoading: false });
});
it.each(['orders', 'riders'])('keeps only the newest detail query (%s)', async type => {
  const old = deferred(); jest.mocked(api.get).mockReturnValueOnce(old.promise).mockResolvedValueOnce(type === 'orders' ? row('new') : { id: 'new' });
  const first = type === 'orders' ? useOrdersStore.getState().fetchOrderById('old') : useRidersStore.getState().fetchRiderById('old');
  await (type === 'orders' ? useOrdersStore.getState().fetchOrderById('new') : useRidersStore.getState().fetchRiderById('new'));
  old.resolve(type === 'orders' ? row('old') : { id: 'old' }); await first;
  expect(type === 'orders' ? useOrdersStore.getState().selectedOrder?.id : useRidersStore.getState().selectedRider?.id).toBe('new');
});
it.each(['orders', 'riders'])('rejects detail responses for an incorrect identity (%s)', async type => {
  jest.mocked(api.get).mockResolvedValue(type === 'orders' ? row('wrong') : { id: 'wrong' });
  await expect(type === 'orders' ? useOrdersStore.getState().fetchOrderById('requested') : useRidersStore.getState().fetchRiderById('requested')).rejects.toThrow(/otro/);
  expect(type === 'orders' ? useOrdersStore.getState().selectedOrder : useRidersStore.getState().selectedRider).toBeNull();
});
it('uses rider status_filter/is_online=false and filters unsupported fields locally', async () => {
  const r = { id: 'r', status: 'ACTIVO', is_online: false, vehicle_type: 'MOTO', operating_zone: 'Centro', full_name: 'Ana', created_at: '2026-10-31T12:00:00Z', last_lat: 0, last_lng: 0 };
  jest.mocked(api.get).mockResolvedValue([r]);
  await useRidersStore.getState().fetchRiders({ status: ['ACTIVO'], is_online: false, vehicle_type: ['MOTO'], operating_zone: 'Centro', search: 'ana', dateFrom: new Date('2026-10-30') });
  expect(api.get).toHaveBeenCalledWith('/riders?status_filter=ACTIVO&is_online=false');
  expect(useRidersStore.getState()).toMatchObject({ riders: [r], total: 1 });
  expect(useRidersStore.getState().riders[0]).not.toHaveProperty('role');
  expect(useRidersStore.getState().riders[0]).not.toHaveProperty('is_active');
});
it('does not let stored search filters silently remove assignment candidates', async () => {
  useRidersStore.getState().setFilters({ search: 'previous search', vehicle_type: ['AUTO'] });
  jest.mocked(api.get).mockResolvedValue([{ id: 'r', status: 'ACTIVO', is_online: true }]);
  await useRidersStore.getState().fetchRiders({ status: ['ACTIVO'], is_online: true });
  expect(useRidersStore.getState().total).toBe(1);
});
it('filters multiple rider statuses locally without sending a comma list', async () => {
  jest.mocked(api.get).mockResolvedValue([{ id: 'a', status: 'ACTIVO' }, { id: 'b', status: 'PENDIENTE' }, { id: 's', status: 'SUSPENDIDO' }]);
  await useRidersStore.getState().fetchRiders({ status: ['ACTIVO', 'PENDIENTE'] });
  expect(api.get).toHaveBeenCalledWith('/riders');
  expect(useRidersStore.getState().riders.map(r => r.id)).toEqual(['a', 'b']);
});
it.each([{}, null, [{ id: 'r' }, { id: 'r' }], [{ id: 'r', user_id: 'a', user: { id: 'b' } }]])('rejects malformed rider catalogs (%j)', async raw => {
  jest.mocked(api.get).mockResolvedValue(raw);
  await expect(readRiderCatalog({}, () => {})).rejects.toThrow();
});
it('validates rider service arrays and requested filters', async () => {
  jest.mocked(api.get).mockResolvedValue([{ id: 'r', is_online: false }]);
  await expect(riderService.listRiders({ is_online: true })).rejects.toThrow(/filtro/);
  jest.mocked(api.get).mockResolvedValue([]);
  expect(await riderService.getAll()).toEqual([]);
});
it.each(['success', 'failure'])('fences old rider list responses (%s)', async mode => {
  const old = deferred(); jest.mocked(api.get).mockReturnValueOnce(old.promise).mockResolvedValueOnce([{ id: 'new' }]);
  const first = useRidersStore.getState().fetchRiders().catch(e => e);
  await useRidersStore.getState().fetchRiders();
  if (mode === 'success') old.resolve([{ id: 'old' }]); else old.reject(new Error('stale'));
  await first;
  expect(useRidersStore.getState()).toMatchObject({ riders: [{ id: 'new' }], error: null });
});
it.each(['store', 'service'])('sends new_status in the query and validates the status confirmation (%s)', async source => {
  jest.mocked(api.patch).mockResolvedValue(row('a/b', { status: 'EN_RUTA' }));
  if (source === 'store') await useOrdersStore.getState().updateOrderStatus('a/b', 'EN_RUTA');
  else await orderService.updateStatus('a/b', 'EN_RUTA');
  expect(api.patch).toHaveBeenCalledWith('/orders/a%2Fb/status', {}, { params: { new_status: 'EN_RUTA' } });
  jest.mocked(api.patch).mockResolvedValue(row('wrong', { status: 'EN_RUTA' }));
  await expect(source === 'store' ? useOrdersStore.getState().updateOrderStatus('a', 'EN_RUTA') : orderService.updateStatus('a', 'EN_RUTA')).rejects.toThrow(/otro/);
});
it('rejects contradictory assignment identity aliases before publishing success', async () => {
  jest.mocked(api.patch).mockResolvedValue({ ...sample, rider_id: 'wrong' });
  await expect(useOrdersStore.getState().assignRider(sample.id, sample.assigned_rider_id)).rejects.toThrow(/contradictorias/);
  expect(useOrdersStore.getState().orders).toEqual([]);
});
it.each([
  { rider_id: 'a', assigned_rider_id: 'b' }, { assigned_rider_id: null, assigned_rider: { id: 'r' } },
  { delivery: { id: 'd', order_id: 'other' } }, { status: 'NOT_REAL' },
])('rejects contradictory order identities and unknown states (%j)', change => {
  expect(() => validateHttpOrder(row('o', change))).toThrow();
});
it('preserves absence, informed emptiness and legitimate zero values in the visual model', () => {
  const absent = orderView(row('o'));
  for (const field of ['total', 'subtotal', 'deliveryFee', 'discount', 'items', 'createdAt', 'paymentMethod', 'paymentStatus', 'type', 'createdBy']) expect(absent[field as keyof typeof absent]).toBeUndefined();
  const zero = orderView(row('z', { total: 0, total_amount: 99, subtotal: '0', delivery_fee: 0, pickup_lat: 0, pickup_lng: 0, delivery_lat: 0, delivery_lng: 0, items: [] }));
  expect(zero).toMatchObject({ total: 0, subtotal: 0, deliveryFee: 0, items: [], pickupAddress: { latitude: 0, longitude: 0 } });
  expect(itemCount(absent.items)).toBeUndefined(); expect(itemCount(zero.items)).toBe(0);
  expect(validateRider({ id: 'r' })).not.toHaveProperty('role');
});
it('does not invent item quantities/prices or convert malformed dates/coordinates into current data', () => {
  const o = orderView(row('o', { items: [{ product_name: 'Unknown' }, { product_name: 'Free', quantity: 0, unit_price: 0, subtotal: 0 }], created_at: 'bad', total: false, pickup_lat: 91, pickup_lng: 181 }));
  expect(o.items?.[0].quantity).toBeUndefined(); expect(o.items?.[0].unitPrice).toBeUndefined();
  expect(o.items?.[1]).toMatchObject({ quantity: 0, unitPrice: 0, totalPrice: 0 });
  expect(itemCount(o.items)).toBeUndefined(); expect(o.createdAt).toBeUndefined(); expect(o.total).toBeUndefined(); expect(o.pickupAddress.latitude).toBeUndefined();
});
it('applies supported visual filters without treating absent payment/type as known', () => {
  const o = orderView(row('o', { priority: 'NORMAL', created_at: '2026-10-31T00:00:00Z', payment_method: 'efectivo', payment_status: 'pagado' }));
  expect(filterOrderViews([o], { priority: ['NORMAL'], dateFrom: new Date('2026-10-30'), dateTo: new Date('2026-11-01'), paymentStatus: 'PAGADO' })).toEqual([o]);
  expect(filterOrderViews([o], { type: ['DOMICILIO'] })).toEqual([]);
});
it.each(['ASIGNADO', 'EN_RECOLECCION', 'RECOLECTADO', 'EN_RUTA', 'ENTREGADO', 'FALLIDO', 'CANCELADO'])('does not offer a first assignment for %s', status => {
  expect(canAssignOrder(orderView(row('o', { status })))).toBe(false);
});
it.each(['list', 'detail', 'service-list', 'service-riders'])('does not publish a successful response from the previous account (%s)', async source => {
  const old = deferred(); jest.mocked(api.get).mockReturnValue(old.promise);
  const work = source === 'list' ? useRidersStore.getState().fetchRiders() : source === 'detail' ? useRidersStore.getState().fetchRiderById('r') : source === 'service-list' ? orderService.getAll() : riderService.getAll();
  const result = work.catch(e => e);
  storeTokens({ access_token: 'b', refresh_token: 'rb' });
  old.resolve(source === 'detail' ? { id: 'r' } : source === 'service-list' ? [row('o')] : [{ id: 'r' }]);
  expect(await result).toBeInstanceOf(SessionChangedError);
  expect(useRidersStore.getState().riders).toEqual([]);
  expect(useRidersStore.getState().selectedRider).toBeNull();
});
it.each(['store', 'service'])('rejects a status response that did not confirm the requested transition (%s)', async source => {
  jest.mocked(api.patch).mockResolvedValue(row('o'));
  await expect(source === 'store' ? useOrdersStore.getState().updateOrderStatus('o', 'EN_RUTA') : orderService.updateStatus('o', 'EN_RUTA')).rejects.toThrow(/confirmó/);
});
it('does not replace an assignment with an older outstanding list response', async () => {
  const old = deferred(); jest.mocked(api.get).mockReturnValue(old.promise);
  useOrdersStore.getState().setOrders([orderView(row(sample.id))]);
  const first = useOrdersStore.getState().fetchOrders().catch(e => e);
  jest.mocked(api.patch).mockResolvedValue(sample);
  await useOrdersStore.getState().assignRider(sample.id, sample.assigned_rider_id);
  old.resolve([row(sample.id)]); await first;
  expect(useOrdersStore.getState().orders[0].status).toBe('ASIGNADO');
  expect(useOrdersStore.getState().isLoading).toBe(false);
});
it.each([
  { order_id: 'wrong' }, { assigned_rider: { id: '' } },
  { assigned_rider: { id: 'r', name: 'Ana', distance_km: Infinity } }, { other_candidates: -1 },
])('rejects invalid automatic assignment confirmations (%j)', async change => {
  jest.mocked(api.post).mockResolvedValue({ message: 'OK', order_id: 'o', assigned_rider: { id: 'r', name: 'Ana', distance_km: 0 }, other_candidates: 0, ...change });
  await expect(orderService.assignRiderAuto('o')).rejects.toThrow();
});
it('accepts a coherent automatic assignment confirmation with zero distance and no other candidates', async () => {
  const confirmation = { message: 'OK', order_id: 'o', assigned_rider: { id: 'r', name: 'Ana', distance_km: 0 }, other_candidates: 0 };
  jest.mocked(api.post).mockResolvedValue(confirmation);
  expect(await orderService.assignRiderAuto('o')).toEqual(confirmation);
});
it('rejects two rider profiles claiming the same user identity', async () => {
  jest.mocked(api.get).mockResolvedValue([{ id: 'a', user_id: 'one-user' }, { id: 'b', user_id: 'one-user' }]);
  await expect(riderService.getAll()).rejects.toThrow(/contradictorias/);
});
