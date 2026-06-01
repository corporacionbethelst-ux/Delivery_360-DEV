import { api } from '@/lib/api';
import { UserRole } from '@/types/user';

export interface Permission {
  id: string;
  name: string;
  module: 'orders' | 'riders' | 'financial' | 'users' | 'admin';
  description?: string;
}

export interface Role {
  id: string;
  name: string; // Ej: "Gerente Regional"
  slug: string; // Ej: "regional_manager" (para código)
  description?: string | null;
  permissions: string[]; // Array de IDs de permisos
  users_count: number;
  is_system: boolean; // True si es rol por defecto (no borable)
  created_at: string;
}

export interface RoleCreateInput {
  name: string;
  slug: string;
  description?: string;
  permissions: string[];
}

export const roleService = {
  /**
   * Listar todos los roles.
   */
  getAll: async (): Promise<Role[]> => {
    try {
      return await api.get<Role[]>('/roles');
    } catch (error) {
      console.error('[RoleService] Error fetching roles:', error);
      throw error;
    }
  },

  /**
   * Obtener permisos disponibles del sistema.
   */
  getPermissions: async (): Promise<Permission[]> => {
    try {
      return await api.get<Permission[]>('/roles/permissions');
    } catch (error) {
      console.error('[RoleService] Error fetching permissions:', error);
      throw error;
    }
  },

  /**
   * Crear nuevo rol personalizado.
   */
  create: async (data: RoleCreateInput): Promise<Role> => {
    try {
      if (!data.name || !data.slug) {
        throw new Error('[RoleService] Nombre y Slug son requeridos.');
      }
      return await api.post<Role>('/roles', data);
    } catch (error) {
      console.error('[RoleService] Error creating role:', error);
      throw error;
    }
  },

  /**
   * Actualizar rol (Permisos y descripción).
   */
  update: async (id: string, data: Partial<RoleCreateInput>): Promise<Role> => {
    if (!id) throw new Error('[RoleService] ID requerido');
    try {
      return await api.patch<Role>(`/roles/${id}`, data);
    } catch (error) {
      console.error(`[RoleService] Error updating role ${id}:`, error);
      throw error;
    }
  },

  /**
   * Eliminar rol (Solo si no es sistema y no tiene usuarios).
   */
  delete: async (id: string): Promise<void> => {
    if (!id) throw new Error('[RoleService] ID requerido');
    try {
      await api.delete(`/roles/${id}`);
    } catch (error) {
      console.error(`[RoleService] Error deleting role ${id}:`, error);
      throw error;
    }
  }
};