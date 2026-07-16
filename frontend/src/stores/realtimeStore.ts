// Realtime Store - Zustand para actualizaciones en tiempo real (WebSocket)
import { create } from 'zustand';
import type { Order, OrderStatus } from '@/types/order';
import type { Delivery, DeliveryStatus, DeliveryStatusLegacy } from '@/types/delivery';
import type { Rider, RiderStatus } from '@/types/user';
import type { Alert } from '@/types/alerts';
 
interface RealtimeState {
  // Estado de conexión
  isConnected: boolean;
  isConnecting: boolean;
  lastMessageAt: Date | null;
  error: string | null;
  
  // Datos en tiempo real
  activeOrders: Order[];
  activeDeliveries: Delivery[];
  onlineRiders: Rider[];
  alerts: Alert[];
  
  // Acciones - Conexión
  connect: () => void;
  disconnect: () => void;
  reconnect: () => void;
  
  // Acciones - Actualización de datos
  updateOrder: (order: Order) => void;
  updateDelivery: (delivery: Delivery) => void;
  updateRider: (rider: Rider) => void;
  addAlert: (alert: Alert) => void;
  dismissAlert: (alertId: string) => void;
  
  // Acciones - Estado
  setConnected: (connected: boolean) => void;
  setError: (error: string | null) => void;
  clearAll: () => void;
}

const initialState = {
  isConnected: false,
  isConnecting: false,
  lastMessageAt: null,
  error: null,
  activeOrders: [],
  activeDeliveries: [],
  onlineRiders: [],
  alerts: [],
};

export const useRealtimeStore = create<RealtimeState>((set, get) => ({
  ...initialState,
  
  // CONEXIÓN
  connect: () => {
    set({ isConnecting: true, error: null });
    // La implementación real de WebSocket se maneja en el hook useRealtimeUpdates
    // Este store solo gestiona el estado reactivo
  },
  
  disconnect: () => {
    set({ 
      isConnected: false, 
      isConnecting: false,
      lastMessageAt: null 
    });
  },
  
  reconnect: () => {
    set({ isConnecting: true });
  },
  
  // ACTUALIZACIÓN DE DATOS
  updateOrder: (order: Order) => {
    set((state) => {
      const existingIndex = state.activeOrders.findIndex(o => o.id === order.id);
      
      // Estados finales para Órdenes (Ajustar según tu tipo OrderStatus real)
      // Asumiendo valores comunes, verificar si coinciden con tu enum OrderStatus
      const finalStatuses: OrderStatus[] = ['ENTREGADO', 'CANCELADO'] as OrderStatus[];
      
      if (existingIndex >= 0) {
        const updatedOrders = [...state.activeOrders];
        
        if (finalStatuses.includes(order.status)) {
          // Si pasó a estado final, la removemos de la lista de "activas"
          updatedOrders.splice(existingIndex, 1);
        } else {
          // Si sigue activa, actualizamos los datos
          updatedOrders[existingIndex] = order;
        }
        
        return { activeOrders: updatedOrders };
      } else {
        // Nueva orden (solo si no es final)
        if (!finalStatuses.includes(order.status)) {
          return { activeOrders: [...state.activeOrders, order] };
        }
      }
      
      return {};
    });
  },
  
  updateDelivery: (delivery: Delivery) => {
    set((state) => {
      const existingIndex = state.activeDeliveries.findIndex(d => d.id === delivery.id);
      
      // ✅ CORRECCIÓN: Usando los valores EXACTOS del enum DeliveryStatus
      // INICIADA, EN_PICKUP, EN_ROUTE, COMPLETE, FAILED
      const finalStatuses: (DeliveryStatus | DeliveryStatusLegacy)[] = ['ENTREGADO', 'FALLIDO', 'CANCELADO'];
      
      if (existingIndex >= 0) {
        const updatedDeliveries = [...state.activeDeliveries];
        
        if (finalStatuses.includes(delivery.status)) {
          // Si la entrega finalizó (Completa o Fallida), la removemos de "activas"
          updatedDeliveries.splice(existingIndex, 1);
        } else {
          // Actualizamos datos en curso
          updatedDeliveries[existingIndex] = delivery;
        }
        
        return { activeDeliveries: updatedDeliveries };
      } else {
        // Nueva entrega activa (solo si no es final)
        if (!finalStatuses.includes(delivery.status)) {
          return { activeDeliveries: [...state.activeDeliveries, delivery] };
        }
      }
      
      return {};
    });
  },
  
  updateRider: (rider: Rider) => {
    set((state) => {
      const existingIndex = state.onlineRiders.findIndex(r => r.id === rider.id);
      
      // Verificar si está online y activo
      // Se usa 'is_online' según tu interfaz Rider
      if (rider.is_online && rider.status === 'ACTIVO') {
        if (existingIndex >= 0) {
          // Actualizar rider existente
          const updatedRiders = [...state.onlineRiders];
          updatedRiders[existingIndex] = rider;
          return { onlineRiders: updatedRiders };
        } else {
          // Nuevo rider online
          return { onlineRiders: [...state.onlineRiders, rider] };
        }
      } else {
        // Rider offline o inactivo - remover
        if (existingIndex >= 0) {
          const updatedRiders = [...state.onlineRiders];
          updatedRiders.splice(existingIndex, 1);
          return { onlineRiders: updatedRiders };
        }
      }
      
      return {};
    });
  },
  
  addAlert: (alert: Alert) => {
    set((state) => {
      // Evitar duplicados por ID
      const exists = state.alerts.find(a => a.id === alert.id);
      if (exists) return state;

      return {
        alerts: [alert, ...state.alerts].slice(0, 50) // Máximo 50 alertas recientes
      };
    });
  },
  
  dismissAlert: (alertId: string) => {
    set((state) => ({
      alerts: state.alerts.filter(a => a.id !== alertId)
    }));
  },
  
  // ESTADO
  setConnected: (connected: boolean) => {
    set({ 
      isConnected: connected, 
      isConnecting: !connected,
      lastMessageAt: connected ? new Date() : null
    });
  },
  
  setError: (error: string | null) => {
    set({ error, isConnecting: false });
  },
  
  clearAll: () => {
    set(initialState);
  },
}));

export default useRealtimeStore;