"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import {
  DollarSign,
  Package,
  MapPin,
  TrendingUp,
  Clock,
  Bike,
  AlertCircle,
  Wifi,
  WifiOff,
  Loader2,
  RefreshCw,
  Phone,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { riderService } from "@/services/rider.service";
import { riderExactService } from "@/services/rider-earnings-exact.service";
import { cashText } from "@/lib/customer-cashbook";
import { capturePrivateTask } from "@/lib/private-task";
import { PayoutSessionBoundary } from "@/components/financial/PayoutSessionBoundary";
import { payoutAmountLabel } from "@/lib/payout-contract";

import { orderService, Order } from "@/services/order.service";
import { resolveOrderCollectAmount } from "@/lib/order-amount";

// --- Constantes y Configuración ---
const ACTIVE_DELIVERY_STATUSES = [
  "ASIGNADO",
  "EN_RECOLECCION",
  "RECOLECTADO",
  "EN_RUTA",
];
const HEARTBEAT_INTERVAL_MS = 15000;

const collectLabel = (order: Order): string =>
  order.pricing
    ? cashText(order.pricing.total, "USD")
    : payoutAmountLabel(
        resolveOrderCollectAmount(order),
        order.currency ?? undefined,
      );

// Opciones de Geolocalización
const INITIAL_GEOLOCATION_OPTIONS: PositionOptions = {
  enableHighAccuracy: true,
  timeout: 20000,
  maximumAge: 30000,
};

const FALLBACK_GEOLOCATION_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  timeout: 15000,
  maximumAge: 120000,
};

const WATCH_GEOLOCATION_OPTIONS: PositionOptions = {
  enableHighAccuracy: true,
  timeout: 20000,
  maximumAge: 30000,
};

const getGeolocationErrorMessage = (err: GeolocationPositionError): string => {
  if (err.code === 1)
    return "Permiso de ubicación denegado. Actívalo para conectarte.";
  if (err.code === 2)
    return "No se pudo obtener ubicación. Verifica GPS o datos.";
  if (err.code === 3)
    return "La ubicación tardó demasiado. Intenta nuevamente.";
  return "Error al obtener ubicación.";
};

export default function RiderDashboard() {
  return (
    <PayoutSessionBoundary>
      <PrivateRiderDashboard />
    </PayoutSessionBoundary>
  );
}
function PrivateRiderDashboard() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();

  // Estados de Datos
  const [earnings, setEarnings] = useState<{
    today: string | null;
    week: string | null;
    pending: string | null;
  }>({ today: null, week: null, pending: null });
  const [moneyError, setMoneyError] = useState<string | null>(null);
  const alive = useRef(false),
    sequence = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const [nextDelivery, setNextDelivery] = useState<Order | null>(null);
  const [completedToday, setCompletedToday] = useState(0);
  const [loadingData, setLoadingData] = useState(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  // Estados de UI
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  // Estados de Geolocalización
  const [riderId, setRiderId] = useState<string | null>(null);
  const [isOnline, setIsOnline] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [sendingLocation, setSendingLocation] = useState(false);

  const watchIdRef = useRef<number | null>(null);
  const lastHeartbeatSentAtRef = useRef(0);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Función de Carga de Datos
  const loadDashboardData = async () => {
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      (!task || task.isCurrent());
    setLoadingData(true);
    setDashboardError(null);

    try {
      task = capturePrivateTask();
      const [profileResult, earningsResult, balanceResult, ordersResult] =
        await Promise.allSettled([
          riderService.getProfile(),
          riderExactService.report(user!.id),
          riderExactService.balance(user!.id),
          orderService.getAll({ limit: 100 }),
        ]);

      task.assertCurrent();
      if (!current()) return;
      if (profileResult.status === "rejected") throw profileResult.reason;
      const profile = profileResult.value,
        orders = ordersResult.status === "fulfilled" ? ordersResult.value : [];
      setRiderId(profile.id);
      setIsOnline(Boolean(profile.is_online));
      const report =
        earningsResult.status === "fulfilled" ? earningsResult.value : null;
      const balance =
        balanceResult.status === "fulfilled" ? balanceResult.value : null;
      if (
        (report && report.rider_id !== profile.id) ||
        (balance && balance.rider_id !== profile.id)
      )
        throw new Error("La respuesta financiera pertenece a otra cuenta");
      setEarnings({
        today: report?.day.credit_usd ?? null,
        week: report?.week.credit_usd ?? null,
        pending: balance?.available ?? null,
      });
      setCompletedToday(report?.day.completed_delivery_count ?? 0);
      setMoneyError(
        report && balance
          ? null
          : "No se pudieron confirmar todas las cifras USD. Las órdenes no se usan para inventar ganancias o disponibilidad.",
      );

      const activeOrders = orders
        .filter((order) => ACTIVE_DELIVERY_STATUSES.includes(order.status))
        .sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
        );
      setNextDelivery(activeOrders[0] ?? null);
    } catch (error) {
      if (!current()) return;
      console.error("Error cargando datos del dashboard:", error);
      setDashboardError("No se pudieron cargar tus datos. Revisa tu conexión.");
      setEarnings({ today: null, week: null, pending: null });
      setCompletedToday(0);
      setNextDelivery(null);
    } finally {
      if (current()) setLoadingData(false);
    }
  };

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== "REPARTIDOR") {
      router.push("/login");
      return;
    }

    loadDashboardData();

    return () => {
      if (watchIdRef.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current);
      }
    };
  }, [user?.id, user?.role, isAuthenticated, router, isMounted]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadDashboardData();
    setIsRefreshing(false);
  };

  const forceOffline = async () => {
    setIsOnline(false);
    if (watchIdRef.current !== null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    if (riderId) {
      try {
        await riderService.toggleOnline(riderId, false);
      } catch (e) {
        console.error(e);
      }
    }
  };

  const sendLocation = async (
    lat: number,
    lng: number,
    options: { force?: boolean; showLoading?: boolean } = {},
  ): Promise<boolean> => {
    if (!riderId) return false;
    const now = Date.now();
    if (
      !options.force &&
      now - lastHeartbeatSentAtRef.current < HEARTBEAT_INTERVAL_MS
    )
      return true;

    try {
      if (options.showLoading) setSendingLocation(true);
      await riderService.sendHeartbeat(riderId, lat, lng);
      lastHeartbeatSentAtRef.current = now;
      setLocationError(null);
      return true;
    } catch (error: any) {
      const status = error?.response?.status;
      setLocationError(
        status === 429
          ? "Demasiadas solicitudes. Espera."
          : "Error al actualizar ubicación.",
      );
      if (status !== 429) await forceOffline();
      return false;
    } finally {
      if (options.showLoading) setSendingLocation(false);
    }
  };

  const toggleOnlineMode = async () => {
    if (isOnline) {
      if (watchIdRef.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      setIsOnline(false);
      if (riderId)
        riderService.toggleOnline(riderId, false).catch(console.error);
      return;
    }

    if (!navigator.geolocation) {
      setLocationError("Geolocalización no soportada");
      void forceOffline();
      return;
    }
    if (!riderId) {
      setLocationError("Cargando perfil...");
      return;
    }

    setLocationError(null);
    setSendingLocation(true);

    try {
      let position: GeolocationPosition;
      try {
        position = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(
            resolve,
            reject,
            INITIAL_GEOLOCATION_OPTIONS,
          ),
        );
      } catch (firstError) {
        const geolocationError = firstError as GeolocationPositionError;
        if (geolocationError.code !== 3) throw geolocationError;
        position = await new Promise((resolve, reject) =>
          navigator.geolocation.getCurrentPosition(
            resolve,
            reject,
            FALLBACK_GEOLOCATION_OPTIONS,
          ),
        );
      }

      const { latitude, longitude } = position.coords;
      const canGoOnline = await sendLocation(latitude, longitude, {
        force: true,
        showLoading: true,
      });
      if (!canGoOnline) return;

      setIsOnline(true);
      const id = navigator.geolocation.watchPosition(
        (pos) => sendLocation(pos.coords.latitude, pos.coords.longitude),
        (err) => {
          setLocationError(getGeolocationErrorMessage(err));
          void forceOffline();
        },
        WATCH_GEOLOCATION_OPTIONS,
      );
      watchIdRef.current = id;
    } catch (error) {
      setLocationError(
        getGeolocationErrorMessage(error as GeolocationPositionError),
      );
      await forceOffline();
    } finally {
      setSendingLocation(false);
    }
  };

  const nextDeliveryCode = useMemo(() => {
    if (!nextDelivery) return "";
    return nextDelivery.external_id || nextDelivery.id.slice(0, 8);
  }, [nextDelivery]);

  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin h-12 w-12 text-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Cargando panel...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Panel de Control Superior (Sin saludo repetido, enfocado en acción) */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white p-4 rounded-xl border shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Panel de Control</h2>
          <p className="text-sm text-gray-500 flex items-center gap-2 mt-1">
            {isOnline ? (
              <>
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
                </span>
                <span className="text-green-700 font-medium">
                  En línea - Recibiendo ubicaciones
                </span>
              </>
            ) : (
              <>
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400"></span>
                <span className="text-gray-500">Desconectado</span>
              </>
            )}
          </p>
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="gap-2 bg-white"
          >
            <RefreshCw
              className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`}
            />
            {isRefreshing ? "Actualizando..." : "Actualizar"}
          </Button>
          <Button
            onClick={toggleOnlineMode}
            variant={isOnline ? "destructive" : "default"}
            disabled={sendingLocation || !riderId}
            className={
              isOnline
                ? "bg-red-600 hover:bg-red-700"
                : "bg-green-600 hover:bg-green-700"
            }
          >
            {sendingLocation ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : isOnline ? (
              <WifiOff className="w-4 h-4 mr-2" />
            ) : (
              <Wifi className="w-4 h-4 mr-2" />
            )}
            {sendingLocation
              ? "Obteniendo ubicación..."
              : isOnline
                ? "Desconectarse"
                : "Conectarse"}
          </Button>
        </div>
      </div>

      {/* Alertas de Error */}
      {(locationError || dashboardError || moneyError) && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3 animate-in fade-in slide-in-from-top-2">
          <AlertCircle className="w-5 h-5 text-red-600 mt-0.5" />
          <div>
            <h3 className="font-semibold text-red-800">Atención</h3>
            <p className="text-sm text-red-700">
              {locationError || dashboardError || moneyError}
            </p>
          </div>
        </div>
      )}

      {/* Tarjetas de Métricas */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-gradient-to-br from-green-50 to-white border-green-200 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-sm font-medium text-green-800">Ganado Hoy</p>
                <h3 className="text-3xl font-bold text-green-900 mt-1">
                  {earnings.today === null
                    ? "Por confirmar"
                    : cashText(earnings.today)}
                </h3>
              </div>
              <DollarSign className="w-6 h-6 text-green-600" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-green-700 flex items-center">
              <TrendingUp className="w-3 h-3 mr-1" />{" "}
              {earnings.today === null
                ? "Abonos por confirmar"
                : `${completedToday} abonos de entrega registrados hoy`}
            </p>
          </CardContent>
        </Card>

        <Card className="border-t-4 border-t-blue-500 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-sm font-medium text-gray-500">
                  Últimos 7 días
                </p>
                <h3 className="text-2xl font-bold text-gray-900 mt-1">
                  {earnings.week === null
                    ? "Por confirmar"
                    : cashText(earnings.week)}
                </h3>
              </div>
              <Package className="w-6 h-6 text-blue-600" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-gray-500">
              Créditos registrados en el libro USD · últimos 7 días
            </p>
          </CardContent>
        </Card>

        <Card className="border-t-4 border-t-purple-500 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-sm font-medium text-gray-500">
                  Disponible para Retiro
                </p>
                <h3 className="text-2xl font-bold text-gray-900 mt-1">
                  {earnings.pending === null
                    ? "Por confirmar"
                    : cashText(earnings.pending)}
                </h3>
              </div>
              <Clock className="w-6 h-6 text-purple-600" />
            </div>
          </CardHeader>
          <CardContent>
            <Button
              variant="link"
              className="p-0 h-auto text-xs text-purple-600 font-semibold"
              onClick={() => router.push("/rider/earnings")}
            >
              Ver ganancias →
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Sección Inferior: Próxima Entrega y Accesos Rápidos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="shadow-md border-l-4 border-l-blue-600">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MapPin className="w-5 h-5 text-blue-600" /> Próxima Entrega
            </CardTitle>
          </CardHeader>
          <CardContent>
            {nextDelivery ? (
              <div className="space-y-4">
                <div className="flex justify-between items-start">
                  <div>
                    <Badge className="mb-2 bg-blue-100 text-blue-800 border-blue-200">
                      {nextDelivery.status}
                    </Badge>
                    <h3 className="font-bold text-lg text-gray-900">
                      Orden #{nextDeliveryCode}
                    </h3>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-gray-500">Monto a cobrar</p>
                    <p className="font-bold text-green-600">
                      {collectLabel(nextDelivery)}
                    </p>
                  </div>
                </div>

                <div className="bg-gray-50 p-3 rounded-lg border border-gray-100">
                  <p className="text-xs text-gray-500 uppercase font-semibold mb-1">
                    Dirección
                  </p>
                  <p className="text-sm font-medium text-gray-900">
                    {nextDelivery.delivery_address}
                  </p>
                </div>

                <div className="flex gap-2">
                  <Button
                    className="flex-1 bg-blue-600 hover:bg-blue-700"
                    onClick={() =>
                      router.push(`/rider/my-orders/${nextDelivery.id}`)
                    }
                  >
                    Ver Ruta
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => {
                      const address = encodeURIComponent(
                        nextDelivery.delivery_address,
                      );
                      window.open(
                        `https://www.google.com/maps/search/?api=1&query=${address}`,
                        "_blank",
                      );
                    }}
                  >
                    <MapPin className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                <Bike className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>No tienes entregas asignadas ahora mismo.</p>
                <p className="text-xs mt-2">
                  Conéctate y espera nuevas asignaciones.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Gestión Rápida</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Button
              variant="outline"
              className="h-24 flex flex-col gap-2 hover:bg-green-50 hover:border-green-200"
              onClick={() => router.push("/rider/earnings")}
            >
              <DollarSign className="w-6 h-6 text-green-600" />
              <span className="text-sm font-medium">Mis Ganancias</span>
            </Button>
            <Button
              variant="outline"
              className="h-24 flex flex-col gap-2 hover:bg-blue-50 hover:border-blue-200"
              onClick={() => router.push("/rider/profile")}
            >
              <Bike className="w-6 h-6 text-blue-600" />
              <span className="text-sm font-medium">Mi Perfil</span>
            </Button>
            <Button
              variant="outline"
              className="h-24 flex flex-col gap-2 hover:bg-orange-50 hover:border-orange-200"
              onClick={() => router.push("/rider/notifications")}
            >
              <Clock className="w-6 h-6 text-orange-600" />
              <span className="text-sm font-medium">Notificaciones</span>
            </Button>
            <Button
              variant="outline"
              className="h-24 flex flex-col gap-2 hover:bg-purple-50 hover:border-purple-200"
              onClick={() => router.push("/rider/productivity")}
            >
              <TrendingUp className="w-6 h-6 text-purple-600" />
              <span className="text-sm font-medium">Productividad</span>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
