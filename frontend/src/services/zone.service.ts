import { api } from '@/lib/api';

export interface Zone {
  id: string;
  name: string;
  code: string;
  description?: string | null;
  delivery_fee_base: number;
  cost_per_km: number;
  estimated_time_min: number;
  is_priority: boolean;
  is_active: boolean;
  color_hex: string; // Ej: '#3b82f6'
  center_lat?: number | null;
  center_lng?: number | null;
  riders_count?: number; // Contador denormalizado
  created_at: string;
  updated_at?: string | null;
}

export interface ZoneCreateInput {
  name: string;
  code: string;
  description?: string;
  delivery_fee_base: number;
  cost_per_km: number;
  estimated_time_min: number;
  is_priority?: boolean;
  is_active?: boolean;
  color_hex?: string;
  center_lat?: number;
  center_lng?: number;
}

export const zoneService = {
  /**
   * Listar zonas.
   */
  getAll: async (): Promise<Zone[]> => {
    try {
      return await api.get<Zone[]>('/zones');
    } catch (error) {
      console.error('[ZoneService] Error fetching zones:', error);
      throw error;
    }
  },

  /**
   * Obtener zona por ID.
   */
  getById: async (id: string): Promise<Zone> => {
    if (!id) throw new Error('[ZoneService] ID de zona requerido');
    try {
      return await api.get<Zone>(`/zones/${id}`);
    } catch (error) {
      console.error(`[ZoneService] Error fetching zone ${id}:`, error);
      throw error;
    }
  },

  /**
   * Crear nueva zona.
   */
  create: async (data: ZoneCreateInput): Promise<Zone> => {
    try {
      if (!data.name || !data.code) {
        throw new Error('[ZoneService] Nombre y Código son requeridos.');
      }
      if (data.delivery_fee_base < 0 || data.cost_per_km < 0) {
        throw new Error('[ZoneService] Las tarifas no pueden ser negativas.');
      }

      return await api.post<Zone>('/zones', data);
    } catch (error) {
      console.error('[ZoneService] Error creating zone:', error);
      throw error;
    }
  },

  /**
   * Actualizar zona.
   */
  update: async (id: string, data: Partial<ZoneCreateInput>): Promise<Zone> => {
    if (!id) throw new Error('[ZoneService] ID requerido para actualizar');
    try {
      return await api.patch<Zone>(`/zones/${id}`, data);
    } catch (error) {
      console.error(`[ZoneService] Error updating zone ${id}:`, error);
      throw error;
    }
  },

  /**
   * Eliminar zona (Verificar en backend si permite borrar con órdenes asociadas).
   */
  delete: async (id: string): Promise<void> => {
    if (!id) throw new Error('[ZoneService] ID requerido para eliminar');
    try {
      await api.delete(`/zones/${id}`);
    } catch (error) {
      console.error(`[ZoneService] Error deleting zone ${id}:`, error);
      throw error;
    }
  }
};