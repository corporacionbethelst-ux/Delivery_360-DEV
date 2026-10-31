import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Modal from '@/components/orders/AssignRiderModal';
import type { Order } from '@/types/order';
import type { Rider } from '@/types/user';

const mockFetch = jest.fn();
let mockState: { riders: Rider[]; isLoading: boolean; fetchRiders: typeof mockFetch };
jest.mock('@/stores/ridersStore', () => ({ useRidersStore: () => mockState }));

const rider = {
  id: 'rider-1', first_name: 'Ana', last_name: 'Pérez', phone: '123', cpf: '123456',
  status: 'ACTIVO', is_online: true, vehicle_type: 'MOTO', vehicle_plate: 'ABC',
  operating_zone: 'Centro', level: 2,
} as Rider;
const order = {
  id: 'order-1', orderNumber: 'ORD-1', customerName: 'Cliente', customerPhone: '555',
  status: 'PENDIENTE', priority: 'ALTA', total: 12,
  deliveryAddress: { street: 'Destino', number: '2', neighborhood: 'Centro' },
} as Order;
beforeEach(() => {
  jest.clearAllMocks();
  mockFetch.mockReset();
  mockState = { riders: [rider], isLoading: false, fetchRiders: mockFetch };
});
const props = () => ({ order, onClose: jest.fn(), onAssign: jest.fn() });

it('loads active candidates and hides offline or suspended rows', () => {
  mockState.riders.push({ ...rider, id: 'offline', first_name: 'Offline', is_online: false });
  mockState.riders.push({ ...rider, id: 'suspended', first_name: 'Suspendido', status: 'SUSPENDIDO' });
  render(<Modal {...props()} />);
  expect(mockFetch).toHaveBeenCalledWith({ status: ['ACTIVO'] });
  expect(screen.getByText('1 repartidores disponibles')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Seleccionar a Offline/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Seleccionar a Suspendido/ })).not.toBeInTheDocument();
});

it('requires an explicit current selection before assignment', async () => {
  const p = props();
  render(<Modal {...p} />);
  const save = screen.getByRole('button', { name: 'Asignar Orden' });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  expect(save).toBeEnabled();
  await act(async () => { fireEvent.click(save); });
  expect(p.onAssign).toHaveBeenCalledWith('rider-1');
});

it.each(['Enter', ' '])('supports candidate selection with keyboard %s', async key => {
  const p = props();
  render(<Modal {...p} />);
  fireEvent.keyDown(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }), { key });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' })); });
  expect(p.onAssign).toHaveBeenCalledWith('rider-1');
});

it.each(['removed', 'offline', 'suspended', 'loading'])('blocks a stale selection when the live list changes: %s', change => {
  const p = props();
  const { rerender } = render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  if (change === 'removed') mockState.riders = [];
  if (change === 'offline') mockState.riders = [{ ...rider, is_online: false }];
  if (change === 'suspended') mockState.riders = [{ ...rider, status: 'SUSPENDIDO' }];
  if (change === 'loading') mockState.isLoading = true;
  rerender(<Modal {...p} />);
  const save = screen.getByRole('button', { name: 'Asignar Orden' });
  expect(save).toBeDisabled();
  fireEvent.click(save);
  expect(p.onAssign).not.toHaveBeenCalled();
});

it('blocks the selected candidate when the order becomes terminal', () => {
  const p = props();
  const { rerender } = render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  rerender(<Modal {...p} order={{ ...order, status: 'CANCELADO' }} />);
  expect(screen.getByRole('button', { name: 'Pedido no asignable' })).toBeDisabled();
  expect(p.onAssign).not.toHaveBeenCalled();
});

it('searches name and document and can clear an empty result', () => {
  render(<Modal {...props()} />);
  const search = screen.getByLabelText('Buscar Repartidor');
  fireEvent.change(search, { target: { value: '123456' } });
  expect(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' })).toBeInTheDocument();
  fireEvent.change(search, { target: { value: 'Not here' } });
  expect(screen.getByText('No hay repartidores disponibles')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Limpiar búsqueda' }));
  expect(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' })).toBeInTheDocument();
});

it('preserves the assigned-order guard and exposes close controls', () => {
  const p = props();
  render(<Modal {...p} order={{ ...order, assignedRiderId: rider.id, assignedRider: rider }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  expect(screen.getByRole('button', { name: 'Ya Asignado' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar asignación' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
  expect(p.onClose).toHaveBeenCalledTimes(2);
  expect(p.onAssign).not.toHaveBeenCalled();
});

it('keeps confirmation and close controls locked until the assignment finishes', async () => {
  let resolve!: () => void;
  const p = { ...props(), onAssign: jest.fn(() => new Promise<void>(done => { resolve = done; })) };
  render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' }));
  fireEvent.click(screen.getByRole('button', { name: 'Asignando...' }));
  fireEvent.keyDown(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }), { key: 'Enter' });
  expect(p.onAssign).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();
  await act(async () => { resolve(); });
  expect(screen.getByRole('button', { name: 'Cerrar asignación' })).toBeEnabled();
});

it('keeps the form open on rejection and permits an explicit retry', async () => {
  const p = { ...props(), onAssign: jest.fn().mockRejectedValueOnce(new Error('refused')).mockResolvedValueOnce(undefined) };
  render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' }));
  await screen.findByRole('alert');
  expect(p.onClose).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Asignar Orden' })).toBeEnabled();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' })); });
  expect(p.onAssign).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('contains a synchronous assignment exception without claiming success', async () => {
  const p = { ...props(), onAssign: jest.fn(() => { throw new Error('Unavailable'); }) };
  render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' })); });
  expect(screen.getByRole('alert')).toHaveTextContent('No se pudo confirmar');
  expect(p.onClose).not.toHaveBeenCalled();
});

it('can unmount while an assignment settles without calling close again', async () => {
  let resolve!: () => void;
  const p = { ...props(), onAssign: jest.fn(() => new Promise<void>(done => { resolve = done; })) };
  const { unmount } = render(<Modal {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  fireEvent.click(screen.getByRole('button', { name: 'Asignar Orden' }));
  unmount();
  await act(async () => { resolve(); });
  expect(p.onClose).not.toHaveBeenCalled();
});

it('contains a failed rider read, blocks stale confirmation and permits reloading', async () => {
  mockFetch.mockRejectedValueOnce(new Error('Read failed')).mockResolvedValueOnce(undefined);
  render(<Modal {...props()} />);
  await screen.findByRole('status');
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar a Ana Pérez' }));
  expect(screen.getByRole('button', { name: 'Asignar Orden' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Volver a cargar repartidores' }));
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(mockFetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: 'Asignar Orden' })).toBeEnabled();
});

it('contains a rider read that fails after the form unmounts', async () => {
  let reject!: (error: Error) => void;
  mockFetch.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  const p = props();
  const { unmount } = render(<Modal {...p} />);
  unmount();
  await act(async () => { reject(new Error('Late read failure')); });
  expect(p.onClose).not.toHaveBeenCalled();
  expect(p.onAssign).not.toHaveBeenCalled();
});
