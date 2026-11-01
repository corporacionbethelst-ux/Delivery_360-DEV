import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import OrderCard from '@/components/orders/OrderCard';
import { OrderDetailPanel } from '@/components/orders/OrderDetailPanel';
import { RecentOrdersTable } from '@/components/dashboard/RecentOrdersTable';
import AssignRiderModal from '@/components/orders/AssignRiderModal';
import { orderView } from '@/lib/order-view';
import { ORDER_STATUSES } from '@/lib/operational-catalog';
import { DeliveryStatus } from '@/types/delivery';

jest.mock('@/stores/ridersStore', () => ({ useRidersStore: () => ({ riders: [], fetchRiders: mockFetch, isLoading: false }) }));
const mockFetch = jest.fn().mockResolvedValue(undefined);
const pending = orderView({ id: 'o', status: 'PENDIENTE', pickup_address: 'Origen', delivery_address: 'Destino' });
it.each(ORDER_STATUSES)('represents the canonical state %s consistently in card, detail and table', status => {
  const order = { ...pending, status };
  const { container } = render(<><OrderCard order={order} showActions /><OrderDetailPanel order={order} /><RecentOrdersTable orders={[order]} /></>);
  const expected: Record<string, string> = { PENDIENTE: 'Pendiente', ASIGNADO: 'Asignado', EN_RECOLECCION: 'En recolección', RECOLECTADO: 'Recolectado', EN_RUTA: 'En ruta', ENTREGADO: 'Entregado', FALLIDO: 'Fallido', CANCELADO: 'Cancelado' };
  expect(screen.getAllByText(expected[status])).toHaveLength(3);
  expect(screen.queryAllByRole('button', { name: /Asignar repartidor/i })).toHaveLength(status === 'PENDIENTE' ? 3 : 0);
  expect(container).not.toHaveTextContent('Invalid Date');
});
it.each(['assignedRiderId', 'delivery'])('blocks assignment with an existing assignment even without a rider summary: %s', source => {
  const order = { ...pending, ...(source === 'assignedRiderId' ? { assignedRiderId: 'r' } : { delivery: { id: 'd', orderId: pending.id, riderId: 'r', status: DeliveryStatus.INICIADA } }) };
  render(<><OrderCard order={order} showActions /><OrderDetailPanel order={order} /><RecentOrdersTable orders={[order]} /><AssignRiderModal order={order} onAssign={jest.fn()} onClose={jest.fn()} /></>);
  expect(screen.queryAllByRole('button', { name: /^Asignar repartidor$/i })).toHaveLength(0);
  expect(screen.getByRole('button', { name: 'Ya Asignado' })).toBeDisabled();
});
it('shows unknown amounts, quantity, payment and dates without defaulting to cash or zero', () => {
  const { container } = render(<><OrderCard order={pending} /><OrderDetailPanel order={pending} /></>);
  expect(screen.getByText('Cantidad no informada')).toBeInTheDocument();
  expect(screen.getByText('Artículos no informados')).toBeInTheDocument();
  expect(screen.getByText('Estado de pago no informado')).toBeInTheDocument();
  expect(container).not.toHaveTextContent('Efectivo'); expect(container).not.toHaveTextContent('0 items');
  expect(screen.getAllByText(/Método no informado/)).toHaveLength(2);
});
it('keeps zero totals and empty items distinct from missing values in all amount views', () => {
  const order = orderView({ id: 'free', status: 'PENDIENTE', total: 0, total_amount: 99, items: [], subtotal: 0, delivery_fee: 0 });
  const { container } = render(<><OrderCard order={order} /><OrderDetailPanel order={order} /><AssignRiderModal order={order} onAssign={jest.fn()} onClose={jest.fn()} /></>);
  expect(screen.getByText('0 items')).toBeInTheDocument(); expect(screen.getByText('Sin artículos')).toBeInTheDocument();
  expect(container).not.toHaveTextContent('99');
  expect(screen.queryByText('Artículos no informados')).not.toBeInTheDocument();
});
it('includes pickup stages in the active table filter and excludes failed/terminal orders', () => {
  const rows = ORDER_STATUSES.map(status => ({ ...pending, id: status, status }));
  render(<RecentOrdersTable orders={rows} />);
  fireEvent.click(screen.getByRole('button', { name: 'Activos' }));
  for (const status of ['Asignado', 'En recolección', 'Recolectado', 'En ruta']) expect(screen.getByText(status)).toBeInTheDocument();
  expect(screen.queryByText('Entregado')).not.toBeInTheDocument(); expect(screen.queryByText('Fallido')).not.toBeInTheDocument();
});
