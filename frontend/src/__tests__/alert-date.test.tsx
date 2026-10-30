import AlertPanel from '@/components/alerts/AlertPanel';
import { api } from '@/lib/api';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AlertItem } from '@/components/alerts/AlertItem';
import { alertDate, formatAlertDate } from '@/lib/alert-date';
import type { Alert } from '@/types/alerts';

const sample: Alert = {
  id: 'alert-1', type: 'OTRO', severity: 'ALTA', status: 'ACTIVA',
  title: 'Aviso SLA', message: 'Revisar la entrega', createdAt: new Date('2026-10-30T12:00:00Z'),
  notifiedUsers: [], escalationLevel: 0,
};

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), delete: jest.fn(), post: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());
afterEach(() => jest.useRealTimers());

it.each(['', 'not-a-date', null, undefined, new Date(NaN)])('renders an alert with unknown date %p without crashing or inventing an epoch', (createdAt) => {
  render(<AlertItem alert={{ ...sample, createdAt } as Alert} />);
  expect(screen.getByText('Aviso SLA')).toBeInTheDocument();
  expect(screen.getByText('Fecha no disponible')).toBeInTheDocument();
});

it.each([
  ['2026-10-30T12:00:00', '2026-10-30T12:00:00.000Z'],
  ['2026-10-30T08:00:00-04:00', '2026-10-30T12:00:00.000Z'],
  ['2026-10-30T12:00:00.123456', '2026-10-30T12:00:00.123Z'],
])('interprets %s as the actual server instant, independent of the browser time zone', (value, expected) => {
  expect(alertDate(value)?.toISOString()).toBe(expected);
});

it('keeps relative text in Spanish for a known timestamp', () => {
  jest.useFakeTimers().setSystemTime(new Date('2026-10-30T12:05:00Z'));
  render(<AlertItem alert={sample} />);
  expect(screen.getByText('hace 5 minutos')).toBeInTheDocument();
});

it('keeps read/dismiss actions usable when the date is unknown', () => {
  const read = jest.fn(), dismiss = jest.fn();
  render(<AlertItem alert={{ ...sample, createdAt: new Date(NaN) }} onMarkAsRead={read} onDismiss={dismiss} />);
  fireEvent.click(screen.getByTitle('Marcar como atendida'));
  fireEvent.click(screen.getByTitle('Descartar'));
  expect(read).toHaveBeenCalledWith('alert-1');
  expect(dismiss).toHaveBeenCalledWith('alert-1');
  expect(formatAlertDate(null)).toBe('Fecha no disponible');
});

const rawAlert = {
  id: 'legacy-1', type: 'SLA_WARNING', severity: 'HIGH', status: 'UNREAD',
  title: 'Aviso personal SLA', description: 'Revisar esta entrega', createdAt: '', isRead: false, isDismissed: false,
};

it('the panel uses the real personal read endpoint without claiming an operational resolution', async () => {
  jest.mocked(api.get).mockResolvedValueOnce([rawAlert]).mockResolvedValue([]);
  jest.mocked(api.patch).mockResolvedValue(undefined);
  render(<AlertPanel />);
  expect(await screen.findByText('Aviso personal SLA')).toBeInTheDocument();
  expect(screen.getByText('Alta')).toBeInTheDocument();
  expect(screen.getByText('Fecha no disponible')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/alerts?status=UNREAD&limit=100');
  fireEvent.click(screen.getByTitle('Marcar como leída'));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/alerts/legacy-1/read'));
  await waitFor(() => expect(screen.queryByText('Aviso personal SLA')).not.toBeInTheDocument());
});

it('discard uses DELETE and keeps the row visible after a rejected request', async () => {
  jest.mocked(api.get).mockResolvedValue([rawAlert]);
  jest.mocked(api.delete).mockRejectedValue(new Error('rejected'));
  render(<AlertPanel />);
  await screen.findByText('Aviso personal SLA');
  fireEvent.click(screen.getByTitle('Descartar alerta'));
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo actualizar');
  expect(api.delete).toHaveBeenCalledWith('/alerts/legacy-1');
  expect(screen.getByText('Aviso personal SLA')).toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
});
