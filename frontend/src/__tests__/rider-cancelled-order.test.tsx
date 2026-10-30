import { render, screen } from '@testing-library/react';
import RiderOrder from '@/app/(dashboard)/rider/my-orders/[id]/page';
import { orderService } from '@/services/order.service';

jest.mock('next/navigation', () => ({ useParams: () => ({ id: 'order-1' }), useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/services/order.service', () => ({ orderService: { getById: jest.fn() } }));
jest.mock('@/services/delivery.service', () => ({ deliveryService: { updateStatus: jest.fn() } }));

it.each([
  ['CANCELADO', 'CANCELADA'],
  ['CANCELADO', 'EN_ROUTE'],
  ['ASIGNADO', 'CANCELADA'],
  ['ASIGNADO', 'CANCELADO'],
])('closes rider actions for order %s / delivery %s, including historical partial records', async (status, deliveryStatus) => {
  jest.mocked(orderService.getById).mockResolvedValue({
    id: 'order-1', status, customer_name: 'Cliente', customer_phone: '123',
    pickup_address: 'Origen', delivery_address: 'Destino',
    cancellation_reason: 'Cliente solicita cancelar su pedido',
    delivery: { id: 'delivery-1', status: deliveryStatus },
  } as any);
  render(<RiderOrder />);
  expect(await screen.findByRole('status')).toHaveTextContent('Las acciones de entrega están cerradas');
  expect(screen.getByText('Motivo: Cliente solicita cancelar su pedido')).toBeInTheDocument();
  expect(screen.queryByText('Acciones de Entrega')).not.toBeInTheDocument();
  expect(screen.getByText(/Cancelada: sin bono de entrega/)).toBeInTheDocument();
});
