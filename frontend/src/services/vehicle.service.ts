import { api } from '@/lib/api';
import { AxiosError } from 'axios';

// --- Tipos e Interfaces Estrictas ---

export type VehicleType = 'MOTO' | 'AUTO' | 'FURGONETA' | 'BICICLETA';
export type VehicleStatus = 'ACTIVO' | 'MANTENIMIENTO' | 'BAJA';

export interface Vehicle {
  id: string;
  plate: string;
  type: VehicleType;
  model: string;
  color: string;
  year: number;
  status: VehicleStatus;
  insurance_expiry?: string | null;
  rider_id?: string | null;
  rider_name?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface VehicleCreateInput {
  plate: string;
  type: VehicleType;
  model: string;
  color: string;
  year: number;
  insurance_expiry?: string;
  notes?: string;
}

export interface VehicleFilters {
  type?: VehicleType;
  status?: VehicleStatus;
  search?: string;
  available_only?: boolean;
  limit?: number;
  page?: number;
}

// --- Clases de Error Personalizadas ---

class ServiceError extends Error {
  constructor(
    message: string,
    public status?: number,
    public code?: string
  ) {
    super(message);
    this.name = 'ServiceError';
  }
}

// --- Helpers Internos ---

const handleApiError = (error: unknown, context: string): never => {
  console.error(`[VehicleService] ${context}:`, error);

  if (error instanceof AxiosError) {
    const message = error.response?.data?.detail || error.message || 'Error desconocido';
    throw new ServiceError(message, error.response?.status, error.code);
  }

  if (error instanceof Error) {
    throw new ServiceError(error.message);
  }

  throw new ServiceError('Error inesperado en el servicio');
};

const isValidUuid = (id: string): boolean => {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return uuidRegex.test(id);
};

// --- Servicio Principal ---

export const vehicleService = {
  /**
   * Obtener lista de vehículos con filtros.
   * GET /vehicles
   */
  getAll: async (params?: Readonly<VehicleFilters>): Promise<Vehicle[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.type) queryParams.append('type', params.type);
      if (params?.status) queryParams.append('status', params.status);
      if (params?.search) queryParams.append('search', params.search);
      if (params?.available_only) queryParams.append('available_only', 'true');
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.page) queryParams.append('page', String(params.page));

      const query = queryParams.toString() ? `?${queryParams}` : '';
      
      // api.get ya devuelve los datos directamente (T), no hay que hacer .data ni extractData
      const response = await api.get<Vehicle[]>(`/vehicles${query}`);
      return response;
    } catch (error) {
      throw handleApiError(error, 'Error fetching vehicles');
    }
  },

  /**
   * Obtener detalles de un vehículo por ID.
   * GET /vehicles/{id}
   */
  getById: async (id: string): Promise<Vehicle> => {
    if (!id || !isValidUuid(id)) {
      throw new ServiceError('ID de vehículo inválido', 400);
    }
    try {
      const response = await api.get<Vehicle>(`/vehicles/${id}`);
      return response;
    } catch (error) {
      throw handleApiError(error, `Error fetching vehicle ${id}`);
    }
  },

  /**
   * Registrar nuevo vehículo.
   * POST /vehicles
   */
  create: async (data: VehicleCreateInput): Promise<Vehicle> => {
    if (!data.plate || !data.model || !data.year) {
      throw new ServiceError('Placa, Modelo y Año son requeridos', 400);
    }
    
    const cleanPlate = data.plate.trim().toUpperCase();
    if (!/^[A-Z0-9-]+$/.test(cleanPlate)) {
      throw new ServiceError('Formato de placa inválido. Solo letras, números y guiones.', 400);
    }

    if (data.year < 1900 || data.year > new Date().getFullYear() + 1) {
      throw new ServiceError('Año del vehículo inválido', 400);
    }

    try {
      const payload = { ...data, plate: cleanPlate };
      const response = await api.post<Vehicle>('/vehicles', payload);
      return response;
    } catch (error) {
      throw handleApiError(error, 'Error creating vehicle');
    }
  },

  /**
   * Actualizar vehículo existente.
   * PATCH /vehicles/{id}
   */
  update: async (id: string, data: Partial<VehicleCreateInput> & { status?: VehicleStatus }): Promise<Vehicle> => {
    if (!id || !isValidUuid(id)) {
      throw new ServiceError('ID de vehículo inválido', 400);
    }
    
    const payload: any = { ...data };
    if (payload.plate) {
      payload.plate = payload.plate.trim().toUpperCase();
      if (!/^[A-Z0-9-]+$/.test(payload.plate)) {
        throw new ServiceError('Formato de placa inválido', 400);
      }
    }

    try {
      const response = await api.patch<Vehicle>(`/vehicles/${id}`, payload);
      return response;
    } catch (error) {
      throw handleApiError(error, `Error updating vehicle ${id}`);
    }
  },

  /**
   * Dar de baja un vehículo (Cambio de estado a BAJA).
   * PATCH /vehicles/{id}
   */
  deactivate: async (id: string): Promise<Vehicle> => {
    if (!id || !isValidUuid(id)) {
      throw new ServiceError('ID de vehículo inválido', 400);
    }
    try {
      const response = await api.patch<Vehicle>(`/vehicles/${id}`, { status: 'BAJA' });
      return response;
    } catch (error) {
      throw handleApiError(error, `Error deactivating vehicle ${id}`);
    }
  },

  /**
   * Eliminar permanentemente un vehículo.
   * DELETE /vehicles/{id}
   */
  delete: async (id: string): Promise<void> => {
    if (!id || !isValidUuid(id)) {
      throw new ServiceError('ID de vehículo inválido', 400);
    }
    try {
      await api.delete(`/vehicles/${id}`);
    } catch (error) {
      throw handleApiError(error, `Error deleting vehicle ${id}`);
    }
  }
};