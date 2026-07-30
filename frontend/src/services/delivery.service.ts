import { api } from '@/lib/api';
import type { Delivery, DeliveryStatus } from '@/types/delivery';
import { isAxiosError } from 'axios';

// Usamos string union para ser flexibles con el filtro
export type DeliveryStatusFilter = 'PENDIENTE' | 'INICIADA' | 'EN_ROUTE' | 'EN_RUTA' | 'COMPLETADA' | 'INCIDENCIA' | 'FALLIDA' | 'EN_PICKUP' | 'EN_DESTINO';

// Nuevos tipos para las causas de falla estandarizadas
export type FailureCause = 
  | 'CLIENTE_NO_ESTA'
  | 'CLIENTE_NO_CONTESTA'
  | 'DIRECCION_INCORRECTA'
  | 'DIRECCION_NO_EXISTE'
  | 'COMERCIO_CERRADO'
  | 'CLIENTE_RECHAZA'
  | 'ZONA_INSEGURA'
  | 'FUERZA_MAYOR'
  | 'EDIFICIO_RESTRINGIDO'
  | 'REPARTIDOR_NO_QUIERE_ENTREGAR'
  | 'REPARTIDOR_LLEGO_TARDE'
  | 'REPARTIDOR_ERROR_PROPIO'
  | 'REPARTIDOR_VEHICULO_FALLA'
  | 'REPARTIDOR_SIN_BATERIA'
  | 'OTRO_REPARTIDOR';

export interface RiderInfo {
  id: string;
  first_name: string;
  last_name: string;
  vehicle_type?: string | null;
}

export interface DeliveryProofInput {
  otp_code?: string;
  delivery_lat?: number;
  delivery_lng?: number;
  customer_rating?: number;
  notes?: string;
}

export interface DeliveryLocationInput {
  latitude: number;
  longitude: number;
}

export interface DeliveryFilters {
  rider_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
  include_total?: boolean;
}

export interface DeliveryListResponse {
  items: Delivery[];
  total: number;
  limit?: number;
  offset?: number;
}

/**
 * Payload para actualizar el estado de una entrega.
 * Soporta tanto el flujo legacy (issue_type) como el nuevo (failure_cause).
 */
export interface UpdateStatusPayload {
  status: string;
  issue_type?: string;
  issue_description?: string;
  failure_cause?: FailureCause;
}

export const deliveryService = {
  /**
   * Listar entregas con filtros, paginación y offset.
   */
  getAll: async (params?: Readonly<DeliveryFilters>): Promise<DeliveryListResponse> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.rider_id) queryParams.append('rider_id', params.rider_id);
      if (params?.status) queryParams.append('status', params.status);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.offset) queryParams.append('offset', String(params.offset));
      if (params?.include_total) queryParams.append('include_total', 'true');

      const query = queryParams.toString() ? `?${queryParams}` : '';
      const response = await api.get<DeliveryListResponse>(`/deliveries${query}`);
      
      return response;
    } catch (error) {
      console.error('[DeliveryService] Error fetching deliveries:', error);
      throw error;
    }
  },

  /**
   * Listar entregas con total real del backend para paginación estable.
   */
  getPage: async (params?: Readonly<DeliveryFilters>): Promise<DeliveryListResponse> => {
    try {
      const queryParams = new URLSearchParams();

      if (params?.rider_id) queryParams.append('rider_id', params.rider_id);
      if (params?.status) queryParams.append('status', params.status);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.offset) queryParams.append('offset', String(params.offset));
      queryParams.append('include_total', 'true');

      const query = queryParams.toString() ? `?${queryParams}` : '';
      const response = await api.get<Delivery[] | DeliveryListResponse>(`/deliveries${query}`);

      if (Array.isArray(response)) {
        return {
          items: response,
          total: response.length,
          limit: params?.limit ?? response.length,
          offset: params?.offset ?? 0,
        };
      }

      return response;
    } catch (error) {
      console.error('[DeliveryService] Error fetching paginated deliveries:', error);
      throw error;
    }
  },

  getById: async (id: string): Promise<Delivery> => {
    if (!id || typeof id !== 'string') {
      throw new Error('[DeliveryService] ID de entrega inválido');
    }
    try {
      return await api.get<Delivery>(`/deliveries/${id}`);
    } catch (error) {
      console.error(`[DeliveryService] Error fetching delivery ${id}:`, error);
      throw error;
    }
  },

  getByOrderId: async (orderId: string): Promise<Delivery | null> => {
    if (!orderId) {
      throw new Error('[DeliveryService] Order ID requerido');
    }
    try {
      const response = await api.get<Delivery[]>(`/deliveries?order_id=${orderId}&limit=1`);
      const items = Array.isArray(response) ? response : (response as DeliveryListResponse).items || [];
      return items.length > 0 ? items[0] : null;
    } catch (error) {
      console.error(`[DeliveryService] Error fetching delivery for order ${orderId}:`, error);
      return null;
    }
  },

  updateStatus: async (id: string | number, payload: UpdateStatusPayload): Promise<Delivery> => {
    if (!id) {
      throw new Error('[DeliveryService] ID de entrega requerido');
    }
    if (!payload.status) {
      throw new Error('[DeliveryService] Estado nuevo requerido');
    }
    try {
      const deliveryId = String(id);
      return await api.patch<Delivery>(`/deliveries/${deliveryId}/status`, payload);
    } catch (error: unknown) {
      console.error('[DeliveryService] Error updating status:', error);
      const axiosError = isAxiosError(error) ? error : null;
      throw new Error(axiosError?.response?.data?.detail || 'No se pudo actualizar el estado de la entrega');
    }
  },

  start: async (orderId: string): Promise<{ otp_code: string; message: string }> => {
    if (!orderId) throw new Error('[DeliveryService] Order ID requerido');
    try {
      return await api.post<{ otp_code: string; message: string }>(`/deliveries/${orderId}/start`);
    } catch (error: unknown) {
      const axiosError = isAxiosError(error) ? error : null;
      throw new Error(axiosError?.response?.data?.detail || 'No se pudo iniciar la entrega');
    }
  },

  complete: async (id: string, proof: DeliveryProofInput): Promise<Delivery> => {
    if (!id) throw new Error('[DeliveryService] ID requerido');
    try {
      return await api.post<Delivery>(`/deliveries/${id}/complete`, proof);
    } catch (error: unknown) {
      const axiosError = isAxiosError(error) ? error : null;
      throw new Error(axiosError?.response?.data?.detail || 'Error al completar');
    }
  },

  updateLocation: async (id: string, lat: number, lng: number): Promise<void> => {
    if (!id) throw new Error('[DeliveryService] ID requerido');
    try {
      await api.patch(`/deliveries/${id}/location`, { 
        lat,
        lng,
        latitude: lat,
        longitude: lng,
      });
    } catch (error: unknown) {
      console.error('[DeliveryService] Error updating location:', error);
      const axiosError = isAxiosError(error) ? error : null;
      throw new Error(axiosError?.response?.data?.detail || 'No se pudo actualizar la ubicación');
    }
  },

  /**
   * Reportar una entrega como fallida usando el sistema estandarizado de causas.
   * @param id - ID de la entrega
   * @param failure_cause - Valor del ENUM (ej: "CLIENTE_NO_ESTA")
   * @param notes - (Opcional) Notas adicionales del repartidor
   */
  failDelivery: async (
    id: string, 
    failure_cause: FailureCause, 
    notes?: string
  ): Promise<Delivery & { bonus_applied?: boolean; bonus_amount?: number; issue_analysis?: any }> => {
    if (!id) throw new Error('[DeliveryService] ID de entrega requerido');
    if (!failure_cause) throw new Error('[DeliveryService] Causa de falla requerida');
    
    try {
      // Enviamos failure_cause como campo principal. 
      // El backend puede usar notes como descripción secundaria si lo soporta.
      const payload: any = { failure_cause };
      if (notes && notes.trim()) {
        payload.issue_description = notes;
      }

      return await api.post<Delivery & { bonus_applied?: boolean; bonus_amount?: number; issue_analysis?: any }>(
        `/deliveries/${id}/fail`, 
        payload
      );
    } catch (error: unknown) {
      console.error('[DeliveryService] Error reporting failed delivery:', error);
      const axiosError = isAxiosError(error) ? error : null;
      throw new Error(axiosError?.response?.data?.detail || 'No se pudo reportar la entrega fallida');
    }
  },

  getActiveTracking: async (): Promise<Delivery[]> => {
     try {
       const response = await api.get<Delivery[] | DeliveryListResponse>('/deliveries?status=EN_ROUTE&limit=100&include_total=true');
       
       if (Array.isArray(response)) return response;
       return response.items || [];
     } catch (error) {
       console.error('[DeliveryService] Error fetching active tracking:', error);
       throw error;
     }
  },
  
  getLiveTracking: async (): Promise<Delivery[]> => {
    try {
      const response = await api.get<Delivery[] | DeliveryListResponse>('/deliveries?limit=100&status=EN_ROUTE&include_total=true');

      const isValidCoordinate = (value: any): boolean => {
        if (value === null || value === undefined || value === '') return false;
        const coordinate = Number(value);
        return Number.isFinite(coordinate);
      };
      
      const items = Array.isArray(response) ? response : (response.items || []);

      return items.filter((d: any) => {
        const lat = d.current_latitude ?? d.latitude;
        const lng = d.current_longitude ?? d.longitude;
        
        return isValidCoordinate(lat) && isValidCoordinate(lng) &&
          [ 'INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'EN_DESTINO' ].includes(d.status);
      });
    } catch (error) {
      console.error('[DeliveryService] Error fetching live tracking:', error);
      throw error;
    }
  },
};