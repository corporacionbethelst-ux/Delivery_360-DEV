import { useNotificationStore } from '@/stores/notificationStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() } }));
const service = jest.mocked(api);
const alert = (id = 'alert-1') => ({
  id,
  type: 'ORDER',
  title: 'Private alert',
  description: 'Only this account',
  createdAt: '2026-10-27T00:00:00Z',
  isRead: false,
  orderId: 'order-1',
});
const store = () => useNotificationStore.getState();
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  localStorage.clear();
  store().reset();
  jest.clearAllMocks();
  service.get.mockResolvedValue([alert()]);
  service.patch.mockResolvedValue({});
  service.post.mockResolvedValue({});
});
it('does not request or mutate alerts before session verification', async () => {
  await store().fetchNotifications();
  store().markAsRead('x');
  store().markAllAsRead();
  store().addNotification({ type: 'SYSTEM', title: 'x', message: 'private' });
  expect(service.get).not.toHaveBeenCalled();
  expect(service.patch).not.toHaveBeenCalled();
  expect(service.post).not.toHaveBeenCalled();
  expect(store().notifications).toEqual([]);
});
it('loads only memory state and removes the old browser cache', async () => {
  localStorage.setItem(
    'delivery360-notifications-v1',
    JSON.stringify({ state: { notifications: [alert('other-owner')] } })
  );
  localStorage.setItem('theme', 'dark');
  store().setSession('owner-1');
  await store().fetchNotifications();
  expect(store().notifications[0]).toMatchObject({
    id: 'alert-1',
    type: 'OPERATIONAL',
    actionUrl: '/operator/orders/order-1',
  });
  expect(store().unreadCount).toBe(1);
  expect(store().lastFetched).not.toBeNull();
  expect(localStorage.getItem('delivery360-notifications-v1')).toBeNull();
  expect(localStorage.getItem('theme')).toBe('dark');
});
it('reset clears all private state and a pending response cannot repopulate it', async () => {
  store().setSession('owner-1');
  const pending = deferred<unknown>();
  service.get.mockReturnValueOnce(pending.promise);
  const request = store().fetchNotifications();
  expect(store().isLoading).toBe(true);
  store().reset();
  pending.resolve([alert()]);
  await request;
  expect(store()).toMatchObject({
    notifications: [],
    unreadCount: 0,
    lastFetched: null,
    isLoading: false,
    sessionUserId: null,
  });
});
it('a response from owner A cannot overwrite owner B', async () => {
  store().setSession('owner-a');
  const old = deferred<unknown>();
  service.get.mockReturnValueOnce(old.promise);
  const request = store().fetchNotifications();
  store().setSession('owner-b');
  service.get.mockResolvedValueOnce([alert('b')]);
  await store().fetchNotifications();
  old.resolve([alert('a')]);
  await request;
  expect(store().notifications.map((n) => n.id)).toEqual(['b']);
});
it('a late failure cannot clear the loading state of the next request', async () => {
  store().setSession('owner-a');
  const old = deferred<unknown>(),
    next = deferred<unknown>();
  service.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  const a = store().fetchNotifications(),
    b = store().fetchNotifications();
  old.reject(new Error('private URL or token'));
  await a;
  expect(store().isLoading).toBe(true);
  next.resolve([alert('new')]);
  await b;
  expect(store().isLoading).toBe(false);
});
it('the latest request wins even when responses arrive backwards', async () => {
  store().setSession('owner-a');
  const old = deferred<unknown>();
  service.get.mockReturnValueOnce(old.promise);
  const request = store().fetchNotifications();
  service.get.mockResolvedValueOnce([alert('latest')]);
  await store().fetchNotifications();
  old.resolve([alert('old')]);
  await request;
  expect(store().notifications.map((n) => n.id)).toEqual(['latest']);
});
it('keeps unread counts consistent with the displayed 50-item limit', async () => {
  store().setSession('owner');
  service.get.mockResolvedValueOnce(Array.from({ length: 80 }, (_, n) => alert(String(n))));
  await store().fetchNotifications();
  expect(store().notifications).toHaveLength(50);
  expect(store().unreadCount).toBe(50);
});
it('a read mutation fences an older snapshot and encodes the alert ID', async () => {
  store().setSession('owner');
  service.get.mockResolvedValueOnce([alert('id/with spaces')]);
  await store().fetchNotifications();
  const pending = deferred<unknown>();
  service.get.mockReturnValueOnce(pending.promise);
  const request = store().fetchNotifications();
  store().markAsRead('id/with spaces');
  pending.resolve([alert('id/with spaces')]);
  await request;
  expect(store().unreadCount).toBe(0);
  expect(store().notifications[0].read).toBe(true);
  expect(service.patch).toHaveBeenCalledWith('/alerts/id%2Fwith%20spaces/read');
});
it('mark-all and deletion maintain the count without persisting data', async () => {
  store().setSession('owner');
  await store().fetchNotifications();
  store().markAllAsRead();
  expect(store().notifications[0].read).toBe(true);
  expect(service.post).toHaveBeenCalledWith('/alerts/read-all');
  store().deleteNotification('alert-1');
  expect(store().notifications).toEqual([]);
  expect(store().unreadCount).toBe(0);
});
it('failed requests expose no diagnostics or unhandled rejection', async () => {
  const log = jest.spyOn(console, 'error').mockImplementation(() => {});
  store().setSession('owner');
  service.get.mockRejectedValueOnce(new Error('private bearer'));
  await store().fetchNotifications();
  expect(store().isLoading).toBe(false);
  expect(log).not.toHaveBeenCalled();
  log.mockRestore();
});
