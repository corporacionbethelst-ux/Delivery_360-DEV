/**
 * Fase 8 - Servicio de Tracking (backend FastAPI: /api/v1/tracking/*)
 *
 * Punto único de acceso REST para el dashboard operativo de mapas.
 * El tiempo real incremental llega por WebSocket (useTrackingWebSocket);
 * este servicio alimenta el estado inicial y sirve como fallback si el
 * WS está caído (polling degradado).
 */
import { api } from '@/lib/api';

export interface ActiveRiderPosition {
  riderId: string;
  name: string;
  status: string;
  lat: number;
  lng: number;
  lastSeenMinutesAgo: number | null;
}

export interface DashboardStats {
  activeCount: number;
  onlineTotal: number;
  staleOver15Min: number;
  avgWaitMinutes: number | null;
}

export interface ActiveRidersResponse {
  riders: ActiveRiderPosition[];
  stats: DashboardStats;
  alerts: unknown[];
}

export const trackingService = {
  /**
   * Última posición conocida de una orden (fallback REST del tracking en vivo).
   */
  async getLiveTracking(orderId: string): Promise<any> {
    return api.get(`/tracking/live/${orderId}`);
  },

  /**
   * Datos agregados para el dashboard manager: riders online, métricas y alertas.
   * @param minutes ventana de frescura de posición (default backend: 5 min)
   * @param bbox    "min_lat,min_lng,max_lat,max_lng" (opcional)
   */
  async getActiveRiders(
    minutes: number = 10,
    bbox?: string
  ): Promise<ActiveRidersResponse> {
    const params = new URLSearchParams({ minutes: String(minutes) });
    if (bbox) params.set('bbox', bbox);
    return api.get(`/tracking/dashboard/active-riders?${params.toString()}`);
  },

  /**
   * Trigger manual de re-optimización batch (VRP) — requiere rol manager+.
   */
  async optimizeRoutes(): Promise<any> {
    return api.post('/tracking/routes/optimize', {});
  },
};
