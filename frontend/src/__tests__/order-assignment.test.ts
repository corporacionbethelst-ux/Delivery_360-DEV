import { api } from '@/lib/api';
import { storeTokens, clearStoredTokens, SessionChangedError } from '@/lib/auth-session';
import { orderAssignmentPatch } from '@/lib/order-assignment';
import { useOrdersStore } from '@/stores/ordersStore';
import { orderService } from '@/services/order.service';
import type { Order } from '@/types/order';
import sample from './fixtures/order-assignment-response.json';

jest.mock('@/lib/api', () => ({ api: { patch: jest.fn(), get: jest.fn(), delete: jest.fn() } }));
const oid = sample.id, rid = sample.assigned_rider_id;
const original = { id: oid, status: 'PENDIENTE', total: 0, customerName: 'Keep customer',
  pickupAddress: { street: 'Keep pickup' }, items: [] } as unknown as Order;
beforeEach(() => { jest.clearAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'test-session-a', refresh_token: 'test-refresh-a' }); });
afterEach(() => { clearStoredTokens(); jest.restoreAllMocks(); });

it('projects the exact HTTP/PostgreSQL contract without requiring a full User account', () => {
  const frozen = JSON.stringify(sample);
  const patch = orderAssignmentPatch(sample, oid, rid);
  expect(patch).toMatchObject({ status: 'ASIGNADO', assignedRiderId: rid,
    assignedRider: { id: rid, full_name: sample.assigned_rider.full_name },
    delivery: { id: sample.delivery.id, orderId: oid, riderId: rid,
      started_at: sample.delivery.started_at, sla_expected_minutes: sample.delivery.sla_expected_minutes } });
  expect(patch.assignedRider).not.toHaveProperty('role');
  expect(patch).not.toHaveProperty('total');
  expect(JSON.stringify(sample)).toBe(frozen);
});

it.each([
  { id: 'other' }, { status: 'PENDIENTE' }, { assigned_rider_id: 'other' },
  { assigned_rider: null }, { assigned_rider: { id: 'other' } }, { delivery: null },
  { delivery: { ...sample.delivery, id: '' } }, { delivery: { ...sample.delivery, order_id: 'other' } },
  { delivery: { ...sample.delivery, rider_id: 'other' } }, { delivery: { ...sample.delivery, status: 'EN_ROUTE' } },
])('rejects an inconsistent confirmation without claiming success (%j)', change => {
  expect(() => orderAssignmentPatch({ ...sample, ...change }, oid, rid)).toThrow(/confirmación/);
});

it.each([null, undefined, [], false])('rejects a missing or non-object confirmation (%j)', value => {
  expect(() => orderAssignmentPatch(value, oid, rid)).toThrow(/confirmación/);
});

it('keeps unknown timestamps/metrics unknown and preserves measured zeroes', () => {
  const patch = orderAssignmentPatch({ ...sample, delivery: { ...sample.delivery,
    started_at: null, sla_expected_minutes: 0, sla_actual_minutes: null, sla_compliant: null } }, oid, rid);
  expect(patch.delivery).toMatchObject({ started_at: null, sla_expected_minutes: 0, sla_actual_minutes: null, sla_compliant: null });
  const malformed = orderAssignmentPatch({ ...sample, delivery: { ...sample.delivery,
    started_at: {}, sla_expected_minutes: Infinity, sla_actual_minutes: 'unknown', sla_compliant: 'yes' } }, oid, rid);
  expect(malformed.delivery?.started_at).toBeUndefined();
  expect(malformed.delivery?.sla_expected_minutes).toBeUndefined();
  expect(malformed.delivery?.sla_compliant).toBeUndefined();
});

it('publishes only confirmed assignment fields while preserving money and customer data', async () => {
  useOrdersStore.getState().setOrders([original]);
  jest.mocked(api.patch).mockResolvedValue(sample);
  await useOrdersStore.getState().assignRider(oid, rid);
  expect(api.patch).toHaveBeenCalledWith(`/orders/${oid}/assign`, { rider_id: rid });
  expect(useOrdersStore.getState().orders[0]).toMatchObject({ total: 0, customerName: 'Keep customer',
    pickupAddress: original.pickupAddress, assignedRiderId: rid,
    assignedRider: { full_name: sample.assigned_rider.full_name }, status: 'ASIGNADO' });
});

it('does not change local business state after an inconsistent successful HTTP response', async () => {
  useOrdersStore.getState().setOrders([original]);
  jest.mocked(api.patch).mockResolvedValue({ ...sample, assigned_rider_id: 'other' });
  await expect(useOrdersStore.getState().assignRider(oid, rid)).rejects.toThrow(/confirmación/);
  expect(useOrdersStore.getState().orders).toEqual([original]);
  expect(useOrdersStore.getState().isUpdating).toBe(false);
});

it('propagates an ordinary refusal and keeps the unassigned order visible', async () => {
  useOrdersStore.getState().setOrders([original]);
  const error = new Error('La documentación requiere revisión');
  jest.mocked(api.patch).mockRejectedValue(error);
  await expect(useOrdersStore.getState().assignRider(oid, rid)).rejects.toBe(error);
  expect(useOrdersStore.getState().orders).toEqual([original]);
  expect(useOrdersStore.getState().error).toBe(error.message);
});

it('fences a confirmed assignment that finishes after a different account starts', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.patch).mockReturnValue(new Promise(done => { resolve = done; }));
  const pending = useOrdersStore.getState().assignRider(oid, rid).catch(error => error);
  storeTokens({ access_token: 'test-session-b', refresh_token: 'test-refresh-b' });
  const next = { ...original, customerName: 'Account B' };
  useOrdersStore.getState().setOrders([next]);
  resolve(sample);
  expect(await pending).toBeInstanceOf(SessionChangedError);
  expect(useOrdersStore.getState().orders).toEqual([next]);
});

it.each([['', rid], [oid, '']])('rejects incomplete assignment identifiers before HTTP', async (order, rider) => {
  await expect(useOrdersStore.getState().assignRider(order, rider)).rejects.toThrow(/pedido/);
  expect(api.patch).not.toHaveBeenCalled();
});

it('escapes the order identifier without changing the confirmed identity', async () => {
  jest.mocked(api.patch).mockResolvedValue({ ...sample, id: 'a/b', delivery: { ...sample.delivery, order_id: 'a/b' } });
  await useOrdersStore.getState().assignRider('a/b', rid);
  expect(api.patch).toHaveBeenCalledWith('/orders/a%2Fb/assign', { rider_id: rid });
});

it.each([401, 404, 500])('does not turn a failed legacy stats read into fabricated revenue (%s)', async status => {
  const error = Object.assign(new Error('Unavailable'), { status });
  jest.mocked(api.get).mockRejectedValue(error);
  await expect(orderService.getStats()).rejects.toBe(error);
});

it('keeps real zero metrics without mutating the response', async () => {
  const data = Object.freeze({ total_orders: 0, total_revenue: 0, pending_count: 0,
    completed_count: 0, daily_revenue: Object.freeze([{ label: 'Day', value: 0 }]) });
  jest.mocked(api.get).mockResolvedValue(data);
  await expect(orderService.getStats()).resolves.toBe(data);
});

it.each([NaN, Infinity, null, '12'])('rejects malformed metric values instead of inventing zeroes (%j)', async value => {
  jest.mocked(api.get).mockResolvedValue({ total_orders: 1, total_revenue: 1, pending_count: 1,
    completed_count: 0, daily_revenue: [{ label: 'Day', value }] });
  await expect(orderService.getStats()).rejects.toThrow(/métricas/);
});

it('accepts a successful empty deletion response without reporting a second failure', async () => {
  jest.mocked(api.delete).mockResolvedValue(undefined);
  await expect(orderService.delete(oid)).resolves.toBeUndefined();
  expect(api.delete).toHaveBeenCalledTimes(1);
});
