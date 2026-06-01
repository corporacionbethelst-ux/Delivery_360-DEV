import { api } from '@/lib/api';
import { User, UserRole } from '@/types/user';

export interface UserCreateInput {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  phone?: string;
  is_active?: boolean;
}

export interface UserFilters {
  role?: UserRole;
  is_active?: boolean;
  search?: string;
  limit?: number;
  page?: number;
}

export const userService = {
  /**
   * Obtener lista de usuarios con filtros opcionales.
   * GET /users
   */
  getAll: async (params?: Readonly<UserFilters>): Promise<User[]> => {
    try {
      const queryParams = new URLSearchParams();
      
      if (params?.role) queryParams.append('role', params.role);
      if (params?.is_active !== undefined) queryParams.append('is_active', String(params.is_active));
      if (params?.search) queryParams.append('search', params.search);
      if (params?.limit) queryParams.append('limit', String(params.limit));
      if (params?.page) queryParams.append('page', String(params.page));

      const query = queryParams.toString() ? `?${queryParams}` : '';
      
      // Asumiendo que api.get retorna directamente T gracias a los interceptores
      return await api.get<User[]>(`/users${query}`);
    } catch (error) {
      console.error('[UserService] Error fetching users:', error);
      throw error;
    }
  },

  /**
   * Obtener detalles de un usuario específico por ID.
   * GET /users/{id}
   */
  getById: async (id: string): Promise<User> => {
    if (!id || typeof id !== 'string') {
      throw new Error('[UserService] ID de usuario inválido');
    }

    try {
      return await api.get<User>(`/users/${id}`);
    } catch (error) {
      console.error(`[UserService] Error fetching user ${id}:`, error);
      throw error;
    }
  },

  /**
   * Crear un nuevo usuario.
   * POST /users
   */
  create: async (data: UserCreateInput): Promise<User> => {
    try {
      // Validaciones básicas
      if (!data.email || !data.password || !data.first_name || !data.last_name || !data.role) {
        throw new Error('[UserService] Campos requeridos faltantes para crear usuario');
      }

      return await api.post<User>('/users', data);
    } catch (error) {
      console.error('[UserService] Error creating user:', error);
      throw error;
    }
  },

  /**
   * Actualizar datos de un usuario existente.
   * PATCH /users/{id}
   */
  update: async (id: string, data: Partial<UserCreateInput>): Promise<User> => {
    if (!id) throw new Error('[UserService] ID requerido para actualizar usuario');

    try {
      return await api.patch<User>(`/users/${id}`, data);
    } catch (error) {
      console.error(`[UserService] Error updating user ${id}:`, error);
      throw error;
    }
  },

  /**
   * Desactivar un usuario (soft delete).
   * PATCH /users/{id}
   */
  deactivate: async (id: string): Promise<void> => {
    if (!id) throw new Error('[UserService] ID requerido para desactivar usuario');

    try {
      await api.patch(`/users/${id}`, { is_active: false });
    } catch (error) {
      console.error(`[UserService] Error deactivating user ${id}:`, error);
      throw error;
    }
  },

  /**
   * Eliminar permanentemente un usuario (si el backend lo soporta).
   * DELETE /users/{id}
   */
  delete: async (id: string): Promise<void> => {
    if (!id) throw new Error('[UserService] ID requerido para eliminar usuario');

    try {
      await api.delete(`/users/${id}`);
    } catch (error) {
      console.error(`[UserService] Error deleting user ${id}:`, error);
      throw error;
    }
  }
};