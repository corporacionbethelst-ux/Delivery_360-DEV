import { api } from '@/lib/api'; // ✅ Usamos el wrapper 'api' que ya devuelve los datos (T)
import { User, AuthResponse } from '@/types/user';

// Interfaz para respuestas simples de mensaje del backend
export interface MessageResponse {
  message: string;
  detail?: string;
}

// Datos para registro de repartidor
export interface RegisterRiderData {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  phone: string;
  vehicle_type?: string;
  vehicle_plate?: string;
}

// Datos extendidos para registro con archivos (FormData)
export interface RegisterRiderWithFilesData extends RegisterRiderData {
  license_file: File;
  id_card_file: File;
}

export const authService = {
  /**
   * Login de usuario
   * ENVÍA COMO FORM DATA (application/x-www-form-urlencoded)
   */
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const params = new URLSearchParams();
    params.append('username', email); 
    params.append('password', password);

    try {
      // ✅ CORRECCIÓN: Usar 'api' en lugar de 'apiClient'
      // Nota: Como usamos FormData/URLSearchParams, necesitamos pasar los headers explícitamente
      // El wrapper 'api' permite pasar config como segundo/tercer argumento
      const response = await api.post<AuthResponse>('/auth/login', params, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      
      // 'response' ya es AuthResponse directamente gracias al wrapper
      return response; 
    } catch (error: any) {
      console.error('❌ Error detallado del login:', error.response?.data || error);
      
      const errorMsg = error.response?.data?.detail 
        || error.response?.data?.message 
        || 'Credenciales inválidas o error de conexión';
        
      throw new Error(errorMsg);
    }
  },

  /**
   * Registro de repartidor
   */
  register: async (data: RegisterRiderData | FormData): Promise<AuthResponse> => {
    let payload: FormData;

    if (data instanceof FormData) {
      payload = data;
    } else {
      payload = new FormData();
      payload.append('first_name', data.first_name);
      payload.append('last_name', data.last_name);
      payload.append('email', data.email);
      payload.append('password', data.password);
      payload.append('phone', data.phone);
      
      if (data.vehicle_type) payload.append('vehicle_type', data.vehicle_type);
      if (data.vehicle_plate) payload.append('vehicle_plate', data.vehicle_plate);
      
      // Manejo seguro de archivos si existen en el objeto (aunque lo ideal es pasar FormData)
      if ('license_file' in data && data.license_file) {
         // @ts-ignore
         payload.append('license_file', data.license_file);
      }
      if ('id_card_file' in data && data.id_card_file) {
         // @ts-ignore
         payload.append('id_card_file', data.id_card_file);
      }
    }

    try {
      // ✅ CORRECCIÓN: Usar 'api' y quitar .data
      const response = await api.post<AuthResponse>('/auth/register-rider', payload, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      return response;
    } catch (error: any) {
      console.error('❌ Error en registro:', error.response?.data);
      const errorMsg = error.response?.data?.detail || error.response?.data?.message || 'Error al registrar usuario';
      throw new Error(errorMsg);
    }
  },

  /**
   * Obtener perfil del usuario actual
   * ESTRATEGIA: Intenta /auth/me primero, luego /users/me como fallback
   */
  getProfile: async (): Promise<User> => {
    // Intento 1: Ruta común en backends auth-centric
    try {
      const response = await api.get<User>('/auth/me'); 
      return response; // ✅ Sin .data
    } catch (error: any) {
      console.warn('⚠️ Ruta /auth/me no encontrada, intentando /users/me...');
      
      // Intento 2: Fallback
      try {
        const fallbackResponse = await api.get<User>('/users/me');
        return fallbackResponse; // ✅ Sin .data
      } catch (fallbackError) {
        console.error('❌ Error crítico: Ningún endpoint de perfil encontrado.');
        throw error; // Lanza el error original para que el login lo maneje
      }
    }
  },

  /**
   * Cerrar sesión
   */
  logout: async (): Promise<void> => {
    try { 
      // ✅ CORRECCIÓN: Usar 'api'
      await api.post('/auth/logout'); 
    } catch (e) { 
      console.warn('⚠️ Error en logout del servidor, limpiando localmente...');
    }
  },
  
  /**
   * Actualizar perfil
   */
  updateProfile: async (data: Partial<User>): Promise<User> => {
    // ✅ CORRECCIÓN: Usar 'api' y quitar .data
    const response = await api.put<User>('/users/me', data);
    return response;
  },
  
  /**
   * Cambiar contraseña
   */
  changePassword: async (currentPassword: string, newPassword: string): Promise<MessageResponse> => {
    // ✅ CORRECCIÓN: Usar 'api' y quitar .data
    const response = await api.post<MessageResponse>('/auth/change-password', { 
      current_password: currentPassword,
      new_password: newPassword 
    });
    return response;
  },

  /**
   * Solicitud de recuperación de contraseña
   */
  forgotPassword: async (email: string): Promise<MessageResponse> => {
    try {
      // ✅ CORRECCIÓN: Usar 'api' y quitar .data
      const response = await api.post<MessageResponse>('/auth/forgot-password', { email });
      return response;
    } catch (error: any) {
      if (error.response?.status === 404 || error.response?.status === 400) {
         return { message: 'Si el correo existe, recibirás instrucciones.' };
      }
      throw error;
    }
  },

  /**
   * Restablecimiento de contraseña con token
   */
  resetPassword: async (token: string, newPassword: string): Promise<MessageResponse> => {
    // ✅ CORRECCIÓN: Usar 'api' y quitar .data
    const response = await api.post<MessageResponse>('/auth/reset-password', { 
      token, 
      new_password: newPassword 
    });
    return response;
  },
};