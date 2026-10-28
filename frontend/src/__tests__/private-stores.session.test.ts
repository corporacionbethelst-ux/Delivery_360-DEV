import { api } from '@/lib/api';
import client from '@/lib/api';
import { riderService } from '@/services/rider.service';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { useOrdersStore } from '@/stores/ordersStore';
import { useDeliveriesStore } from '@/stores/deliveriesStore';
import { useRidersStore } from '@/stores/ridersStore';
import { useRiderPersonalStore } from '@/stores/riderPersonalStore';
import { useFinancialStore } from '@/stores/financialStore';
import { useNotificationStore } from '@/stores/notificationStore';
import { useRealtimeStore } from '@/stores/realtimeStore';
jest.mock('@/lib/api', () => ({
  __esModule: true,
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn() },
  default: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));
jest.mock('@/services/rider.service', () => ({ riderService: { updateRider: jest.fn() } }));
const credentials = { access_token: 'owner-a', refresh_token: 'refresh-a' };
const replacement = { access_token: 'owner-b', refresh_token: 'refresh-b' };
const mocks = [
  ...Object.values(api),
  client.get,
  client.post,
  client.patch,
  client.delete,
  riderService.updateRider,
] as jest.Mock[];
const orders = {
  state: () => useOrdersStore.getState(),
  next: () => useOrdersStore.setState({ isLoading: true }),
};
const deliveries = {
  state: () => useDeliveriesStore.getState(),
  next: () => useDeliveriesStore.setState({ isLoading: true }),
};
const riders = {
  state: () => useRidersStore.getState(),
  next: () => useRidersStore.setState({ isLoading: true }),
};
const personal = {
  state: () => useRiderPersonalStore.getState(),
  next: () => useRiderPersonalStore.setState({ isLoading: true }),
};
const finance = {
  state: () => useFinancialStore.getState(),
  next: () => useFinancialStore.setState({ loading: true }),
};
interface Case {
  name: string;
  action: () => Promise<unknown>;
  state: () => unknown;
  next: () => void;
}
const cases: Case[] = [
  { name: 'orders list', action: () => useOrdersStore.getState().fetchOrders(), ...orders },
  { name: 'order detail', action: () => useOrdersStore.getState().fetchOrderById('o'), ...orders },
  {
    name: 'order creation',
    action: () => useOrdersStore.getState().createOrder({} as never),
    ...orders,
  },
  {
    name: 'order status',
    action: () => useOrdersStore.getState().updateOrderStatus('o', 'ENTREGADO'),
    ...orders,
  },
  {
    name: 'order assignment',
    action: () => useOrdersStore.getState().assignRider('o', 'r'),
    ...orders,
  },
  { name: 'order deletion', action: () => useOrdersStore.getState().deleteOrder('o'), ...orders },
  {
    name: 'deliveries list',
    action: () => useDeliveriesStore.getState().fetchDeliveries(),
    ...deliveries,
  },
  {
    name: 'delivery detail',
    action: () => useDeliveriesStore.getState().fetchDeliveryById('d'),
    ...deliveries,
  },
  {
    name: 'active deliveries',
    action: () => useDeliveriesStore.getState().fetchActiveDeliveries(),
    ...deliveries,
  },
  {
    name: 'pending deliveries',
    action: () => useDeliveriesStore.getState().fetchPendingDeliveries(),
    ...deliveries,
  },
  {
    name: 'delivery assign',
    action: () => useDeliveriesStore.getState().assignDelivery('d', 'r'),
    ...deliveries,
  },
  {
    name: 'delivery unassign',
    action: () => useDeliveriesStore.getState().unassignDelivery('d'),
    ...deliveries,
  },
  {
    name: 'delivery start',
    action: () => useDeliveriesStore.getState().startDelivery('d'),
    ...deliveries,
  },
  {
    name: 'delivery finish',
    action: () => useDeliveriesStore.getState().finishDelivery('d', {} as never),
    ...deliveries,
  },
  {
    name: 'delivery cancel',
    action: () => useDeliveriesStore.getState().cancelDelivery('d', 'reason'),
    ...deliveries,
  },
  { name: 'riders list', action: () => useRidersStore.getState().fetchRiders(), ...riders },
  { name: 'rider detail', action: () => useRidersStore.getState().fetchRiderById('r'), ...riders },
  {
    name: 'rider pending documents',
    action: () => useRidersStore.getState().fetchPendingDocuments(),
    ...riders,
  },
  {
    name: 'rider creation',
    action: () =>
      useRidersStore.getState().createRider({
        email: 'r@example.test',
        password: 'test-only',
        first_name: 'R',
        last_name: 'Test',
        phone: '123',
      }),
    ...riders,
  },
  { name: 'rider update', action: () => useRidersStore.getState().updateRider('r', {}), ...riders },
  { name: 'rider deletion', action: () => useRidersStore.getState().deleteRider('r'), ...riders },
  { name: 'rider approval', action: () => useRidersStore.getState().approveRider('r'), ...riders },
  {
    name: 'rider rejection',
    action: () => useRidersStore.getState().rejectRider('r', 'reason'),
    ...riders,
  },
  {
    name: 'personal deliveries',
    action: () => useRiderPersonalStore.getState().fetchMyDeliveries(),
    ...personal,
  },
  {
    name: 'personal earnings',
    action: () => useRiderPersonalStore.getState().fetchMyEarnings(),
    ...personal,
  },
  {
    name: 'personal start',
    action: () => useRiderPersonalStore.getState().startDeliveryAction('d'),
    ...personal,
  },
  {
    name: 'personal finish',
    action: () => useRiderPersonalStore.getState().finishDeliveryAction('d', {}),
    ...personal,
  },
  {
    name: 'financial summary',
    action: () => useFinancialStore.getState().fetchSummary(),
    ...finance,
  },
  {
    name: 'financial report',
    action: () => useFinancialStore.getState().getFinancialReport(),
    ...finance,
  },
  {
    name: 'financial daily adaptation',
    action: () => useFinancialStore.getState().getDailySummary('today'),
    ...finance,
  },
  {
    name: 'financial transactions',
    action: () => useFinancialStore.getState().getTransactions(),
    ...finance,
  },
  {
    name: 'payment rules',
    action: () => useFinancialStore.getState().fetchPaymentRules(),
    ...finance,
  },
  {
    name: 'payment rule update',
    action: () => useFinancialStore.getState().updatePaymentRule('rule', {}),
    ...finance,
  },
];
function pending() {
  let resolve!: (value: unknown) => void, reject!: (error: Error) => void;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  localStorage.clear();
  clearStoredTokens();
  storeTokens(credentials);
  mocks.forEach((mock) => mock.mockReset());
  jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  jest.restoreAllMocks();
  clearStoredTokens();
});
it.each(cases)(
  '$name cannot republish a completed result after another account starts',
  async (test) => {
    const deferred = pending();
    mocks.forEach((mock) => mock.mockReturnValue(deferred.promise));
    const work = test.action().then(
      (value) => ({ value, error: null }),
      (error) => ({ error, value: null })
    );
    expect(mocks.some((mock) => mock.mock.calls.length > 0)).toBe(true);
    storeTokens(replacement);
    test.next();
    const nextState = test.state();
    deferred.resolve({ id: 'owner-a-private', data: { id: 'owner-a-private' } });
    expect((await work).error).toBeInstanceOf(SessionChangedError);
    expect(test.state()).toBe(nextState);
    expect(console.error).not.toHaveBeenCalled();
  }
);
it.each(cases)(
  '$name ignores a late error without clearing the next operation flags',
  async (test) => {
    const deferred = pending();
    mocks.forEach((mock) => mock.mockReturnValue(deferred.promise));
    const work = test.action().then(
      () => null,
      (error) => error
    );
    storeTokens(replacement);
    test.next();
    const nextState = test.state();
    deferred.reject(new Error('private owner-a body and bearer'));
    expect(await work).toBeInstanceOf(SessionChangedError);
    expect(test.state()).toBe(nextState);
    expect(console.error).not.toHaveBeenCalled();
  }
);
it.each(cases)('$name sends nothing before credentials exist', async (test) => {
  clearStoredTokens();
  const before = test.state();
  await expect(test.action()).rejects.toBeInstanceOf(SessionChangedError);
  expect(mocks.every((mock) => mock.mock.calls.length === 0)).toBe(true);
  expect(test.state()).toBe(before);
});
it('keeps a current-session order read and creation working', async () => {
  jest.mocked(api.get).mockResolvedValueOnce({ items: [{ id: 'order-a' }], total: 1 });
  await useOrdersStore.getState().fetchOrders();
  expect(useOrdersStore.getState().orders[0].id).toBe('order-a');
  jest.mocked(api.post).mockResolvedValueOnce({ id: 'order-b' });
  const created = await useOrdersStore.getState().createOrder({} as never);
  expect(created.id).toBe('order-b');
  expect(useOrdersStore.getState().orders.map((o) => o.id)).toEqual(['order-b', 'order-a']);
});
it('keeps current-session delivery normalization working through the Axios default export', async () => {
  jest.mocked(client.get).mockResolvedValueOnce({ data: { items: [{ id: 'd' }], total: 1 } });
  await useDeliveriesStore.getState().fetchDeliveries();
  expect(useDeliveriesStore.getState().deliveries[0].id).toBe('d');
  expect(useDeliveriesStore.getState().isLoading).toBe(false);
});
it('keeps current-session riders and earnings reads working', async () => {
  jest.mocked(api.get).mockResolvedValueOnce({ items: [{ id: 'r' }], total: 1 });
  await useRidersStore.getState().fetchRiders();
  expect(useRidersStore.getState().riders[0].id).toBe('r');
  jest.mocked(api.get).mockResolvedValueOnce({ amount: 10 }).mockResolvedValueOnce({ amount: 70 });
  await useRiderPersonalStore.getState().fetchMyEarnings();
  expect(useRiderPersonalStore.getState()).toMatchObject({
    todayEarnings: 10,
    weeklyEarnings: 70,
    isLoading: false,
  });
});
it('keeps a current-session report adaptation and rule update chain working', async () => {
  jest.mocked(api.get).mockResolvedValueOnce({
    totalRevenue: 100,
    totalExpenses: 40,
    netProfit: 60,
    totalRiderPayments: 20,
  });
  expect(await useFinancialStore.getState().getDailySummary('today')).toMatchObject({
    totalRevenue: 100,
    netProfit: 60,
  });
  jest.mocked(api.put).mockResolvedValueOnce({});
  jest.mocked(api.get).mockResolvedValueOnce([{ id: 'rule' }]);
  await useFinancialStore.getState().updatePaymentRule('rule', {});
  expect(useFinancialStore.getState().rules[0].id).toBe('rule');
});
it('does not execute a second read under B after a mutation initiated under A', async () => {
  const deferred = pending();
  jest.mocked(api.post).mockReturnValueOnce(deferred.promise);
  const work = useRidersStore
    .getState()
    .approveRider('r')
    .catch((error) => error);
  storeTokens(replacement);
  deferred.resolve({});
  await work;
  expect(api.get).not.toHaveBeenCalled();
});
it('clears all six stores immediately and preserves their actions', () => {
  useOrdersStore.setState({ orders: [{ id: 'o' } as never], selectedOrder: { id: 'o' } as never });
  useDeliveriesStore.setState({ deliveries: [{ id: 'd' } as never] });
  useRidersStore.setState({ riders: [{ id: 'r' } as never] });
  useRiderPersonalStore.setState({ todayEarnings: 22 });
  useFinancialStore.setState({ transactions: [{ id: 't' } as never] });
  useRealtimeStore.setState({ alerts: [{ id: 'alert' } as never], isConnected: true });
  clearStoredTokens();
  expect(useOrdersStore.getState()).toMatchObject({
    orders: [],
    selectedOrder: null,
    isLoading: false,
  });
  expect(typeof useOrdersStore.getState().fetchOrders).toBe('function');
  expect(useDeliveriesStore.getState().deliveries).toEqual([]);
  expect(useRidersStore.getState().riders).toEqual([]);
  expect(useRiderPersonalStore.getState().todayEarnings).toBe(0);
  expect(useFinancialStore.getState().transactions).toEqual([]);
  expect(useRealtimeStore.getState()).toMatchObject({ alerts: [], isConnected: false });
});

it('a credential change outside authStore clears alerts and invalidates their pending REST result', async () => {
  useNotificationStore.getState().setSession('owner-a');
  const deferred = pending();
  jest.mocked(api.get).mockReturnValueOnce(deferred.promise);
  const work = useNotificationStore.getState().fetchNotifications();
  storeTokens(replacement);
  deferred.resolve([
    { id: 'private-a', title: 'Old owner', description: 'Private', createdAt: '', isRead: false },
  ]);
  await work;
  expect(useNotificationStore.getState()).toMatchObject({
    notifications: [],
    sessionUserId: null,
    unreadCount: 0,
    isLoading: false,
  });
});
