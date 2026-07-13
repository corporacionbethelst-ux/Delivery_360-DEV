// Tipos TypeScript para Orders - Delivery360
import { User, Rider } from './user';
import type { Delivery } from './delivery';

export type OrderStatus =
  | 'PENDIENTE'
  | 'ASIGNADO'
  | 'CONFIRMADO'
  | 'EN_PREPARACION'
  | 'LISTO_PARA_RECOGER'
  | 'EN_CAMINO'
  | 'ENTREGADO'
  | 'CANCELADO'
  | 'RECHAZADO';

export type OrderPriority = 'BAJA' | 'MEDIA' | 'ALTA' | 'URGENTE';
export type OrderType = 'DOMICILIO' | 'RECOGIDA' | 'PROGRAMADO';

export interface OrderAddress {
  street: string;
  number: string;
  complement?: string;
  neighborhood: string;
  city: string;
  state: string;
  zipCode: string; // Frontend camelCase
  latitude?: number;
  longitude?: number;
  reference?: string;
}

export interface OrderItem {
  id: string;
  name: string;
  description?: string;
  quantity: number;
  unitPrice: number;
  totalPrice: number;
  observations?: string;
}

/**
 * Interfaz principal de Order.
 * Incluye la propiedad opcional delivery para el flujo del repartidor.
 */
export interface Order {
  id: string;
  orderNumber: string;
  status: OrderStatus;
  priority: OrderPriority;
  type: OrderType;

  // Cliente
  customerId: string;
  customer_id?: string;
  customerName: string;
  customer_name?: string;
  customerPhone: string;
  customerEmail?: string;

  // Direcciones
  pickupAddress: OrderAddress;
  deliveryAddress: OrderAddress;

  // Items y valores
  items: OrderItem[];
  subtotal: number;
  deliveryFee: number;
  discount: number;
  total: number;

  // Asignación
  assignedRiderId?: string;
  assignedRider?: Rider;

  // Entrega asociada (para el flujo del repartidor)
  delivery?: Delivery | null;

  // Tiempos
  createdAt: Date;
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  pickedUpAt?: Date;
  deliveredAt?: Date;
  cancelledAt?: Date;
  scheduledAt?: string | Date;

  // Información adicional
  paymentMethod: 'EFECTIVO' | 'TARJETA' | 'PIX' | 'ONLINE' | 'DEBIT_CARD';
  paymentStatus: 'PENDIENTE' | 'PAGADO' | 'REEMBOLSADO';
  observations?: string;
  internalNotes?: string;

  // Tracking
  trackingCode?: string;
  signatureUrl?: string;
  photoProofUrl?: string;

  // Auditoría
  createdBy: string;
  updatedBy?: string;
  cancelledBy?: string;
  cancelReason?: string;
  
  // Campos adicionales para compatibilidad
  restaurant_name?: string;
  restaurant_address?: string;
  restaurant_phone?: string;
}

export interface OrderFilters {
  status?: OrderStatus[];
  priority?: OrderPriority[];
  type?: OrderType[];
  riderId?: string;
  dateFrom?: Date;
  dateTo?: Date;
  search?: string;
  paymentStatus?: 'PENDIENTE' | 'PAGADO' | 'REEMBOLSADO';
}

export interface OrderCreateInput {
  customerName: string;
  customer_name?: string;
  customerPhone: string;
  customerEmail?: string;
  pickupAddress: OrderAddress;
  deliveryAddress: OrderAddress;
  items: Omit<OrderItem, 'id' | 'totalPrice'>[];
  deliveryFee: number;
  discount?: number;
  paymentMethod: Order['paymentMethod'];
  priority?: OrderPriority;
  type?: OrderType;
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  observations?: string;
}

export interface OrderUpdateInput {
  status?: OrderStatus;
  priority?: OrderPriority;
  assignedRiderId?: string | null;
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  observations?: string;
  internalNotes?: string;
}

export interface OrderAssignment {
  orderId: string;
  riderId: string;
  assignedBy: string;
  assignedAt: Date;
  acceptedAt?: Date;
  rejectedAt?: Date;
  rejectionReason?: string;
}

export interface OrderStats {
  total: number;
  byStatus: Record<OrderStatus, number>;
  byPriority: Record<OrderPriority, number>;
  averageDeliveryTime: number;
  onTimePercentage: number;
}
