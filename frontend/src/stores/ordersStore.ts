import { readOrderCatalog, validateHttpOrder } from '@/lib/operational-catalog';
import { orderView, filterOrderViews } from '@/lib/order-view';
import { capturePrivateTask, resetOnSessionChange } from '@/lib/private-task';
// Store de Orders con Zustand - Delivery360
import { create } from 'zustand';
import { api } from '@/lib/api'; // ✅ Usar el wrapper correcto
import { orderAssignmentPatch, type OrderAssignmentPatch } from '@/lib/order-assignment';
import type { Order, OrderFilters, OrderStats, OrderCreateInput, OrderStatus } from '../types/order';

interface OrdersState {
  // Datos
  orders: Order[];
  selectedOrder: Order | null;
  filters: OrderFilters;
  stats: OrderStats | null;
  
  // Estado de carga
  isLoading: boolean;
  isCreating: boolean;
  isUpdating: boolean;
  error: string | null;
  
  // Paginación
  pagination: {
    page: number;
    pageSize: number;
    total: number | null;
    totalPages: number | null;
  };
  
  // Acciones Síncronas (Estado local)
  setOrders: (orders: Order[]) => void;
  addOrder: (order: Order) => void;
  updateOrderLocal: (id: string, updates: Partial<Order>) => void;
  removeOrder: (id: string) => void;
  setSelectedOrder: (order: Order | null) => void;
  setFilters: (filters: Partial<OrderFilters>) => void;
  setStats: (stats: OrderStats) => void;
  
  // Fetch actions (API real)
  fetchOrders: (filters?: OrderFilters) => Promise<void>;
  fetchOrderById: (id: string) => Promise<void>;
  createOrder: (input: OrderCreateInput) => Promise<Order>;
  updateOrderStatus: (id: string, status: OrderStatus) => Promise<void>;
  assignRider: (orderId: string, riderId: string) => Promise<OrderAssignmentPatch>;
  deleteOrder: (id: string) => Promise<void>;
  
  reset: () => void;
}

const initialState = {
  orders: [],
  selectedOrder: null,
  filters: {},
  stats: null,
  isLoading: false,
  isCreating: false,
  isUpdating: false,
  error: null,
  pagination: {
    page: 1,
    pageSize: 20,
    total: null,
    totalPages: null,
  },
};

let listRequest = 0, detailRequest = 0;

export const useOrdersStore = create<OrdersState>((set, get) => ({
  ...initialState,
  
  // --- ACCIONES SÍNCRONAS ---
  setOrders: (orders) => set({ orders }),
  
  addOrder: (order) => set((state) => ({ 
    orders: [order, ...state.orders] 
  })),
  
  // Renombrado a updateOrderLocal para evitar conflicto con la acción asíncrona si se usa mal
  updateOrderLocal: (id, updates) => set((state) => ({
    orders: state.orders.map((order) => 
      order.id === id ? { ...order, ...updates } : order
    ),
    selectedOrder: state.selectedOrder?.id === id 
      ? { ...state.selectedOrder, ...updates } 
      : state.selectedOrder,
  })),
  
  removeOrder: (id) => set((state) => ({
    orders: state.orders.filter((order) => order.id !== id),
    selectedOrder: state.selectedOrder?.id === id ? null : state.selectedOrder,
  })),
  
  setSelectedOrder: (order) => set({ selectedOrder: order }),
  
  setFilters: (filters) => set((state) => ({ 
    filters: { ...state.filters, ...filters },
    pagination: { ...state.pagination, page: 1 } // Resetear a pág 1 al filtrar
  })),
  
  setStats: (stats) => set({ stats }),
  
  // --- ACCIONES ASÍNCRONAS (API) ---
  
  fetchOrders: async (filters) => {
    const task = capturePrivateTask(), request = ++listRequest;
    const assertCurrent = () => {
      task.assertCurrent();
      if (request !== listRequest) throw new Error('Consulta de pedidos sustituida por otra más reciente');
    };
    set({ isLoading: true, error: null });
    try {
      const f = filters ?? get().filters;
      const rows = await readOrderCatalog({ status: f.status?.length === 1 ? f.status[0] as never : undefined, rider_id: f.riderId }, assertCurrent);
      assertCurrent();
      const orders = filterOrderViews(rows.map(row => orderView(row)), f);
      set({ orders, filters: f, pagination: { ...get().pagination, page: 1, total: orders.length,
        totalPages: Math.ceil(orders.length / get().pagination.pageSize) }, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      if (request === listRequest) set({ error: error.message || 'Error al obtener pedidos', isLoading: false });
      throw error;
    }
  },
  
  fetchOrderById: async (id) => {
    const task = capturePrivateTask(), request = ++detailRequest;
    set({ isLoading: true, error: null });
    try {
      const response = await api.get<unknown>(`/orders/${encodeURIComponent(id)}`);
      task.assertCurrent();
      if (request !== detailRequest) return;
      set({ selectedOrder: orderView(response, id), isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      if (request === detailRequest) set({ error: error.message || 'Error al obtener pedido', isLoading: false });
      throw error;
    }
  },
  
  createOrder: async (input) => {
    const task = capturePrivateTask();
    set({ isCreating: true, error: null });
    try {
      // ✅ Sin .data
      const response = await api.post<unknown>('/orders', input);
      task.assertCurrent();
      
      const newOrder = orderView(response);
      listRequest++;
      set((state) => ({ 
        orders: [newOrder, ...state.orders],
        pagination: {
          ...state.pagination,
          total: null, totalPages: null,
        },
        isCreating: false, isLoading: false
      }));
      return newOrder;
    } catch (error: any) {
      task.assertCurrent();
      set({ 
        error: error.message || 'Error al crear pedido',
        isCreating: false, isLoading: false
      });
      throw error;
    }
  },
  
  updateOrderStatus: async (id, status) => {
    const task = capturePrivateTask();
    set({ isUpdating: true, error: null });
    try {
      // ✅ Sin .data
      const response = await api.patch<unknown>(`/orders/${encodeURIComponent(id)}/status`, {}, { params: { new_status: status } });
      task.assertCurrent();
      const updatedOrder = orderView(response, id);
      if (updatedOrder.status !== status) throw new Error('El servidor no confirmó el estado solicitado');
      listRequest++; detailRequest++;
      get().updateOrderLocal(id, updatedOrder);
      set({ isUpdating: false, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      set({ 
        error: error.message || 'Error al actualizar estado',
        isUpdating: false 
      });
      throw error;
    }
  },
  
  assignRider: async (orderId, riderId) => {
    const task = capturePrivateTask();
    if (typeof orderId !== 'string' || !orderId.trim() || typeof riderId !== 'string' || !riderId.trim()) {
      throw new Error('Indica el pedido y el repartidor antes de asignar');
    }
    set({ isUpdating: true, error: null });
    try {
      // ✅ Sin .data
      const updatedOrder = await api.patch<unknown>(`/orders/${encodeURIComponent(orderId)}/assign`, { rider_id: riderId });
      task.assertCurrent();
      const confirmed = orderAssignmentPatch(updatedOrder, orderId, riderId);
      validateHttpOrder(updatedOrder, orderId);
      listRequest++; detailRequest++;
      get().updateOrderLocal(orderId, confirmed);
      set({ isUpdating: false, isLoading: false });
      return confirmed;
    } catch (error: any) {
      task.assertCurrent();
      set({ 
        error: error.message || 'Error al asignar repartidor',
        isUpdating: false 
      });
      throw error;
    }
  },
  
  deleteOrder: async (id) => {
    const task = capturePrivateTask();
    set({ isUpdating: true, error: null });
    try {
      await api.delete(`/orders/${id}`);
      task.assertCurrent();
      listRequest++; detailRequest++;
      get().removeOrder(id);
      set({ isUpdating: false, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      set({ 
        error: error.message || 'Error al eliminar pedido',
        isUpdating: false 
      });
      throw error;
    }
  },
  
  reset: () => { listRequest++; detailRequest++; set(initialState); },
}));
resetOnSessionChange(useOrdersStore);
