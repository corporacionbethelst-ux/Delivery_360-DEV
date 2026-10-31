import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import List from '@/components/orders/OrderList';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { useOrdersStore } from '@/stores/ordersStore';
import { useRidersStore } from '@/stores/ridersStore';
import type { Order } from '@/types/order';
import type { Rider } from '@/types/user';
import sample from './fixtures/order-assignment-response.json';

jest.mock('@/lib/api', () => ({ api: { patch: jest.fn(), get: jest.fn() } }));
jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => <select value={value} onChange={event => onValueChange(event.target.value)}>{children}</select>,
  SelectTrigger: () => null, SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ children, value }: any) => <option value={value}>{children}</option>,
}));
const order: Order = {
  id: sample.id, orderNumber: 'TEST-001', status: 'PENDIENTE', priority: 'ALTA',
  customerName: 'Visible Customer', customerPhone: '123', total: 0, items: [],
  type: 'DOMICILIO', customerId: 'test-customer', subtotal: 0, deliveryFee: 0, discount: 0, createdBy: 'test-staff',
  pickupAddress: { street: 'Origin Avenue', number: '1', neighborhood: 'Origin', city: 'Test', state: 'Test', zipCode: '000' },
  deliveryAddress: { street: 'Destination', number: '2', neighborhood: 'Centro', city: 'Test', state: 'Test', zipCode: '000' },
  paymentMethod: 'EFECTIVO', paymentStatus: 'PENDIENTE', createdAt: new Date('2026-10-31T12:00:00Z'),
};
beforeEach(() => {
  jest.clearAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'ui-test-a', refresh_token: 'ui-refresh-a' });
  jest.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
  useOrdersStore.getState().setOrders([order]);
  const rider: Rider = { ...sample.assigned_rider, vehicle_plate: sample.assigned_rider.vehicle_plate ?? undefined,
    role: 'REPARTIDOR', is_active: true, created_at: '2026-10-31T12:00:00Z', updated_at: '2026-10-31T12:00:00Z',
    status: 'ACTIVO', is_online: true };
  useRidersStore.setState({ riders: [rider],
    isLoading: false, fetchRiders: jest.fn() });
});
afterEach(() => { clearStoredTokens(); });
function choose() {
  fireEvent.click(screen.getByRole('button', { name: 'Asignar Repartidor' }));
  fireEvent.click(screen.getByRole('button', { name: `Seleccionar a ${sample.assigned_rider.full_name}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' }));
}

it.each(['store', 'props'])('confirms through the real store/API action before closing (%s)', async source => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.patch).mockReturnValue(new Promise(done => { resolve = done; }));
  render(<List showActions orders={source === 'props' ? [order] : undefined} />);
  choose();
  expect(api.patch).toHaveBeenCalledWith(`/orders/${sample.id}/assign`, { rider_id: sample.assigned_rider_id });
  expect(screen.getByRole('button', { name: 'Asignando...' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeDisabled();
  await act(async () => { resolve(sample); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Cerrar asignación' })).not.toBeInTheDocument());
  expect(screen.getByText(sample.assigned_rider.full_name)).toBeInTheDocument();
  expect(screen.getByText('Asignado', { selector: ':not(option)' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Asignar Repartidor' })).not.toBeInTheDocument();
});

it('keeps the same order and form visible when the server refuses, then accepts a deliberate retry', async () => {
  jest.mocked(api.patch).mockRejectedValueOnce(new Error('Documentos pendientes')).mockResolvedValueOnce(sample);
  render(<List showActions />);
  choose();
  await screen.findByRole('alert');
  expect(useOrdersStore.getState().orders[0].status).toBe('PENDIENTE');
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' })); });
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(api.patch).toHaveBeenCalledTimes(2);
  expect(useOrdersStore.getState().orders[0].status).toBe('ASIGNADO');
});

it('does not close on a mismatched HTTP success response', async () => {
  jest.mocked(api.patch).mockResolvedValue({ ...sample, assigned_rider_id: 'someone-else' });
  render(<List showActions />);
  choose();
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeEnabled();
  expect(useOrdersStore.getState().orders[0].status).toBe('PENDIENTE');
});

it('lets a new caller-owned order object supersede the local assignment confirmation', async () => {
  jest.mocked(api.patch).mockResolvedValue(sample);
  const { rerender } = render(<List showActions orders={[order]} />);
  choose();
  await waitFor(() => expect(screen.getByText('Asignado', { selector: ':not(option)' })).toBeInTheDocument());
  rerender(<List showActions orders={[{ ...order, status: 'CANCELADO' }]} />);
  expect(screen.getByText('Cancelado', { selector: ':not(option)' })).toBeInTheDocument();
  expect(screen.queryByText(sample.assigned_rider.full_name)).not.toBeInTheDocument();
});

it.each(['TEST-001', 'visible customer', 'origin avenue'])('keeps searching by real order information (%s)', search => {
  render(<List />);
  fireEvent.change(screen.getByPlaceholderText('Buscar por ID, cliente o dirección...'), { target: { value: search } });
  expect(screen.getByText('#TEST-001')).toBeInTheDocument();
});

it('supports empty search recovery and status/priority filters without assigning', () => {
  render(<List />);
  fireEvent.change(screen.getByPlaceholderText('Buscar por ID, cliente o dirección...'), { target: { value: 'No such order' } });
  expect(screen.getByText('No se encontraron órdenes')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
  expect(screen.getByText('#TEST-001')).toBeInTheDocument();
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'CANCELADO' } });
  expect(screen.getByText('No se encontraron órdenes')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar' }));
  fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'URGENTE' } });
  expect(screen.getByText('No se encontraron órdenes')).toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
});

it('can display caller-owned orders without action or filter controls', () => {
  const select = jest.fn();
  render(<List orders={[order]} showFilters={false} onOrderSelect={select} compact />);
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Asignar Repartidor' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('#TEST-001'));
  expect(select).toHaveBeenCalledWith(order);
  expect(api.patch).not.toHaveBeenCalled();
});

it('fences the parent continuation after the store finishes under a different account', async () => {
  jest.mocked(api.patch).mockResolvedValue(sample);
  const assign = useOrdersStore.getState().assignRider;
  useOrdersStore.setState({ assignRider: async (...args) => {
    const confirmed = await assign(...args);
    // The store completed correctly under A. The parent must recheck after await.
    storeTokens({ access_token: 'ui-test-b', refresh_token: 'ui-refresh-b' });
    return confirmed;
  } });
  render(<List showActions orders={[order]} />);
  choose();
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeEnabled();
  expect(screen.queryByText(sample.assigned_rider.full_name)).not.toBeInTheDocument();
  expect(useOrdersStore.getState().orders).toEqual([]);
});
