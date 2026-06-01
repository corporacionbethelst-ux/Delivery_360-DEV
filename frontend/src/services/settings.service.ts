import { api } from '@/lib/api';

export interface PlatformSettings {
  delivery_fee_base: number;
  commission_percentage: number;
  min_order_amount: number;
  active_zones: string[];
  support_email: string;
  maintenance_mode: boolean;
}

// Valores por defecto seguros (Fallback)
const DEFAULT_SETTINGS: PlatformSettings = {
  delivery_fee_base: 5000,
  commission_percentage: 15,
  min_order_amount: 10000,
  active_zones: ['Norte', 'Sur', 'Centro'],
  support_email: 'soporte@delivery.com',
  maintenance_mode: false
};

export const settingsService = {
  /**
   * Obtiene la configuración global de la plataforma.
   * Intenta traer datos reales del backend. Si falla (ej. endpoint no listo),
   * devuelve valores por defecto seguros para no romper la UI.
   */
  getSettings: async (): Promise<PlatformSettings> => {
    try {
      const response = await api.get<PlatformSettings>('/settings');
      // Asumiendo que api.get retorna directamente los datos gracias a nuestros interceptores
      // Si tu interceptor retorna el objeto Axios completo, usar: return response.data;
      return response; 
    } catch (error) {
      console.warn('⚠️ No se pudo cargar la configuración del backend. Usando valores por defecto.', error);
      // Retornamos una copia para evitar mutaciones accidentales del default
      return { ...DEFAULT_SETTINGS };
    }
  },

  /**
   * Actualiza la configuración global.
   * Incluye validaciones básicas antes de enviar al backend.
   */
  updateSettings: async (settings: Partial<PlatformSettings>): Promise<PlatformSettings> => {
    // Validaciones de seguridad básicas
    if (settings.commission_percentage !== undefined) {
      if (settings.commission_percentage < 0 || settings.commission_percentage > 100) {
        throw new Error('La comisión debe estar entre 0 y 100');
      }
    }

    if (settings.delivery_fee_base !== undefined && settings.delivery_fee_base < 0) {
      throw new Error('La tarifa base no puede ser negativa');
    }

    try {
      const response = await api.patch<PlatformSettings>('/settings', settings);
      return response;
    } catch (error: any) {
      console.error('❌ Error al actualizar configuración:', error);
      // Propagamos el error para que el componente muestre la alerta correspondiente
      throw new Error(error.response?.data?.detail || 'No se pudo guardar la configuración');
    }
  }
};