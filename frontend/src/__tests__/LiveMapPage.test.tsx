import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/operations/live-map/MapPageContent';
import { useAuthStore } from '@/stores/authStore';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { riderService } from '@/services/rider.service';
import { orderService } from '@/services/order.service';
import { trackingService } from '@/services/tracking.service';
import { credentials, profile } from '../../test-utils/realtime';
jest.mock('@/services/rider.service', () => ({ riderService: { getAll: jest.fn() } }));
jest.mock('@/services/order.service', () => ({ orderService: { getAll: jest.fn() } }));
jest.mock('@/services/tracking.service', () => ({
  trackingService: { getActiveRiders: jest.fn() },
}));
jest.mock('@/hooks/useTrackingWebSocket', () => ({
  useTrackingWebSocket: () => ({
    positions: [{ riderId: 'r', lat: 2, lng: 2, timestamp: '2026-10-27T10:00:00Z' }],
    isConnected: true,
    latencyMs: 1,
    error: null,
    reconnect: jest.fn(),
  }),
}));
jest.mock('next/dynamic', () => () => () => null);
jest.mock('@/components/maps/DeliveryMap', () => ({
  DeliveryMap: ({ riders }: { riders: Array<{ lat: number }> }) => (
    <div data-testid="map-latitude">{riders.map((r) => r.lat).join(',')}</div>
  ),
}));
const row = (lat: number, timestamp: string) => ({
  id: 'r',
  first_name: 'Test',
  last_name: 'Rider',
  last_lat: lat,
  last_lng: lat,
  last_location_at: timestamp,
  is_online: true,
});
beforeEach(() => {
  localStorage.clear();
  storeTokens(credentials);
  useAuthStore.setState({ user: profile, isAuthenticated: true, sessionRevision: 1 });
  jest
    .mocked(riderService.getAll)
    .mockReset()
    .mockResolvedValue([row(1, '2026-10-27T09:00:00Z')] as never);
  jest.mocked(orderService.getAll).mockReset().mockResolvedValue([]);
  jest
    .mocked(trackingService.getActiveRiders)
    .mockReset()
    .mockResolvedValue({
      riders: [],
      alerts: [],
      stats: { activeCount: 1, onlineTotal: 1, staleOver15Min: 0, avgWaitMinutes: null },
    });
});
afterEach(() => {
  cleanup();
  clearStoredTokens();
});
it('renders the most recent source after manual REST refreshes instead of rewinding its live point', async () => {
  render(<Page />);
  expect(await screen.findByTestId('map-latitude')).toHaveTextContent('2');
  jest
    .mocked(riderService.getAll)
    .mockResolvedValueOnce([row(1.5, '2026-10-27T09:30:00Z')] as never);
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  await waitFor(() => expect(screen.getByRole('button', { name: /actualizar/i })).toBeEnabled());
  expect(screen.getByTestId('map-latitude')).toHaveTextContent('2');
  jest.mocked(riderService.getAll).mockResolvedValueOnce([row(3, '2026-10-27T11:00:00Z')] as never);
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  await waitFor(() => expect(screen.getByTestId('map-latitude')).toHaveTextContent('3'));
});
it('shows a generic refresh error and retains the last completed map', async () => {
  render(<Page />);
  await screen.findByTestId('map-latitude');
  jest.mocked(riderService.getAll).mockRejectedValueOnce(new Error('private bearer and URL'));
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo actualizar el mapa');
  expect(screen.getByRole('alert')).not.toHaveTextContent('bearer');
  expect(screen.getByTestId('map-latitude')).toHaveTextContent('2');
});

it('hides retained WS positions after REST denies access until a complete authorized read succeeds', async () => {
  render(<Page />);
  expect(await screen.findByTestId('map-latitude')).toHaveTextContent('2');
  jest
    .mocked(riderService.getAll)
    .mockRejectedValueOnce(Object.assign(new Error('private forbidden response'), { status: 403 }));
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Verifica tu sesión y permisos');
  expect(screen.getByTestId('map-latitude')).toBeEmptyDOMElement();
  jest.mocked(riderService.getAll).mockRejectedValueOnce(new Error('network unavailable'));
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  await waitFor(() => expect(screen.getByRole('button', { name: /actualizar/i })).toBeEnabled());
  expect(screen.getByTestId('map-latitude')).toBeEmptyDOMElement();
  jest.mocked(riderService.getAll).mockResolvedValueOnce([row(3, '2026-10-27T11:00:00Z')] as never);
  fireEvent.click(screen.getByRole('button', { name: /actualizar/i }));
  await waitFor(() => expect(screen.getByTestId('map-latitude')).toHaveTextContent('3'));
});
