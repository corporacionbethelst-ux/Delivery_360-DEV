import { readRiderCatalog, validateRider } from '@/lib/operational-catalog';
import { capturePrivateTask, resetOnSessionChange } from '@/lib/private-task';
// Riders Store - Zustand para gestión de repartidores
// VERSIÓN DEFINITIVA: Consistente con user.ts (snake_case) y api wrapper

import { create } from 'zustand';
import { api } from '@/lib/api';
import { riderService } from '@/services/rider.service';
import { requireVehicleRevision } from '@/lib/vehicle-revision'; // ✅ Importación named correcta
import type { Rider, RiderStatus, RiderDocument } from '@/types/user';

// ==============================================================================
// INTERFACES LOCALES (Para evitar conflictos con rider.ts y garantizar consistencia)
// ==============================================================================

interface RiderCreateInput extends Partial<Rider> {
  expected_vehicle_revision?: string;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone: string;
  role?: 'REPARTIDOR';
}

interface RiderUpdateInput extends Partial<Rider> { expected_profile_revision?: string; expected_assignment_revision?: string; expected_vehicle_revision?: string; }

interface RiderFilters {
  status?: RiderStatus[];
  is_online?: boolean;
  vehicle_type?: string[];
  operating_zone?: string;
  search?: string;
  dateFrom?: Date;
  dateTo?: Date;
}

// ==============================================================================
// ESTADO DEL STORE
// ==============================================================================

interface RidersState {
  // Estado
  riders: Rider[];
  selectedRider: Rider | null;
  filters: RiderFilters;
  isLoading: boolean;
  error: string | null;
  total: number;
  
  // Acciones - Fetch
  fetchRiders: (filters?: Partial<RiderFilters>) => Promise<void>;
  fetchRiderById: (id: string) => Promise<void>;
  fetchPendingDocuments: () => Promise<RiderDocument[]>;
  
  // Acciones - CRUD
  createRider: (data: RiderCreateInput) => Promise<Rider>;
  updateRider: (id: string, data: RiderUpdateInput) => Promise<Rider>;
  deleteRider: (id: string) => Promise<void>;
  approveRider: (id: string, observations?: string) => Promise<void>;
  rejectRider: (id: string, reason: string) => Promise<void>;
  
  // Acciones - Estado
  setRiderOnline: (id: string, online: boolean) => void;
  updateRiderLocation: (id: string, latitude: number, longitude: number) => void;
  
  // Acciones - Filtros
  setFilters: (filters: Partial<RiderFilters>) => void;
  resetFilters: () => void;
  setSelectedRider: (rider: Rider | null) => void;
  
  // Utilidades
  getAvailableRiders: () => Rider[];
  getRidersByZone: (zone: string) => Rider[];
  searchRiders: (query: string) => Rider[];
}

const initialState = {
  riders: [],
  selectedRider: null,
  filters: {},
  isLoading: false,
  error: null,
  total: 0,
};

let listRequest = 0, detailRequest = 0;

export const useRidersStore = create<RidersState>((set, get) => ({
  ...initialState,
  
  // ==========================================================================
  // FETCH OPERATIONS
  // ==========================================================================
  
  fetchRiders: async (filters?: Partial<RiderFilters>) => {
    const task = capturePrivateTask(), request = ++listRequest;
    const assertCurrent = () => {
      task.assertCurrent();
      if (request !== listRequest) throw new Error('Consulta de repartidores sustituida por otra más reciente');
    };
    set({ isLoading: true, error: null });
    try {
      const f = filters ?? get().filters;
      const rows = await readRiderCatalog({ status_filter: f.status?.length === 1 ? f.status[0] : undefined, is_online: f.is_online }, assertCurrent);
      assertCurrent();
      const from = f.dateFrom?.getTime(), to = f.dateTo?.getTime();
      if (from !== undefined && !Number.isFinite(from) || to !== undefined && !Number.isFinite(to)) throw new Error('Fecha de filtro inválida');
      const riders = rows.filter(r => {
        const time = r.created_at ? new Date(r.created_at).getTime() : NaN;
        return (!f.status?.length || !!r.status && f.status.includes(r.status)) &&
          (!f.vehicle_type?.length || !!r.vehicle_type && f.vehicle_type.includes(r.vehicle_type)) &&
          (!f.operating_zone || r.operating_zone === f.operating_zone) &&
          (from === undefined || time >= from) && (to === undefined || time <= to) &&
          (!f.search || [r.id, r.full_name, r.first_name, r.last_name, r.phone, r.email, r.cpf, r.vehicle_plate]
            .some(v => v?.toLowerCase().includes(f.search!.toLowerCase())));
      });
      set({ riders, filters: f, total: riders.length, isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      if (request === listRequest) set({ error: error.message || 'Error al obtener repartidores', isLoading: false });
      throw error;
    }
  },
  
  fetchRiderById: async (id: string) => {
    const task = capturePrivateTask(), request = ++detailRequest;
    set({ isLoading: true, error: null });
    try {
      // Validate identity before publishing
      const rider = await api.get<Rider>(`/riders/${encodeURIComponent(id)}`);
      task.assertCurrent();
      if (request === detailRequest) set({ selectedRider: validateRider(rider, id), isLoading: false });
    } catch (error: any) {
      task.assertCurrent();
      console.error(`[RidersStore] Error fetching rider ${id}:`, error);
      if (request === detailRequest) set({ error: error.message || 'Error al obtener detalle del repartidor', isLoading: false });
      throw error;
    }
  },
  
  fetchPendingDocuments: async () => {
    const task = capturePrivateTask();
    try {
      // ✅ Devuelve directamente el array de documentos
      const docs = await api.get<RiderDocument[]>('/riders/documents/pending');
      task.assertCurrent();
      return docs;
    } catch (error: any) {
      task.assertCurrent();
      console.error('[RidersStore] Error fetching pending documents:', error);
      set({ error: error.message });
      throw error;
    }
  },
  
  // ==========================================================================
  // CRUD OPERATIONS
  // ==========================================================================
  
  createRider: async (data: RiderCreateInput) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      if (data.vehicle_ownership_type === 'EMPRESA') requireVehicleRevision(data.expected_vehicle_revision);
      const newRider = await api.post<Rider>('/riders', data);
      task.assertCurrent();
      set((state) => ({ 
        riders: [...state.riders, newRider],
        total: state.total + 1,
        isLoading: false 
      }));
      return newRider;
    } catch (error: any) {
      task.assertCurrent();
      console.error('[RidersStore] Error creating rider:', { status: error?.status ?? error?.response?.status });
      set({ error: error.message || 'Error al crear repartidor', isLoading: false });
      throw error;
    }
  },
  
  updateRider: async (id: string, data: RiderUpdateInput) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      const updatedRider = await riderService.updateRider(id, { ...data, phone: data.phone ?? undefined });
      task.assertCurrent();
      set((state) => ({
        riders: state.riders.map(r => r.id === id ? updatedRider : r),
        selectedRider: state.selectedRider?.id === id ? updatedRider : state.selectedRider,
        isLoading: false
      }));
      return updatedRider;
    } catch (error: any) {
      task.assertCurrent();
      console.error(`[RidersStore] Error updating rider ${id}:`, error);
      set({ error: error.message || 'Error al actualizar repartidor', isLoading: false });
      throw error;
    }
  },
  
  deleteRider: async (id: string) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      await api.delete(`/riders/${id}`);
      task.assertCurrent();
      set((state) => ({
        riders: state.riders.filter(r => r.id !== id),
        total: state.total - 1,
        selectedRider: state.selectedRider?.id === id ? null : state.selectedRider,
        isLoading: false
      }));
    } catch (error: any) {
      task.assertCurrent();
      console.error(`[RidersStore] Error deleting rider ${id}:`, error);
      set({ error: error.message || 'Error al eliminar repartidor', isLoading: false });
      throw error;
    }
  },
  
  approveRider: async (id: string, observations?: string) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      await api.post(`/riders/${id}/approve`, { observations });
      task.assertCurrent();
      const updatedRider = await api.get<Rider>(`/riders/${id}`);
      task.assertCurrent();
      set((state) => ({
        riders: state.riders.map(r => r.id === id ? updatedRider : r),
        isLoading: false
      }));
    } catch (error: any) {
      task.assertCurrent();
      console.error(`[RidersStore] Error approving rider ${id}:`, error);
      set({ error: error.message || 'Error al aprobar repartidor', isLoading: false });
      throw error;
    }
  },
  
  rejectRider: async (id: string, reason: string) => {
    const task = capturePrivateTask();
    set({ isLoading: true, error: null });
    try {
      await api.post(`/riders/${id}/reject`, { reason });
      task.assertCurrent();
      const updatedRider = await api.get<Rider>(`/riders/${id}`);
      task.assertCurrent();
      set((state) => ({
        riders: state.riders.map(r => r.id === id ? updatedRider : r),
        isLoading: false
      }));
    } catch (error: any) {
      task.assertCurrent();
      console.error(`[RidersStore] Error rejecting rider ${id}:`, error);
      set({ error: error.message || 'Error al rechazar repartidor', isLoading: false });
      throw error;
    }
  },
  
  // ==========================================================================
  // ESTADO Y UBICACIÓN (Snake Case estricto)
  // ==========================================================================
  
  setRiderOnline: (id: string, online: boolean) => {
    set((state) => ({
      riders: state.riders.map(r => 
        r.id === id ? { ...r, is_online: online } : r
      ),
      selectedRider: state.selectedRider?.id === id 
        ? { ...state.selectedRider, is_online: online } 
        : state.selectedRider
    }));
  },
  
  updateRiderLocation: (id: string, latitude: number, longitude: number) => {
    set((state) => ({
      riders: state.riders.map(r => 
        r.id === id 
          ? { 
              ...r, 
              last_lat: latitude, 
              last_lng: longitude,
              last_location_at: new Date().toISOString()
            } 
          : r
      ),
      selectedRider: state.selectedRider?.id === id
        ? {
            ...state.selectedRider,
            last_lat: latitude,
            last_lng: longitude,
            last_location_at: new Date().toISOString()
          }
        : state.selectedRider
    }));
  },
  
  // ==========================================================================
  // FILTROS Y UTILIDADES
  // ==========================================================================
  
  setFilters: (filters: Partial<RiderFilters>) => {
    set((state) => ({ filters: { ...state.filters, ...filters } }));
  },
  
  resetFilters: () => {
    set({ filters: {} });
  },
  
  setSelectedRider: (rider: Rider | null) => {
    set({ selectedRider: rider });
  },
  
  getAvailableRiders: () => {
    const { riders } = get();
    return riders.filter(r => r.status === 'ACTIVO' && r.is_online);
  },
  
  getRidersByZone: (zone: string) => {
    const { riders } = get();
    return riders.filter(r => r.operating_zone === zone && r.is_online && r.status === 'ACTIVO');
  },
  
  searchRiders: (query: string) => {
    const { riders } = get();
    const lowerQuery = query.toLowerCase();
    return riders.filter(r => 
      `${r.first_name} ${r.last_name}`.toLowerCase().includes(lowerQuery) ||
      r.email?.toLowerCase().includes(lowerQuery) ||
      (r.phone && r.phone.includes(query))
    );
  },
}));

export default useRidersStore;
resetOnSessionChange(useRidersStore);
