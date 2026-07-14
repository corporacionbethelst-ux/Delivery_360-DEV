// Tipos TypeScript para Deliveries - Delivery360
import { Order } from './order';
import { Rider } from './user'; 

/**
 * Enum de estados de entrega para el flujo del repartidor.
 * Define los estados exactos que se usan en la máquina de estados de entregas.
 */
export enum DeliveryStatus {
  INICIADA = 'INICIADA',
  EN_PICKUP = 'EN_PICKUP',
  EN_ROUTE = 'EN_ROUTE',
  COMPLETE = 'COMPLETE',
  FAILED = 'FAILED',
}

/**
 * Tipo legacy para compatibilidad con respuestas antiguas del backend.
 */
export type DeliveryStatusLegacy = 
  | 'PENDIENTE'
  | 'ASIGNADO'
  | 'RECOGIDO'
  | 'EN_CAMINO'
  | 'ENTREGADO'
  | 'FALLIDO'
  | 'CANCELADO';

/**
 * Tipo unificado de estado de entrega.
 */
export type DeliveryStatusType = DeliveryStatus | DeliveryStatusLegacy;

export type DeliveryType = 'STANDARD' | 'EXPRESS' | 'PROGRAMADO' | 'AGENDADO';
export type ProofType = 'FIRMA' | 'FOTO' | 'CODIGO' | 'OTP';

export interface DeliveryLocation {
  latitude: number;
  longitude: number;
  address: string;
  neighborhood: string;
  city: string;
  state: string;
  zipCode: string;
  reference?: string;
}

export interface ProofOfDelivery {
  type: ProofType;
  signatureUrl?: string;
  photoUrls?: string[];
  code?: string;
  otp?: string;
  recipientName?: string;
  recipientPhone?: string;
  notes?: string;
  timestamp: Date;
}

export interface DeliveryEvent {
  id: string;
  deliveryId: string;
  status: DeliveryStatus | DeliveryStatusLegacy;
  timestamp: Date;
  location?: {
    latitude: number;
    longitude: number;
  };
  description: string;
  performedBy?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Interfaz principal de Delivery para el flujo del repartidor.
 * Incluye los campos específicos requeridos para la gestión de estados.
 */
export interface Delivery {
  id: string;
  deliveryNumber?: string;
  
  // Relación con orden
  orderId: string;
  order?: Order;
  
  // Asignación de repartidor
  riderId?: string;
  rider_id?: string;
  rider?: Rider;
  
  // Estado actual (usando el enum DeliveryStatus)
  status: DeliveryStatus | DeliveryStatusLegacy;
  
  // Timestamps específicos del flujo de entrega (nullable)
  created_at?: string | Date | null;
  picked_up_at?: string | Date | null;
  in_route_at?: string | Date | null;
  completed_at?: string | Date | null;
  failed_at?: string | Date | null;
  
  // Motivo de fallo (solo cuando status es FAILED)
  failure_reason?: string | null;
  
  // Campos adicionales para compatibilidad con otras partes del sistema
  type?: DeliveryType;
  priority?: 'NORMAL' | 'ALTA' | 'URGENTE';
  pickupLocation?: DeliveryLocation;
  deliveryLocation?: DeliveryLocation;
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  estimated_delivery_time?: string | Date;
  actualPickupTime?: Date;
  actualDeliveryTime?: Date;
  proofOfDelivery?: ProofOfDelivery;
  events?: DeliveryEvent[];
  observations?: string;
  internalNotes?: string;
  customerInstructions?: string;
  deliveryFee?: number;
  distanceKm?: number;
  durationMinutes?: number;
  createdAt?: Date;
  updatedAt?: Date;
  completedAt?: Date;
  cancelledAt?: Date;
  cancellationReason?: string;
  cancelledBy?: string;
  
  // Coordenadas actuales para tracking en tiempo real
  current_latitude?: number | string | null;
  current_longitude?: number | string | null;
}

export interface DeliveryCreateInput {
  orderId: string;
  type?: DeliveryType;
  priority?: 'NORMAL' | 'ALTA' | 'URGENTE';
  riderId?: string;
  rider_id?: string;
  pickupLocation?: Omit<DeliveryLocation, 'address'> & { address: string };
  deliveryLocation?: Omit<DeliveryLocation, 'address'> & { address: string };
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  estimated_delivery_time?: string | Date;
  observations?: string;
  customerInstructions?: string;
}

export interface DeliveryUpdateInput {
  status?: DeliveryStatus;
  riderId?: string | null;
  estimatedPickupTime?: Date;
  estimatedDeliveryTime?: Date;
  estimated_delivery_time?: string | Date;
  observations?: string;
  internalNotes?: string;
}

export interface DeliveryAssignment {
  deliveryId: string;
  riderId: string;
  assignedBy: string;
  assignedAt: Date;
  acceptedAt?: Date;
  rejectedAt?: Date;
  rejectionReason?: string;
}

export interface DeliveryFilters {
  status?: DeliveryStatus[];
  type?: DeliveryType[];
  riderId?: string;
  rider_id?: string;
  orderId?: string;
  dateFrom?: Date;
  dateTo?: Date;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface DeliveryStats {
  total: number;
  byStatus: Record<DeliveryStatus, number>;
  byType: Record<DeliveryType, number>;
  averageDeliveryTime: number;
  onTimePercentage: number;
  successRate: number;
  totalDistance: number;
  totalRevenue: number;
}

export interface DeliveryRoute {
  deliveryId: string;
  route: Array<{
    latitude: number;
    longitude: number;
    timestamp: Date;
    speed?: number;
  }>;
  totalDistance: number;
  totalDuration: number;
  deviations: Array<{
    timestamp: Date;
    expectedLocation: { latitude: number; longitude: number };
    actualLocation: { latitude: number; longitude: number };
    deviationMeters: number;
  }>;
}
