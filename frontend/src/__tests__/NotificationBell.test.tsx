import '@testing-library/jest-dom';
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NotificationBell } from '@/components/layout/NotificationBell';
import type { useNotificationStore } from '@/stores/notificationStore';
import type { useNotifications } from '@/hooks/useNotifications';

const mockFetchNotifications = jest.fn<Promise<void>, []>().mockResolvedValue(undefined);
const mockMarkAsRead = jest.fn();
const mockMarkAllAsRead = jest.fn();
const mockMarkRead = jest.fn<Promise<void>, [string]>().mockResolvedValue(undefined);
let mockLegacyState: Pick<ReturnType<typeof useNotificationStore.getState>, 'notifications' | 'unreadCount' | 'fetchNotifications' | 'markAsRead' | 'markAllAsRead'>;
let mockOmnichannelState: Pick<ReturnType<typeof useNotifications>, 'items' | 'unreadCount' | 'markRead'>;

jest.mock('@/stores/notificationStore', () => ({
  useNotificationStore: () => mockLegacyState,
}));

jest.mock('@/hooks/useNotifications', () => ({
  useNotifications: () => mockOmnichannelState,
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockLegacyState = {
    notifications: [], unreadCount: 0,
    fetchNotifications: mockFetchNotifications,
    markAsRead: mockMarkAsRead, markAllAsRead: mockMarkAllAsRead,
  };
  mockOmnichannelState = { items: [], unreadCount: 0, markRead: mockMarkRead };
});

test('fetches an empty legacy inbox only after opening the bell', async () => {
  const user = userEvent.setup();
  render(<NotificationBell />);
  expect(mockFetchNotifications).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button'));
  expect(screen.getByText('No hay notificaciones nuevas')).toBeInTheDocument();
  expect(mockFetchNotifications).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole('button'));
  expect(mockFetchNotifications).toHaveBeenCalledTimes(1);
});

test('preserves legacy notification and mark-all actions', async () => {
  mockLegacyState.notifications = [{
    id: 'legacy-1', type: 'ORDER', read: false, title: 'Pedido asignado',
    message: 'Recoge el pedido', createdAt: new Date().toISOString(),
  }];
  mockLegacyState.unreadCount = 1;
  const user = userEvent.setup();
  render(<NotificationBell />);
  await user.click(screen.getByRole('button'));
  await user.click(screen.getByText('Pedido asignado'));
  expect(mockMarkAsRead).toHaveBeenCalledWith('legacy-1');
  await user.click(screen.getByRole('button', { name: /Marcar todas/ }));
  expect(mockMarkAllAsRead).toHaveBeenCalledTimes(1);
  expect(mockFetchNotifications).not.toHaveBeenCalled();
});

test('marks an unread omnichannel message and exposes the inbox link', async () => {
  mockOmnichannelState.items = [{
    id: 'omni-1', title: 'Retiro aprobado', body: 'Tu retiro está en proceso',
    status: 'PENDIENTE', channel: 'IN_APP', created_at: new Date().toISOString(),
  }];
  mockOmnichannelState.unreadCount = 2;
  const user = userEvent.setup();
  render(<NotificationBell />);
  await user.click(screen.getByRole('button'));
  expect(screen.getByText('2')).toBeInTheDocument();
  await user.click(screen.getByText('Retiro aprobado'));
  expect(mockMarkRead).toHaveBeenCalledWith('omni-1');
  expect(screen.getByRole('link', { name: 'Ver inbox completo' })).toHaveAttribute('href', '/notifications');
});
