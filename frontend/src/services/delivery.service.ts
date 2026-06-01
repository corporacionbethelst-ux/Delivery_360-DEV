import { api } from '@/lib/api';

// Usamos string union para ser flexibles con el filtro
export type DeliveryStatus = 'PENDIENTE' | 'INICIADA' | 'EN_RUTA' | 'COMPLETADA' | 'INCIDENCIA' | 'FALLIDA' | 'EN_PICKUP' | 'EN_DESTINO';

export interface RiderInfo {
  id: string;
  first_name: string;
  last_name: string;
  vehicle_type?: string | null;
}

export interface Delivery {
  id: string;
  order_id: string;
  external_id?: string;
  rider_id: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  pickup_at?: string | null;
  delivered_at?: string | null;
  current_latitude?: number | null;
  current_longitude?: number | null;
  total_time?: number | null;
  distance_total?: number | null;
  sla_compliant?: boolean | null;
  proof_otp?: string | null;
  created_at: string;
  updated_at: string;
  // Datos Enriquecidos (Vienen del backend gracias al join)
  customer_name?: string;
  rider?: RiderInfo | null;
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
  status?: string; // CAMBIO CRÍTICO: Permitir string genérico
  limit?: number;
  offset?: number; // CAMBIO CRÍTICO: Agregar offset explícito
}

export const deliveryService = {
  /**
   * Listar entregas con filtros, paginación y offset.
   */
  getAll: async (params?: Readonly<DeliveryFilters>): Promise<Delivery[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.rider_id) queryParams.append('rider_id', params.rider_id);
      if (params?.status) queryParams.append('status', params.status);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.offset) queryParams.append('offset', String(params.offset));

      const query = queryParams.toString() ? `?${queryParams}` : '';
      const response = await api.get<Delivery[]>(`/deliveries${query}`);
      
      return response;
    } catch (error) {
      console.error('[DeliveryService] Error fetching deliveries:', error);
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

  start: async (orderId: string): Promise<{ otp_code: string; message: string }> => {
    if (!orderId) throw new Error('[DeliveryService] Order ID requerido');
    try {
      return await api.post(`/deliveries/${orderId}/start`);
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || 'No se pudo iniciar la entrega');
    }
  },

  complete: async (id: string, proof: DeliveryProofInput): Promise<any> => {
    if (!id) throw new Error('[DeliveryService] ID requerido');
    try {
      return await api.patch(`/deliveries/${id}/complete`, proof);
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || 'Error al completar');
    }
  },

  updateLocation: async (id: string, lat: number, lng: number): Promise<void> => {
    if (!id) throw new Error('[DeliveryService] ID requerido');
    try {
      // Asumiendo que el endpoint es /{id}/location. 
      // Si tu backend usa otro path, ajústalo aquí.
      await api.patch(`/deliveries/${id}/location`, { 
        latitude: lat, 
        longitude: lng 
      });
    } catch (error: any) {
      console.error('[DeliveryService] Error updating location:', error);
      throw new Error(error.response?.data?.detail || 'No se pudo actualizar la ubicación');
    }
  },

  GetActiveTracking: async (): Promise<Delivery[]> => {
     try {
       // Obtenemos solo las que están en ruta para no cargar todo el historial
       const response = await api.get<Delivery[]>('/deliveries?status=EN_RUTA&limit=100');
       return response;
     } catch (error) {
       console.error('[DeliveryService] Error fetching active tracking:', error);
       throw error;
     }
  },
  
  getLiveTracking: async (): Promise<Delivery[]> => {
    try {
      // Pedimos un límite mayor para el mapa
      const response = await api.get<Delivery[]>('/deliveries?limit=100&status=EN_ROUTE');
      
      // Filtramos cliente-side para asegurarnos que tengan coordenadas válidas
      return response.filter(d => 
        d.current_latitude !== null && 
        d.current_longitude !== null &&
        [ 'INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'EN_DESTINO' ].includes(d.status)
      );
    } catch (error) {
      console.error('[DeliveryService] Error fetching live tracking:', error);
      throw error;
    }
  },
};