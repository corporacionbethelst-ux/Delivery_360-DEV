"use client";
import { showAlert, toast } from "@/lib/feedback";
import { confirmAction } from "@/lib/feedback";

import { canAssignOrder, orderView } from "@/lib/order-view";
import { isCancellationReasonValid } from "@/lib/delivery-status";
import React, {
  useState,
  useEffect,
  useRef,
  useSyncExternalStore,
} from "react";
import {
  getCredentialGeneration,
  onCredentialsChanged,
  getStoredTokens,
} from "@/lib/auth-session";
import { capturePrivateTask } from "@/lib/private-task";
import { useAuthStore } from "@/stores/authStore";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Plus,
  Search,
  Download,
  Package,
  Clock,
  Trash2,
  Eye,
  AlertCircle,
  Truck,
  Zap,
  CheckCircle,
  MapPin,
  RefreshCw,
} from "lucide-react";
import type { OperationalHttpOrder } from "@/lib/operational-catalog";
import { orderService, OrderStatus } from "@/services/order.service";
import { riderService } from "@/services/rider.service";
import { vehicleService, Vehicle } from "@/services/vehicle.service";
import { payoutAmountLabel } from "@/lib/payout-contract";
import { downloadCSV } from "@/lib/csv-export";
import { OrderSkeleton } from "@/components/loaders/OrderSkeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Rider } from "@/types/user";

export default function OrdersPage() {
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  const { user } = useAuthStore();
  return (
    <SessionOrdersPage
      key={JSON.stringify([generation, user?.id, user?.role])}
    />
  );
}

const reference = (value: unknown): string =>
  typeof value === "string" && value.trim()
    ? value
    : value == null
      ? "No registrado"
      : "Referencia no válida";

function loadFailure(error: unknown): string {
  const e = error as {
    message?: unknown;
    status?: unknown;
    response?: { status?: unknown; data?: { detail?: unknown } };
  } | null;
  const status = e?.response?.status ?? e?.status;
  const detail = e?.response?.data?.detail;
  const reason =
    typeof detail === "string"
      ? detail
      : typeof e?.message === "string"
        ? e.message
        : "Vuelve a intentarlo.";
  return `${typeof status === "number" ? `HTTP ${status}: ` : ""}${reason}`;
}

function SessionOrdersPage() {
  const requestSequence = useRef(0);
  useEffect(
    () => () => {
      requestSequence.current++;
    },
    [],
  );
  const router = useRouter();
  const [orders, setOrders] = useState<OperationalHttpOrder[]>([]);
  const [riders, setRiders] = useState<Rider[]>([]);
  const [companyVehicles, setCompanyVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [filterRider, setFilterRider] = useState<string>("ALL");
  const [searchTerm, setSearchTerm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ridersError, setRidersError] = useState<string | null>(null);
  const [vehiclesError, setVehiclesError] = useState<string | null>(null);
  const [ridersLoading, setRidersLoading] = useState(true);

  const [isRefreshing, setIsRefreshing] = useState(false);

  // Estados para Cancelación
  const [orderToCancel, setOrderToCancel] = useState<{
    id: string;
    externalId: string;
  } | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelling, setCancelling] = useState(false);

  // Estados para Asignación
  const [orderToAssign, setOrderToAssign] =
    useState<OperationalHttpOrder | null>(null);
  const [selectedRiderId, setSelectedRiderId] = useState<string>("");
  const [orderToReview, setOrderToReview] =
    useState<OperationalHttpOrder | null>(null);
  const [assigningAuto, setAssigningAuto] = useState(false);
  const [assigningManual, setAssigningManual] = useState(false);
  const [orderToDeliver, setOrderToDeliver] = useState<OperationalHttpOrder | null>(null);
  const [deliveryOtp, setDeliveryOtp] = useState("");
  const [delivering, setDelivering] = useState(false);
  const deliveryPending = useRef(false);
  const quickStatusPending = useRef(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  useEffect(() => {
    fetchInitialData();
  }, []);

  const fetchInitialData = async () => {
    if (!getStoredTokens().accessToken) {
      setLoading(false);
      return;
    }
    const request = ++requestSequence.current;
    const task = capturePrivateTask();
    const current = () =>
      request === requestSequence.current && task.isCurrent();
    setLoading(true);
    setError(null);
    setRidersLoading(true);
    setRidersError(null);
    setVehiclesError(null);
    // Orders must remain visible even when an auxiliary catalog is unavailable.
    const ordersRequest = orderService
      .getOperationalList({ limit: 100 })
      .then((ordersData) => {
        if (current()) {
          setOrders(ordersData);
          setOrderToAssign((previous) =>
            previous
              ? (ordersData.find(
                  (row) => row.id === previous.id && !row.assignment_review,
                ) ?? null)
              : null,
          );
          setOrderToCancel((previous) =>
            previous &&
            ordersData.some(
              (row) => row.id === previous.id && !row.assignment_review,
            )
              ? previous
              : null,
          );
          setOrderToReview((previous) =>
            previous
              ? (ordersData.find(
                  (row) => row.id === previous.id && !!row.assignment_review,
                ) ?? null)
              : null,
          );
        }
      })
      .catch((err: unknown) => {
        if (!current()) return;
        console.error("Error fetching orders:", err);
        setError(`No se pudieron cargar las órdenes. ${loadFailure(err)}`);
      })
      .finally(() => {
        if (current()) {
          setLoading(false);
          setIsRefreshing(false);
        }
      });
    const ridersRequest = riderService
      .listRiders({ status_filter: "ACTIVO" })
      .then((ridersData) => {
        if (current()) setRiders(ridersData);
      })
      .catch((err: unknown) => {
        if (!current()) return;
        setRiders([]);
        setSelectedRiderId("");
        setRidersError(
          `No se pudieron cargar los repartidores. ${loadFailure(err)}`,
        );
      })
      .finally(() => {
        if (current()) setRidersLoading(false);
      });
    const vehiclesRequest = vehicleService
      .getAvailableCompanyVehicles()
      .then((vehiclesData) => {
        if (current()) setCompanyVehicles(vehiclesData);
      })
      .catch((err: unknown) => {
        if (!current()) return;
        setCompanyVehicles([]);
        setVehiclesError(
          `No se pudieron cargar los vehículos de empresa. ${loadFailure(err)}`,
        );
      });
    await Promise.allSettled([ordersRequest, ridersRequest, vehiclesRequest]);
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await fetchInitialData();
  };

  // --- Lógica de Cancelación ---
  const handleDeleteClick = (id: string, externalId: string) => {
    if (error || orders.find((order) => order.id === id)?.assignment_review)
      return;
    setOrderToCancel({ id, externalId });
    setCancelReason("");
  };

  const confirmCancel = async () => {
    if (
      !orderToCancel ||
      cancelling ||
      error ||
      orders.find((order) => order.id === orderToCancel.id)
        ?.assignment_review ||
      !isCancellationReasonValid(cancelReason)
    )
      return;
    setCancelling(true);
    const task = capturePrivateTask();
    try {
      await orderService.cancel(orderToCancel.id, cancelReason.trim());
      task.assertCurrent();

      await fetchInitialData();
      task.assertCurrent();
      setOrderToCancel(null);
    } catch (err: any) {
      if (!task.isCurrent()) return;
      showAlert(
        "Error al cancelar: " + (err.response?.data?.detail || err.message),
      );
    } finally {
      if (task.isCurrent()) setCancelling(false);
    }
  };

  // --- Lógica de Asignación ---
  const canOfferAssignment = (order: OperationalHttpOrder) =>
    !error &&
    !order.assignment_review &&
    (canAssignOrder(orderView(order)) ||
      (order.status === "ASIGNADO" &&
        !!order.assigned_rider_id &&
        order.delivery?.status === "INICIADA"));

  const handleAssignClick = (order: OperationalHttpOrder) => {
    if (!canOfferAssignment(order)) return;
    setOrderToAssign(order);
    setSelectedRiderId(order.assigned_rider_id || "");
  };

  const performAutoAssign = async () => {
    if (
      !orderToAssign ||
      error ||
      orderToAssign.assignment_review ||
      !canAssignOrder(orderView(orderToAssign))
    )
      return;
    setAssigningAuto(true);
    const task = capturePrivateTask();
    try {
      const result = await orderService.assignRiderAuto(orderToAssign.id);
      task.assertCurrent();
      toast.success(`${result.message}\nAsignado a: ${result.assigned_rider.name}`);

      await fetchInitialData();
      task.assertCurrent();
      setOrderToAssign(null);
      setSelectedRiderId("");
    } catch (err: any) {
      if (!task.isCurrent()) return;
      showAlert(
        "Error en asignación automática: " +
          (err.response?.data?.detail || err.message),
      );
    } finally {
      if (task.isCurrent()) setAssigningAuto(false);
    }
  };

  const performManualAssign = async () => {
    if (
      !orderToAssign ||
      !selectedRiderId ||
      ridersLoading ||
      ridersError ||
      !canOfferAssignment(orderToAssign)
    )
      return;
    setAssigningManual(true);
    const task = capturePrivateTask();
    try {
      await orderService.assignRider(orderToAssign.id, selectedRiderId);
      task.assertCurrent();
      toast.success("Orden asignada correctamente");

      await fetchInitialData();
      task.assertCurrent();
      setOrderToAssign(null);
      setSelectedRiderId("");
    } catch (err: any) {
      if (!task.isCurrent()) return;
      showAlert("Error al asignar: " + (err.response?.data?.detail || err.message));
    } finally {
      if (task.isCurrent()) setAssigningManual(false);
    }
  };

  // --- Lógica de Cambio de Estado Rápido ---
  const handleQuickStatusChange = async (
    orderId: string,
    nextStatus: OrderStatus,
  ) => {
    if (
      error ||
      orders.find((order) => order.id === orderId)?.assignment_review
    )
      return;
    if (nextStatus === "ENTREGADO") {
      const order = orders.find((item) => item.id === orderId);
      if (!order || order.status !== "EN_RUTA") return;
      setDeliveryOtp("");
      setDeliveryError(null);
      setOrderToDeliver(order);
      return;
    }
    if (quickStatusPending.current) return;
    quickStatusPending.current = true;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      if (!(await confirmAction(`¿Cambiar estado a ${nextStatus.replaceAll("_", " ")}?`)) || !task.isCurrent()) return;
      await orderService.updateStatus(orderId, nextStatus);
      task.assertCurrent();
      await fetchInitialData();
      task.assertCurrent();
    } catch (err: any) {
      if (!task?.isCurrent()) return;
      showAlert(
        "Error al actualizar estado: " +
          (err.response?.data?.detail || err.message),
      );
    } finally {
      quickStatusPending.current = false;
    }
  };

  const confirmDelivery = async (checkOnly = false) => {
    if (!orderToDeliver || deliveryPending.current || error) return;
    deliveryPending.current = true;
    setDelivering(true);
    setDeliveryError(null);
    const task = capturePrivateTask();
    try {
      const confirmed = checkOnly
        ? await orderService.getById(orderToDeliver.id)
        : await orderService.updateStatus(orderToDeliver.id, "ENTREGADO", deliveryOtp);
      task.assertCurrent();
      if (confirmed.status !== "ENTREGADO") {
        setDeliveryError(`Estado confirmado: ${confirmed.status.replaceAll("_", " ").toLowerCase()}. La orden todavía no consta como entregada.`);
        return;
      }
      setDeliveryOtp("");
      setOrderToDeliver(null);
      toast.success("Entrega registrada correctamente.");
      await fetchInitialData();
    } catch (err: unknown) {
      if (task.isCurrent()) setDeliveryError(loadFailure(err).replace(/^HTTP \d+: /, ""));
    } finally {
      deliveryPending.current = false;
      if (task.isCurrent()) setDelivering(false);
    }
  };

  const handleExport = () => {
    const dataToExport = filteredOrders.map((o) => ({
      ID: o.external_id || o.id,
      Revision_asignacion:
        o.assignment_review ?? "Sin inconsistencias detectadas",
      Repartidor_orden: reference(o.assigned_rider_id),
      Repartidor_entrega: reference(o.delivery?.rider_id),
      Estado: o.status,
      Cliente: o.customer_name || "N/A",
      Rider: getRiderName(o),
      Vehiculo: getRiderVehicle(o),
      Total: o.total ?? o.total_amount ?? "No informado",
      Fecha: new Date(o.created_at).toLocaleDateString(),
    }));
    downloadCSV(dataToExport, "reporte_ordenes");
  };

  const filteredOrders = orders.filter((order) => {
    const matchesStatus =
      filterStatus === "ALL" || order.status === filterStatus;
    const matchesRider =
      filterRider === "ALL" ||
      (filterRider === "UNASSIGNED"
        ? !order.assigned_rider_id
        : order.assigned_rider_id === filterRider);
    const customerName = order.customer_name || "Cliente General";
    const riderName = getRiderName(order);
    const matchesSearch =
      (order.external_id || order.id)
        .toLowerCase()
        .includes(searchTerm.toLowerCase()) ||
      customerName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (order.delivery_address || "")
        .toLowerCase()
        .includes(searchTerm.toLowerCase()) ||
      riderName.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesStatus && matchesRider && matchesSearch;
  });

  function getRiderName(order: OperationalHttpOrder): string {
    if (order.assignment_review) return "Asignación por revisar";
    // Intentar primero con order.rider
    const rider = (order.assigned_rider ?? order.rider) as any;
    if (rider?.full_name) return rider.full_name;
    const fullName =
      `${rider?.first_name || ""} ${rider?.last_name || ""}`.trim();
    if (fullName) return fullName;

    // Si no hay datos en order.rider pero hay assigned_rider_id, buscar en el array riders
    if (order.assigned_rider_id && riders.length > 0) {
      const foundRider = riders.find((r) => r.id === order.assigned_rider_id);
      if (foundRider) {
        return (
          `${foundRider.first_name} ${foundRider.last_name}`.trim() ||
          "Repartidor asignado"
        );
      }
    }

    // Fallback final
    return order.assigned_rider_id ? "Repartidor asignado" : "Sin asignar";
  }

  function getRiderVehicle(order: OperationalHttpOrder): string {
    if (order.assignment_review) return "Vehículo sin confirmar";
    // Intentar primero con order.rider (vehículo propio)
    const rider = (order.assigned_rider ?? order.rider) as any;

    // Verificar si tiene vehículo propio
    const directVehicle = [rider?.vehicle_type, rider?.vehicle_plate]
      .filter(Boolean)
      .join(" ");
    if (directVehicle && rider?.vehicle_ownership_type !== "EMPRESA") {
      return `🏠 ${directVehicle}`;
    }

    // Si el rider tiene vehicle_ownership_type === 'EMPRESA' o no tiene vehículo propio,
    // buscar el vehículo de empresa asignado mediante assigned_vehicle_id
    const assignedVehicleId =
      rider?.assigned_vehicle_id || rider?.assignedVehicleId;
    if (assignedVehicleId && companyVehicles.length > 0) {
      const assignedVehicle = companyVehicles.find(
        (v) => v.id === assignedVehicleId,
      );
      if (assignedVehicle) {
        return `🏢 ${assignedVehicle.type} ${assignedVehicle.plate}`;
      }
    }

    // Fallback: buscar en lista de riders del estado
    if (order.assigned_rider_id && riders.length > 0) {
      const foundRider = riders.find((r) => r.id === order.assigned_rider_id);
      if (foundRider) {
        // Verificar si tiene vehículo propio
        const foundDirect = [foundRider.vehicle_type, foundRider.vehicle_plate]
          .filter(Boolean)
          .join(" ");
        if (foundDirect && foundRider.vehicle_ownership_type !== "EMPRESA") {
          return `🏠 ${foundDirect}`;
        }

        // Verificar si tiene vehículo de empresa asignado
        const foundAssignedId =
          foundRider.assigned_vehicle_id ||
          (foundRider as any).assignedVehicleId;
        if (foundAssignedId && companyVehicles.length > 0) {
          const assignedV = companyVehicles.find(
            (v) => v.id === foundAssignedId,
          );
          if (assignedV) {
            return `🏢 ${assignedV.type} ${assignedV.plate}`;
          }
        }
      }
    }

    return order.assigned_rider_id
      ? "Vehículo no especificado"
      : "Sin vehículo";
  }

  function getRiderBadgeClass(order: OperationalHttpOrder): string {
    if (order.assignment_review)
      return "bg-amber-50 text-amber-900 border-amber-200";
    if (!order.assigned_rider_id)
      return "bg-gray-100 text-gray-600 border-gray-200";

    // Intentar obtener is_online de order.rider
    const rider = (order.assigned_rider ?? order.rider) as any;
    if (rider?.is_online)
      return "bg-emerald-50 text-emerald-700 border-emerald-200";

    // Si no está en order.rider, buscar en el array riders
    if (riders.length > 0) {
      const foundRider = riders.find((r) => r.id === order.assigned_rider_id);
      if (foundRider?.is_online)
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
    }

    return "bg-blue-50 text-blue-700 border-blue-200";
  }

  const getStatusColor = (status: OrderStatus) => {
    switch (status) {
      case "ENTREGADO":
        return "bg-green-100 text-green-800 border-green-200";
      case "PENDIENTE":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "ASIGNADO":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "EN_RUTA":
        return "bg-purple-100 text-purple-800 border-purple-200";
      case "CANCELADO":
        return "bg-red-100 text-red-800 border-red-200 line-through opacity-75";
      case "FALLIDO":
        return "bg-orange-100 text-orange-800 border-orange-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const getNextActions = (status: OrderStatus): OrderStatus[] => {
    switch (status) {
      case "PENDIENTE":
        return ["ASIGNADO"];
      case "ASIGNADO":
        return ["RECOLECTADO"];
      case "RECOLECTADO":
        return ["EN_RUTA"];
      case "EN_RUTA":
        return ["ENTREGADO", "FALLIDO"];
      default:
        return [];
    }
  };

  return (
    <div className="p-3 sm:p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex min-w-0 flex-col xl:flex-row justify-between items-start xl:items-center gap-5 mb-6 rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-violet-50 p-4 sm:p-6 shadow-sm">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-blue-700">
              <Package className="h-4 w-4 shrink-0" aria-hidden="true" />
              Operaciones · Pedidos
            </div>
            <h1 className="text-2xl font-bold text-gray-900">
              Gestión de Órdenes
            </h1>
            <p className="text-gray-500 mt-1">
              Administra, asigna y rastrea pedidos.
            </p>
          </div>
          <div role="group" aria-label="Acciones de órdenes" className="grid w-full min-w-0 grid-cols-2 gap-2 sm:flex sm:flex-wrap xl:w-auto">
            <Button
              variant="outline"
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="h-11 gap-2"
            >
              <RefreshCw
                className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`}
              />
              Actualizar
            </Button>

            <Button
              variant="outline"
              onClick={handleExport}
              disabled={loading || !!error || orders.length === 0}
              className="h-11"
            >
              <Download className="w-4 h-4 mr-2" /> Exportar
            </Button>
            <Button
              onClick={() => router.push("/manager/operations/orders/new")}
              className="col-span-2 h-11 bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-200"
            >
              <Plus className="w-4 h-4 mr-2" /> Nueva Orden
            </Button>
          </div>
        </div>

        {error && (
          <Alert
            variant="destructive"
            className="mb-6 bg-red-50 border-red-200"
          >
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchInitialData}
              className="ml-auto"
            >
              Reintentar
            </Button>
          </Alert>
        )}
        {(ridersError || vehiclesError) && (
          <Alert className="mb-6 border-amber-200 bg-amber-50 text-amber-900">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="space-y-1">
              {ridersError && (
                <p>{ridersError} La asignación manual queda pendiente.</p>
              )}
              {vehiclesError && <p>{vehiclesError}</p>}
              <p>La consulta de órdenes continúa disponible.</p>
              <Button variant="outline" size="sm" onClick={fetchInitialData}>
                Reintentar catálogos
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {orders.some((order) => order.assignment_review) && (
          <Alert className="mb-6 border-amber-200 bg-amber-50 text-amber-900">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {orders.filter((order) => order.assignment_review).length}{" "}
              {orders.filter((order) => order.assignment_review).length === 1
                ? "orden requiere"
                : "órdenes requieren"}{" "}
              revisión de asignación. Sus datos siguen visibles; sus acciones
              quedan bloqueadas.
            </AlertDescription>
          </Alert>
        )}
        {/* Filtros */}
        <Card className="mb-6 shadow-sm">
          <CardContent className="p-4 flex min-w-0 flex-col xl:flex-row gap-4 items-center justify-between">
            <div className="relative w-full min-w-0 xl:flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="text"
                placeholder="Buscar por ID, cliente, dirección o rider..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                aria-label="Buscar órdenes"
                className="h-11 w-full min-w-0 pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              />
            </div>
            <div role="group" aria-label="Filtros de órdenes" className="grid w-full min-w-0 grid-cols-1 gap-2 lg:grid-cols-2 xl:w-auto">
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                aria-label="Estado de la orden"
                className="h-11 w-full min-w-0 px-3 py-2 border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option value="ALL">Todos los estados</option>
                <option value="PENDIENTE">Pendientes</option>
                <option value="ASIGNADO">Asignados</option>
                <option value="RECOLECTADO">Recolectados</option>
                <option value="EN_RUTA">En Ruta</option>
                <option value="ENTREGADO">Entregados</option>
                <option value="FALLIDO">Fallidos</option>
                <option value="CANCELADO">Cancelados</option>
              </select>
              <select
                value={filterRider}
                onChange={(e) => setFilterRider(e.target.value)}
                aria-label="Repartidor asignado"
                className="h-11 w-full min-w-0 px-3 py-2 border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option value="ALL">Todos los riders</option>
                <option value="UNASSIGNED">Sin asignar</option>
                {riders.map((rider) => (
                  <option key={rider.id} value={rider.id}>
                    {rider.first_name} {rider.last_name}
                  </option>
                ))}
              </select>
            </div>
          </CardContent>
        </Card>

        {/* Lista */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <OrderSkeleton key={i} />
            ))}
          </div>
        ) : error && orders.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-gray-600">
              El listado no está disponible. Reintenta la consulta indicada
              arriba.
            </CardContent>
          </Card>
        ) : filteredOrders.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-gray-500">
              <Package className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No se encontraron órdenes.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredOrders.map((order) => {
              const nextActions: OrderStatus[] =
                error || order.assignment_review
                  ? []
                  : getNextActions(order.status);

              const hasRider = !!order.assigned_rider_id;
              const showAssignButton = canOfferAssignment(order);

              return (
                <Card
                  key={order.id}
                  role="article"
                  aria-label={`Orden ${order.external_id || order.id}`}
                  className={`group hover:shadow-lg transition-all duration-200 border border-gray-100 relative overflow-hidden ${order.status === "CANCELADO" ? "opacity-60 grayscale" : order.status === "FALLIDO" ? "opacity-75 border-orange-200 bg-orange-50/30" : ""}`}
                >
                  <div
                    className={`h-1.5 w-full ${
                      order.status === "ENTREGADO"
                        ? "bg-green-500"
                        : order.status === "CANCELADO"
                          ? "bg-red-500"
                          : order.status === "FALLIDO"
                            ? "bg-orange-500"
                            : order.status === "EN_RUTA"
                              ? "bg-purple-500"
                              : "bg-blue-500"
                    }`}
                  />

                  <CardHeader className="pb-3">
                    <div className="flex justify-between items-start mb-2">
                      <Badge
                        className={`${getStatusColor(order.status)} border font-semibold`}
                      >
                        {order.status}
                      </Badge>
                      <span className="text-xs text-gray-400 font-mono">
                        #{order.external_id || order.id}
                      </span>
                    </div>
                    <CardTitle
                      className="text-lg cursor-pointer group-hover:text-blue-600 transition-colors"
                      onClick={() =>
                        order.assignment_review
                          ? setOrderToReview(order)
                          : router.push(
                              `/manager/operations/orders/${order.id}`,
                            )
                      }
                    >
                      {order.customer_name || "Cliente General"}
                    </CardTitle>
                  </CardHeader>

                  <CardContent className="space-y-3">
                    <div className="flex items-start gap-2 text-sm text-gray-600">
                      <Clock className="w-4 h-4 mt-0.5 text-gray-400 shrink-0" />
                      <span>
                        {typeof order.created_at === "string" &&
                        Number.isFinite(Date.parse(order.created_at))
                          ? new Date(order.created_at).toLocaleString()
                          : "Fecha no informada"}
                      </span>
                    </div>
                    <div className="flex items-start gap-2 text-sm text-gray-600">
                      <MapPin className="w-4 h-4 mt-0.5 text-gray-400 shrink-0" />
                      <span className="line-clamp-2">
                        {order.delivery_address}
                      </span>
                    </div>

                    <div
                      className={`text-xs px-2 py-2 rounded border flex items-start gap-2 ${getRiderBadgeClass(order)}`}
                    >
                      <Truck className="w-3 h-3 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <p className="font-semibold truncate">
                          {getRiderName(order)}
                        </p>
                        <p className="opacity-80 truncate">
                          {getRiderVehicle(order)}
                        </p>
                      </div>
                    </div>

                    {order.assignment_review && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                        <p className="font-semibold">Revisión de asignación</p>
                        <p className="mt-1">{order.assignment_review}</p>
                        <p className="mt-1">
                          Consulta disponible · cambios bloqueados
                        </p>
                      </div>
                    )}
                    <div className="pt-3 border-t flex justify-between items-center">
                      <span className="text-xs text-gray-500">Total</span>
                      <span className="font-bold text-lg text-gray-900">
                        {order.total !== undefined && order.total !== null
                          ? payoutAmountLabel(
                              order.total,
                              order.currency ?? undefined,
                            )
                          : order.total_amount !== undefined &&
                              order.total_amount !== null
                            ? payoutAmountLabel(
                                order.total_amount,
                                order.currency ?? undefined,
                              )
                            : "No informado"}
                      </span>
                    </div>

                    <div className="flex gap-2 pt-2 mt-2 flex-wrap">
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1 text-xs"
                        onClick={() =>
                          order.assignment_review
                            ? setOrderToReview(order)
                            : router.push(
                                `/manager/operations/orders/${order.id}`,
                              )
                        }
                      >
                        <Eye className="w-3 h-3 mr-1" /> Ver
                      </Button>

                      {showAssignButton && (
                        <Dialog
                          open={orderToAssign?.id === order.id}
                          onOpenChange={(isOpen) => {
                            if (!isOpen) {
                              setOrderToAssign(null);
                              setSelectedRiderId("");
                            }
                          }}
                        >
                          <DialogTrigger asChild>
                            <Button
                              size="sm"
                              variant={hasRider ? "secondary" : "default"}
                              className="text-xs"
                              onClick={() => handleAssignClick(order)}
                            >
                              <Truck className="w-3 h-3 mr-1" />{" "}
                              {hasRider ? "Reasignar" : "Asignar"}
                            </Button>
                          </DialogTrigger>

                          <DialogContent className="sm:max-w-[425px]">
                            <DialogHeader>
                              <DialogTitle>
                                {hasRider ? "Reasignar" : "Asignar"} Orden #
                                {order.external_id || order.id}
                              </DialogTitle>
                              <DialogDescription>
                                {hasRider
                                  ? "Cambia el repartidor actual por otro disponible."
                                  : "Elige un repartidor disponible o usa la asignación automática."}
                              </DialogDescription>
                            </DialogHeader>

                            <div className="py-4 space-y-4">
                              {!hasRider && order.status === "PENDIENTE" && (
                                <div className="bg-indigo-50 p-3 rounded-lg border border-indigo-100">
                                  <Button
                                    onClick={performAutoAssign}
                                    disabled={assigningAuto}
                                    className="w-full bg-indigo-600 hover:bg-indigo-700 text-white"
                                  >
                                    {assigningAuto ? (
                                      <>
                                        <div className="animate-spin mr-2 h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                                        Buscando repartidor cercano...
                                      </>
                                    ) : (
                                      <>
                                        <Zap className="w-4 h-4 mr-2" />{" "}
                                        Asignación Automática (Más cercano)
                                      </>
                                    )}
                                  </Button>
                                </div>
                              )}

                              <div className="relative flex py-2 items-center">
                                <div className="flex-grow border-t border-gray-200"></div>
                                <span className="flex-shrink-0 mx-4 text-gray-400 text-xs uppercase">
                                  O selecciona manualmente
                                </span>
                                <div className="flex-grow border-t border-gray-200"></div>
                              </div>

                              <div className="space-y-2">
                                <Label htmlFor="rider-select-manual">
                                  Repartidor Disponible
                                </Label>
                                <Select
                                  value={selectedRiderId}
                                  onValueChange={(val) =>
                                    setSelectedRiderId(val)
                                  }
                                  disabled={ridersLoading || !!ridersError}
                                >
                                  <SelectTrigger
                                    id="rider-select-manual"
                                    className="w-full"
                                  >
                                    <SelectValue placeholder="Selecciona un repartidor..." />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {riders.length === 0 ? (
                                      <div className="p-2 text-sm text-gray-500 text-center">
                                        {ridersLoading
                                          ? "Consultando repartidores…"
                                          : ridersError
                                            ? "Catálogo de repartidores no disponible"
                                            : "No hay repartidores activos disponibles"}
                                      </div>
                                    ) : (
                                      riders.map((r) => (
                                        <SelectItem key={r.id} value={r.id}>
                                          {r.first_name} {r.last_name} -{" "}
                                          {r.vehicle_type || "Vehículo"}
                                        </SelectItem>
                                      ))
                                    )}
                                  </SelectContent>
                                </Select>
                              </div>
                            </div>

                            <DialogFooter className="gap-2 sm:gap-0">
                              <Button
                                type="button"
                                variant="outline"
                                onClick={() => {
                                  setOrderToAssign(null);
                                  setSelectedRiderId("");
                                }}
                              >
                                Cancelar
                              </Button>
                              <Button
                                onClick={performManualAssign}
                                disabled={
                                  !selectedRiderId ||
                                  assigningManual ||
                                  ridersLoading ||
                                  !!ridersError ||
                                  riders.length === 0
                                }
                              >
                                {assigningManual ? "Asignando..." : "Confirmar"}
                              </Button>
                            </DialogFooter>
                          </DialogContent>
                        </Dialog>
                      )}

                      {nextActions.map((nextStatus) => (
                        <Button
                          key={nextStatus}
                          size="sm"
                          variant="outline"
                          className="text-green-600 border-green-200 hover:bg-green-50"
                          onClick={() =>
                            handleQuickStatusChange(order.id, nextStatus)
                          }
                        >
                          <CheckCircle className="w-3 h-3 mr-1" />{" "}
                          {nextStatus.replace("_", " ")}
                        </Button>
                      ))}

                      {!error &&
                        !order.assignment_review &&
                        order.status !== "CANCELADO" &&
                        order.status !== "ENTREGADO" &&
                        order.status !== "FALLIDO" && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="text-red-600 hover:bg-red-50 hover:text-red-700 border-red-200"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteClick(order.id, order.external_id);
                            }}
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      <Dialog
        open={!!orderToReview}
        onOpenChange={(open) => {
          if (!open) setOrderToReview(null);
        }}
      >
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Revisión de asignación</DialogTitle>
            <DialogDescription>
              Datos registrados de la orden. Los vínculos no se modifican ni se
              elige automáticamente un repartidor.
            </DialogDescription>
          </DialogHeader>
          {orderToReview && (
            <div className="space-y-4 text-sm">
              <p className="font-semibold">
                {orderToReview.external_id || orderToReview.id} ·{" "}
                {orderToReview.customer_name || "Cliente no informado"}
              </p>
              <p>{orderToReview.delivery_address}</p>
              <dl className="space-y-3">
                {[
                  ["ID de la orden", orderToReview.id],
                  ["Estado registrado", orderToReview.status],
                  [
                    "Repartidor asignado en la orden",
                    orderToReview.assigned_rider_id,
                  ],
                  ["Alias rider_id de la orden", orderToReview.rider_id],
                  ["Relación assigned_rider", orderToReview.assigned_rider?.id],
                  ["Relación rider", orderToReview.rider?.id],
                  ["ID de la entrega", orderToReview.delivery?.id],
                  [
                    "Repartidor de la entrega",
                    orderToReview.delivery?.rider_id,
                  ],
                ].map(([label, value]) => (
                  <div
                    key={String(label)}
                    className="rounded-lg border bg-slate-50 p-3"
                  >
                    <dt className="text-xs text-slate-500">{label}</dt>
                    <dd className="mt-1 break-all font-mono">
                      {reference(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="rounded-lg bg-amber-50 p-3 text-amber-900">
                Revisa la asignación antes de realizar cambios. El historial y
                los importes permanecen intactos.
              </p>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOrderToReview(null)}>
              Cerrar revisión
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!orderToDeliver} onOpenChange={(open) => {
        if (!open && !deliveryPending.current) {
          setOrderToDeliver(null);
          setDeliveryOtp("");
          setDeliveryError(null);
        }
      }}>
        <DialogContent className="w-[calc(100vw-2rem)] sm:w-full sm:max-w-md max-h-[90dvh] overflow-y-auto border-blue-100">
          <DialogHeader>
            <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
              <CheckCircle className="h-6 w-6" />
            </div>
            <DialogTitle>Confirmar entrega</DialogTitle>
            <DialogDescription>
              Orden #{orderToDeliver?.external_id || orderToDeliver?.id.slice(0, 8)}. Confirma la recepción antes de marcarla como entregada.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-900">
              Si la entrega requiere OTP, solicita el código al destinatario. El servidor verificará el código antes de completar la orden.
            </div>
            <div className="space-y-2">
              <Label htmlFor="delivery-otp">OTP de entrega (si corresponde)</Label>
              <Input id="delivery-otp" value={deliveryOtp} onChange={(event) => setDeliveryOtp(event.target.value)}
                autoComplete="one-time-code" maxLength={128} disabled={delivering}
                aria-invalid={!!deliveryError} aria-describedby="delivery-otp-help" />
              <p id="delivery-otp-help" className="text-xs text-slate-500">Conserva los ceros iniciales. Si no se configuró OTP, puedes confirmar sin código.</p>
            </div>
            {deliveryError && <Alert variant="destructive"><AlertDescription>{deliveryError}</AlertDescription></Alert>}
          </div>
          <DialogFooter className="gap-2">
            {deliveryError && <Button variant="outline" disabled={delivering} onClick={() => void confirmDelivery(true)}>Consultar estado</Button>}
            <Button variant="outline" disabled={delivering} onClick={() => {
              setOrderToDeliver(null); setDeliveryOtp(""); setDeliveryError(null);
            }}>Volver</Button>
            <Button className="bg-emerald-600 hover:bg-emerald-700" disabled={delivering || !!error} onClick={() => void confirmDelivery()}>
              {delivering ? "Confirmando..." : "Confirmar entrega"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* Diálogo de Cancelación */}
      <Dialog
        open={!!orderToCancel}
        onOpenChange={() => setOrderToCancel(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              ¿Cancelar Orden #{orderToCancel?.externalId}?
            </DialogTitle>
            <DialogDescription>
              Esta acción cambiará el estado a <strong>CANCELADO</strong>.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <label className="text-sm font-medium mb-2 block">
              Motivo obligatorio (8 a 500 caracteres)
            </label>
            <Textarea
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              placeholder="..."
              className="w-full"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOrderToCancel(null)}>
              Volver
            </Button>
            <Button
              variant="destructive"
              onClick={confirmCancel}
              disabled={cancelling || !isCancellationReasonValid(cancelReason)}
            >
              {cancelling ? "Cancelando..." : "Confirmar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
