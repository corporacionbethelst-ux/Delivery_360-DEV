// Tipos TypeScript para Deliveries - Delivery360
import { Order } from './order';
import { Rider } from './user'; 

/**
 * Enum de estados de entrega para el flujo del repartidor.
 * Define los estados exactos que se usan en la máquina de estados de entregas.
 * Debe coincidir con el enum DeliveryStatus del backend (backend/app/models/delivery.py).
 */
export enum DeliveryStatus {
  PENDIENTE = 'PENDIENTE',
  INICIADA = 'INICIADA',
  EN_PICKUP = 'EN_PICKUP',
  EN_ROUTE = 'EN_ROUTE',
  EN_DESTINO = 'EN_DESTINO',
  COMPLETADA = 'COMPLETADA',
  FALLIDA = 'FALLIDA',
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
 * Incluye los campos específicos requeridos para la gestión de estados, incidencias y métricas.
 * Actualizado para Fase 2 (Bonos por fallo) y Fase 3 (Snapshot Financiero Inmutable).
 */
export interface Delivery {
  id: string;
  deliveryNumber?: string;
  
  // Relación con orden
  orderId: string;
  order?: Order;
  
  // Datos denormalizados de la orden para acceso rápido
  external_id?: string;
  customer_name?: string;
  pickup_address?: string;
  delivery_address?: string;
  
  // Asignación de repartidor
  riderId?: string;
  rider_id?: string;
  rider?: Rider;
  
  // Estado actual (usando el enum DeliveryStatus)
  status: DeliveryStatus | DeliveryStatusLegacy;
  
  // --- TIMELINE DETALLADO (Timestamps específicos del flujo) ---
  created_at?: string | Date | null;
  started_at?: string | Date | null;           // Cuando el rider acepta/inicia
  arrived_pickup_at?: string | Date | null;    // Llegada al restaurante (EN_PICKUP)
  left_pickup_at?: string | Date | null;       // Salida del restaurante (EN_ROUTE)
  arrived_delivery_at?: string | Date | null;  // Llegada al cliente (EN_DESTINO)
  picked_up_at?: string | Date | null;         // Alias para arrived_pickup_at o left_pickup_at según lógica frontend
  in_route_at?: string | Date | null;          // Alias para left_pickup_at
  completed_at?: string | Date | null;
  failed_at?: string | Date | null;
  
  // --- INCIDENCIAS Y FALLOS (FASE 2) ---
  has_issues?: boolean;
  issue_type?: string | null;                  // Motivo del fallo (ej: "cliente_no_esta")
  issue_description?: string | null;           // Descripción detallada
  issue_resolved?: boolean;
  failure_reason?: string | null;              // Alias para issue_type en vistas
  failure_cause?: string | null;               // Causa estandarizada del fallo (ENUM)
  
  // --- PRUEBAS DE ENTREGA ---
  proof_type?: ProofType | string | null;
  proof_photo_url?: string | null;
  proof_signature?: string | null;
  proof_otp?: string | null;
  proof_notes?: string | null;
  customer_name_received?: string | null;
  
  // --- MÉTRICAS Y SLA ---
  distance_total?: number | null;
  distance_pickup?: number | null;
  distance_delivery?: number | null;
  total_time?: number | null;                  // Tiempo total en minutos
  time_to_pickup?: number | null;
  time_at_pickup?: number | null;
  time_to_delivery?: number | null;
  sla_expected_minutes?: number | null;
  sla_actual_minutes?: number | null;
  sla_compliant?: boolean | null;
  
  // --- UBICACIÓN EN TIEMPO REAL ---
  current_latitude?: number | string | null;
  current_longitude?: number | string | null;
  last_location_update?: string | Date | null;
  
  // --- DATOS DE RUTA (Opcional, para navegación avanzada) ---
  route_data?: any | null;

  // =============================================================================
  // FASE 3: SNAPSHOT FINANCIERO INMUTABLE
  // =============================================================================
  // Campos congelados en el momento de finalizar la entrega (COMPLETADA o FALLIDA)
  // Estos valores NUNCA deben cambiar, independientemente de futuras actualizaciones
  // en la configuración de bonos de PlatformSetting.
  
  // Monto exacto del bono congelado en el momento del cierre
  locked_bonus_amount?: number | string | null;
  
  // Tipo de bono aplicado: "SUCCESS" (entrega completada) o "FAILED_ATTEMPT" (fallida bonificable)
  locked_bonus_type?: 'SUCCESS' | 'FAILED_ATTEMPT' | null;
  
  // Fecha y hora exacta en que se congeló el bono
  bonus_snapshot_date?: string | Date | null;
  
  // Mensaje de alerta sobre configuración faltante en el momento del snapshot (para auditoría)
  bonus_config_warning_snapshot?: string | null;

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
  issue_type?: string;
  issue_description?: string;
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