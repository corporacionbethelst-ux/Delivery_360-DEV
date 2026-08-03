"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { orderService } from "@/services/order.service";
import { deliveryService, FailureCause } from "@/services/delivery.service";
import { Order, Delivery, DeliveryStatus } from "@/types";
import {
  Package,
  Clock,
  DollarSign,
  AlertCircle,
  CheckCircle,
  Truck,
  XCircle,
  MapPin,
  Phone,
  MessageSquare
} from "lucide-react";
import Link from "next/link";

// Definición completa de causas estandarizadas
interface FailureOption {
  value: FailureCause;
  label: string;
  bonificable: boolean;
}

const FAILURE_CAUSES: FailureOption[] = [
  // --- Causas Bonificables (Culpa del Cliente / Externas) ---
  { value: "CLIENTE_NO_ESTA", label: "El cliente no estaba en el lugar", bonificable: true },
  { value: "CLIENTE_NO_CONTESTA", label: "El cliente no contesta llamadas/timbre", bonificable: true },
  { value: "DIRECCION_INCORRECTA", label: "La dirección proporcionada es incorrecta", bonificable: true },
  { value: "DIRECCION_NO_EXISTE", label: "La dirección no existe / No se encuentra", bonificable: true },
  { value: "COMERCIO_CERRADO", label: "El comercio estaba cerrado", bonificable: true },
  { value: "CLIENTE_RECHAZA", label: "El cliente rechazó el pedido", bonificable: true },
  { value: "ZONA_INSEGURA", label: "La zona se tornó insegura", bonificable: true },
  { value: "FUERZA_MAYOR", label: "Fuerza mayor (clima, eventos, etc.)", bonificable: true },
  { value: "EDIFICIO_RESTRINGIDO", label: "Acceso restringido en edificio/conjunto", bonificable: true },

  // --- Causas NO Bonificables (Culpa del Repartidor) ---
  { value: "REPARTIDOR_NO_QUIERE_ENTREGAR", label: "Repartidor no quiere entregar (sin causa justa)", bonificable: false },
  { value: "REPARTIDOR_LLEGO_TARDE", label: "Repartidor llegó tarde", bonificable: false },
  { value: "REPARTIDOR_ERROR_PROPIO", label: "Error operativo del repartidor", bonificable: false },
  { value: "REPARTIDOR_VEHICULO_FALLA", label: "Falla mecánica del vehículo", bonificable: false },
  { value: "REPARTIDOR_SIN_BATERIA", label: "Celular sin batería / Apagado", bonificable: false },
  { value: "OTRO_REPARTIDOR", label: "Entregada por otro repartidor", bonificable: false },
];

// Helper seguro para fechas
const safeDate = (dateVal: string | Date | null | undefined): string => {
  if (!dateVal) return "--:--";
  try {
    return new Date(dateVal).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return "--:--";
  }
};

// Helper para formato de moneda
const formatCurrency = (amount: number) => {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    minimumFractionDigits: 0,
  }).format(amount);
};

export default function RiderOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [order, setOrder] = useState<Order | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const [showFailModal, setShowFailModal] = useState(false);

  // Nuevo estado para causa seleccionada
  const [selectedFailureCause, setSelectedFailureCause] = useState<FailureCause | "">("");
  const [failNotes, setFailNotes] = useState(""); // Opcional: notas adicionales

  const [error, setError] = useState<string | null>(null);

  // Estado calculado para la ganancia
  const [estimatedEarnings, setEstimatedEarnings] = useState<number>(0);
  const [earningsLabel, setEarningsLabel] = useState<string>("Pendiente");

  // Estado para configuración de bonos
  const [isBonusConfigValid, setIsBonusConfigValid] = useState<boolean>(true);
  const [bonusConfigWarning, setBonusConfigWarning] = useState<string | null>(null);

  useEffect(() => {
    loadOrderData();
  }, [id]);

  // Recalcular ganancias cuando cambian delivery u order
  useEffect(() => {
    if (!delivery || !order) {
      setEstimatedEarnings(0);
      setEarningsLabel("Pendiente");
      return;
    }

    let amount = 0;
    let label = "En proceso";

    // Verificar si la configuración de bonos es válida
    const configIsValid = (order as any).is_bonus_config_valid === true;

    if (delivery.status === DeliveryStatus.COMPLETADA) {
      // Si la configuración NO es válida, el monto es 0
      if (!configIsValid) {
        amount = 0;
        label = "Ganancia: $0 (Configuración faltante)";
      } else {
        // Usar el valor real del backend, sin fallback
        amount = (order as any).rider_delivery_bonus ?? 0;
        label = "Ganancia Confirmada";
      }
    } else if (delivery.status === DeliveryStatus.FALLIDA) {
      // Lógica mejorada: Usar el campo failure_cause si existe
      const causeValue = (delivery as any).failure_cause;

      if (causeValue) {
        const option = FAILURE_CAUSES.find(f => f.value === causeValue);
        if (option) {
          if (option.bonificable) {
            // Si la configuración NO es válida, el monto es 0
            if (!configIsValid) {
              amount = 0;
              label = "Bono por Fallo: $0 (Configuración faltante)";
            } else {
              amount = (order as any).rider_failed_attempt_bonus ?? 0;
              label = "Bono por Fallo (Cliente)";
            }
          } else {
            amount = 0;
            label = "Sin Bono (Causa Repartidor)";
          }
        } else {
          // Fallback si el valor no está en nuestra lista local
          amount = 0;
          label = "Causa desconocida (Revisión)";
        }
      } else {
        // Fallback legacy: intentar con issue_type desde delivery o desde order
        const reason = ((delivery as any).issue_type || (order as any).failure_reason || "").toLowerCase();
        const isCustomerFault = ["cliente_no_esta", "direccion_incorrecta", "client"].some(r => reason.includes(r));

        if (isCustomerFault) {
          // Si la configuración NO es válida, el monto es 0
          if (!configIsValid) {
            amount = 0;
            label = "Bono por Fallo: $0 (Configuración faltante)";
          } else {
            amount = (order as any).rider_failed_attempt_bonus ?? 0;
            label = "Bono por Fallo (Legacy)";
          }
        } else {
          amount = 0;
          label = "Sin Bono";
        }
      }
    } else {
      // Estado pendiente/en proceso
      if (!configIsValid) {
        amount = 0;
        label = "Ganancia Proyectada: $0 (Configuración faltante)";
      } else {
        amount = (order as any).rider_delivery_bonus ?? 0;
        label = "Ganancia Proyectada";
      }
    }

    setEstimatedEarnings(amount);
    setEarningsLabel(label);
  }, [delivery, order]);

  const loadOrderData = async () => {
    try {
      setLoading(true);
      setError(null);

      const data = await orderService.getById(id) as unknown as Order;

      if (!data) {
        setError("Orden no encontrada");
        return;
      }

      setOrder(data);
      const deliveryData = (data as any).delivery || null;
      setDelivery(deliveryData ? (deliveryData as Delivery) : null);

      // Capturar estado de configuración de bonos
      setIsBonusConfigValid((data as any).is_bonus_config_valid ?? true);
      setBonusConfigWarning((data as any).bonus_config_warning ?? null);

    } catch (err: any) {
      console.error("Error cargando orden:", err);
      setError(err.message || "Error al cargar los datos de la orden");
    } finally {
      setLoading(false);
    }
  };

  const canTransitionTo = (target: DeliveryStatus): boolean => {
    if (!delivery) return false;

    switch (delivery.status) {
      case DeliveryStatus.INICIADA:
        return target === DeliveryStatus.EN_PICKUP || target === DeliveryStatus.EN_ROUTE;
      case DeliveryStatus.EN_PICKUP:
        return target === DeliveryStatus.EN_ROUTE;
      case DeliveryStatus.EN_ROUTE:
        return target === DeliveryStatus.EN_DESTINO || target === DeliveryStatus.COMPLETADA || target === DeliveryStatus.FALLIDA;
      case DeliveryStatus.EN_DESTINO:
        return target === DeliveryStatus.COMPLETADA || target === DeliveryStatus.FALLIDA;
      default:
        return false;
    }
  };

  const handleQuickAction = (newStatus: DeliveryStatus) => {
    if (!delivery) return;

    if (newStatus === DeliveryStatus.FALLIDA) {
      setShowFailModal(true);
      return;
    }

    executeStatusChange(newStatus);
  };

  const executeStatusChange = async (newStatus: DeliveryStatus, cause?: FailureCause, notes?: string) => {
    if (!delivery) return;

    setActionLoading(newStatus);
    try {
      if (newStatus === DeliveryStatus.FALLIDA) {
        if (!cause) throw new Error("Debes seleccionar una causa para el fallo");
        // Llamada actualizada al servicio
        await deliveryService.failDelivery(delivery.id, cause, notes);
      } else {
        const payload: any = { status: newStatus };
        await deliveryService.updateStatus(delivery.id, payload);
      }

      await loadOrderData();
      alert(`Estado actualizado correctamente a: ${newStatus}`);
    } catch (err: any) {
      console.error("Error actualizando estado:", err);
      alert(err.message || "Error al actualizar el estado de la entrega");
    } finally {
      setActionLoading(null);
      setShowFailModal(false);
      setSelectedFailureCause("");
      setFailNotes("");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="container mx-auto p-6 text-center">
        <div className="bg-red-50 text-red-600 p-6 rounded-lg inline-block">
          <AlertCircle className="w-12 h-12 mx-auto mb-4" />
          <h2 className="text-xl font-bold mb-2">Error al cargar</h2>
          <p>{error || "La orden no existe o no tienes permiso para verla."}</p>
          <button
            onClick={() => router.push('/rider/my-orders')}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Volver a Mis Órdenes
          </button>
        </div>
      </div>
    );
  }

  if (!delivery) {
    return (
      <div className="container mx-auto p-6 text-center">
        <div className="bg-yellow-50 text-yellow-800 p-6 rounded-lg inline-block max-w-md">
          <Clock className="w-12 h-12 mx-auto mb-4 animate-pulse" />
          <h2 className="text-xl font-bold mb-2">Esperando confirmación</h2>
          <p className="mb-4">La orden ha sido asignada, pero el sistema de entregas aún no ha generado tu hoja de ruta.</p>
          <button onClick={() => loadOrderData()} className="mt-4 px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700">
            Reintentar Carga
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 max-w-5xl space-y-6 pb-20">

      {/* Modal de Reporte de Fallo ACTUALIZADO */}
      {showFailModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
            <div className="bg-red-50 p-4 border-b border-red-100 flex items-center gap-3">
              <AlertCircle className="w-6 h-6 text-red-600" />
              <h3 className="text-lg font-bold text-red-800">Reportar Entrega Fallida</h3>
            </div>
            <div className="p-6">
              <p className="text-sm text-gray-600 mb-4">
                Selecciona el motivo exacto. Esto determinará automáticamente si aplica el bono.
                {!isBonusConfigValid && (
                  <span className="block mt-2 text-red-600 font-semibold">
                    ⚠️ La configuración de bonos no está definida. Esta entrega fallida podría registrar $0.
                  </span>
                )}
              </p>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Causa del fallo <span className="text-red-500">*</span>
                  </label>
                  <select
                    className="w-full border border-gray-300 rounded-lg p-3 focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none transition-shadow bg-white"
                    value={selectedFailureCause}
                    onChange={(e) => setSelectedFailureCause(e.target.value as FailureCause)}
                    autoFocus
                  >
                    <option value="">-- Selecciona una opción --</option>
                    {FAILURE_CAUSES.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label} {opt.bonificable ? '(✅ Aplica Bono)' : '(❌ Sin Bono)'}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Notas adicionales (Opcional)
                  </label>
                  <textarea
                    className="w-full border border-gray-300 rounded-lg p-3 focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none transition-shadow min-h-[80px]"
                    placeholder="Detalles extra que ayuden a la revisión..."
                    value={failNotes}
                    onChange={(e) => setFailNotes(e.target.value)}
                  />
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-3">
                <button
                  onClick={() => { setShowFailModal(false); setSelectedFailureCause(""); setFailNotes(""); }}
                  className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors font-medium"
                >
                  Cancelar
                </button>
                <button
                  onClick={() => executeStatusChange(DeliveryStatus.FALLIDA, selectedFailureCause || undefined, failNotes)}
                  disabled={!selectedFailureCause}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium flex items-center gap-2"
                >
                  <XCircle className="w-4 h-4" /> Confirmar Reporte
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <Link href="/rider/my-orders" className="text-sm text-gray-500 hover:text-primary flex items-center gap-1 mb-2 w-fit">
            ← Volver al listado
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">Orden #{order.id}</h1>
        </div>
        <div className="flex gap-2 flex-wrap">
          <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border ${order.status === 'ASIGNADO' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-gray-50 text-gray-600 border-gray-200'}`}>
            Orden: {order.status}
          </span>
          <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border ${
              delivery.status === DeliveryStatus.COMPLETADA ? 'bg-green-50 text-green-700 border-green-200' :
              delivery.status === DeliveryStatus.FALLIDA ? 'bg-red-50 text-red-700 border-red-200' :
              'bg-yellow-50 text-yellow-700 border-yellow-200'
            }`}>
            Entrega: {delivery.status.replace('_', ' ')}
          </span>
        </div>
      </div>

      {/* Panel Principal */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">

        {/* Acciones Rápidas */}
        {delivery.status !== DeliveryStatus.COMPLETADA && delivery.status !== DeliveryStatus.FALLIDA && (
          <div className="bg-gray-50 border-b border-gray-200 p-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <Truck className="w-4 h-4" /> Acciones de Entrega
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {/* Botón: Recolectar */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.EN_PICKUP)}
                disabled={!canTransitionTo(DeliveryStatus.EN_PICKUP) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.EN_PICKUP) ? 'bg-white border-gray-200 hover:border-orange-500 hover:shadow-md cursor-pointer' : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.EN_PICKUP) ? 'bg-orange-50 group-hover:bg-orange-100' : 'bg-gray-200'}`}>
                  <Package className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.EN_PICKUP) ? 'text-orange-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">Recolectar Pedido</span>
                {actionLoading === DeliveryStatus.EN_PICKUP && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-orange-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>

              {/* Botón: En Ruta */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.EN_ROUTE)}
                disabled={!canTransitionTo(DeliveryStatus.EN_ROUTE) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.EN_ROUTE) ? 'bg-white border-gray-200 hover:border-blue-500 hover:shadow-md cursor-pointer' : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.EN_ROUTE) ? 'bg-blue-50 group-hover:bg-blue-100' : 'bg-gray-200'}`}>
                  <Truck className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.EN_ROUTE) ? 'text-blue-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">En Ruta</span>
                {actionLoading === DeliveryStatus.EN_ROUTE && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>

              {/* Botón: Completar */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.COMPLETADA)}
                disabled={!canTransitionTo(DeliveryStatus.COMPLETADA) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.COMPLETADA) ? 'bg-white border-gray-200 hover:border-green-500 hover:shadow-md cursor-pointer' : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.COMPLETADA) ? 'bg-green-50 group-hover:bg-green-100' : 'bg-gray-200'}`}>
                  <CheckCircle className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.COMPLETADA) ? 'text-green-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">Entregado</span>
                {actionLoading === DeliveryStatus.COMPLETADA && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-green-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>

              {/* Botón: Reportar Fallo */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.FALLIDA)}
                disabled={!canTransitionTo(DeliveryStatus.FALLIDA) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.FALLIDA) ? 'bg-white border-gray-200 hover:border-red-500 hover:shadow-md cursor-pointer' : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.FALLIDA) ? 'bg-red-50 group-hover:bg-red-100' : 'bg-gray-200'}`}>
                  <AlertCircle className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.FALLIDA) ? 'text-red-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">Reportar Fallo</span>
                {actionLoading === DeliveryStatus.FALLIDA && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-red-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Contenido Principal */}
        <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-8">

          {/* Columna Izquierda: Ubicaciones */}
          <div className="space-y-6">
            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-orange-500" /> Punto de Recolección
              </h4>
              <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                <h5 className="font-bold text-lg text-gray-900">{order.restaurant_name}</h5>
                <p className="text-gray-600 mt-1">{order.restaurant_address}</p>
                {order.restaurant_phone && (
                  <a href={`tel:${order.restaurant_phone}`} className="inline-flex items-center gap-2 mt-3 text-sm font-medium text-orange-600 hover:text-orange-700 bg-orange-50 px-3 py-1.5 rounded-lg transition-colors">
                    <Phone className="w-4 h-4" /> Llamar al Restaurante
                  </a>
                )}
              </div>
            </div>

            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-blue-500" /> Punto de Entrega
              </h4>
              <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                <h5 className="font-bold text-lg text-gray-900">{order.customer_name}</h5>
                <p className="text-gray-600 mt-1">{order.delivery_address}</p>

                {order.delivery_instructions && (
                  <div className="mt-4 pt-4 border-t border-gray-200">
                    <div className="flex items-start gap-2">
                      <MessageSquare className="w-4 h-4 text-gray-400 mt-0.5 shrink-0" />
                      <p className="text-sm text-gray-700 italic bg-white p-2 rounded border border-gray-100">
                        "{order.delivery_instructions}"
                      </p>
                    </div>
                  </div>
                )}

                {order.customer_phone && (
                  <a href={`tel:${order.customer_phone}`} className="inline-flex items-center gap-2 mt-3 text-sm font-medium text-blue-600 hover:text-blue-700 bg-blue-50 px-3 py-1.5 rounded-lg transition-colors">
                    <Phone className="w-4 h-4" /> Llamar al Cliente
                  </a>
                )}
              </div>
            </div>
          </div>

          {/* Columna Derecha: Finanzas y Timeline */}
          <div className="space-y-6">

            {/* Alerta de Configuración Faltante (si aplica) */}
            {!isBonusConfigValid && bonusConfigWarning && (
              <div className="bg-red-50 border-2 border-red-300 rounded-xl p-5 shadow-md">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-6 h-6 text-red-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-bold text-red-800 mb-1">
                      ⚠️ Configuración de Bonos No Válida
                    </h4>
                    <p className="text-xs text-red-700 leading-relaxed">
                      {bonusConfigWarning}
                    </p>
                    <p className="text-xs text-red-700 mt-2 font-semibold">
                      Esta transacción registra $0 hasta que el administrador configure los valores base.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Resumen Financiero ACTUALIZADO */}
            <div className={`rounded-xl p-5 border ${!isBonusConfigValid ? 'bg-gray-50 border-gray-200' : 'bg-gradient-to-br from-green-50 to-emerald-50 border-green-100'}`}>
              <h4 className={`text-xs font-bold uppercase tracking-wider mb-4 flex items-center gap-2 ${!isBonusConfigValid ? 'text-gray-600' : 'text-green-800'}`}>
                <DollarSign className="w-4 h-4" /> Resumen de Ganancia
              </h4>

              <div className="space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className={!isBonusConfigValid ? 'text-gray-600' : 'text-green-700/80'}>{earningsLabel}:</span>
                  <span className={`font-bold text-lg ${!isBonusConfigValid ? 'text-gray-900' : 'text-green-900'}`}>
                    {formatCurrency(estimatedEarnings)}
                  </span>
                </div>

                {delivery.status === DeliveryStatus.FALLIDA && (
                  <div className={`pt-3 border-t ${!isBonusConfigValid ? 'border-gray-200' : 'border-green-200/50'}`}>
                    <p className="text-xs text-red-600 font-medium mb-1 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" /> Entrega Fallida
                    </p>

                    {/* Mostrar causa estandarizada si existe */}
                    {(delivery as any).failure_cause ? (
                      <div className="text-xs text-gray-700">
                        <span className="font-semibold">Causa:</span>{' '}
                        <span className="italic font-medium block mt-1 bg-white p-2 rounded border border-gray-200">
                          {FAILURE_CAUSES.find(f => f.value === (delivery as any).failure_cause)?.label || (delivery as any).failure_cause}
                        </span>
                      </div>
                    ) : (
                      <p className="text-xs text-gray-600">
                        Motivo registrado: <br/>
                        <span className="italic font-semibold">"{(delivery as any).issue_type || (order as any).failure_reason || 'Sin especificar'}"</span>
                      </p>
                    )}

                    {/* Lógica visual de bono */}
                    {(() => {
                       const causeValue = (delivery as any).failure_cause;
                       const option = causeValue ? FAILURE_CAUSES.find(f => f.value === causeValue) : null;

                       if (option) {
                         return option.bonificable ? (
                           <p className={`text-xs mt-2 font-bold flex items-center gap-1 ${!isBonusConfigValid ? 'text-gray-500' : 'text-green-700'}`}>
                             {isBonusConfigValid ? <CheckCircle className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                             {isBonusConfigValid ? '✅ Aplica bono por fallo externo.' : '⚠️ Bono no disponible (Configuración faltante).'}
                           </p>
                         ) : (
                           <p className="text-xs text-orange-700 mt-2 font-bold flex items-center gap-1">
                             <AlertCircle className="w-3 h-3" /> ⚠️ No aplica bono (Causa operativa).
                           </p>
                         );
                       }

                       // Fallback legacy: intentar con issue_type desde delivery o desde order
                       const reason = ((delivery as any).issue_type || (order as any).failure_reason || "").toLowerCase();
                       const isCustomerFault = ["cliente_no_esta", "direccion_incorrecta", "client"].some(r => reason.includes(r));
                       return isCustomerFault ? (
                         <p className={`text-xs mt-2 font-bold ${!isBonusConfigValid ? 'text-gray-500' : 'text-green-700'}`}>
                           {isBonusConfigValid ? '✅ Aplica bono (Legacy).' : '⚠️ Bono no disponible (Configuración faltante).'}
                         </p>
                       ) : (
                         <p className="text-xs text-orange-700 mt-2 font-bold">⚠️ Sujeto a revisión.</p>
                       );
                    })()}
                  </div>
                )}

                <div className={`pt-4 mt-2 border-t ${!isBonusConfigValid ? 'border-gray-200' : 'border-green-200/50'} flex justify-between items-end`}>
                  <span className={`text-sm font-medium ${!isBonusConfigValid ? 'text-gray-700' : 'text-green-800'}`}>Total a Pagar:</span>
                  <span className={`text-2xl font-extrabold ${!isBonusConfigValid ? 'text-gray-900' : 'text-green-700'}`}>
                    {formatCurrency(estimatedEarnings)}
                  </span>
                </div>
              </div>
            </div>

            {/* Timeline de Estados */}
            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Clock className="w-4 h-4" /> Bitácora de Eventos
              </h4>

              <div className="relative border-l-2 border-gray-200 ml-3 space-y-6 pb-2">
                {/* Evento: Iniciada */}
                <div className="relative pl-6">
                  <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 ${delivery.started_at ? 'bg-green-500 border-green-500' : 'bg-white border-gray-300'}`}></div>
                  <p className="text-sm font-medium text-gray-900">Entrega Iniciada</p>
                  <p className="text-xs text-gray-500">{safeDate(delivery.started_at)}</p>
                </div>

                {/* Evento: Llegada a Pickup */}
                <div className="relative pl-6">
                  <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 ${delivery.arrived_pickup_at ? 'bg-orange-500 border-orange-500' : 'bg-white border-gray-300'}`}></div>
                  <p className={`text-sm font-medium ${delivery.arrived_pickup_at ? 'text-gray-900' : 'text-gray-400'}`}>Llegada al Restaurante</p>
                  <p className="text-xs text-gray-500">{safeDate(delivery.arrived_pickup_at)}</p>
                </div>

                {/* Evento: Salida de Pickup (Recolectado) */}
                <div className="relative pl-6">
                  <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 ${delivery.left_pickup_at ? 'bg-green-500 border-green-500' : 'bg-white border-gray-300'}`}></div>
                  <p className={`text-sm font-medium ${delivery.left_pickup_at ? 'text-gray-900' : 'text-gray-400'}`}>Pedido Recolectado</p>
                  <p className="text-xs text-gray-500">{safeDate(delivery.left_pickup_at)}</p>
                </div>

                {/* Evento: En Ruta */}
                {delivery.status === DeliveryStatus.EN_ROUTE || delivery.status === DeliveryStatus.EN_DESTINO || delivery.status === DeliveryStatus.COMPLETADA || delivery.status === DeliveryStatus.FALLIDA ? (
                   <div className="relative pl-6">
                     <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-blue-500 border-2 border-blue-500"></div>
                     <p className="text-sm font-medium text-gray-900">En Ruta a Destino</p>
                     <p className="text-xs text-gray-500">{safeDate(delivery.left_pickup_at || delivery.updatedAt)}</p>
                   </div>
                ) : (
                  <div className="relative pl-6 opacity-50">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-gray-300"></div>
                    <p className="text-sm text-gray-500">Pendiente de salida...</p>
                  </div>
                )}

                {/* Evento: Completado */}
                {delivery.status === DeliveryStatus.COMPLETADA && (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-green-600 border-2 border-green-600 shadow-lg shadow-green-200"></div>
                    <p className="text-sm font-bold text-green-700">¡Entrega Completada!</p>
                    <p className="text-xs text-gray-500">{safeDate(delivery.completed_at)}</p>
                  </div>
                )}

                {/* Evento: Fallido */}
                {delivery.status === DeliveryStatus.FALLIDA && (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-red-500 border-2 border-red-500 shadow-lg shadow-red-200"></div>
                    <p className="text-sm font-bold text-red-700">Entrega Fallida</p>
                    <p className="text-xs text-red-600 italic mt-1">
                      {(delivery as any).failure_cause
                        ? FAILURE_CAUSES.find(f => f.value === (delivery as any).failure_cause)?.label
                        : ((delivery as any).issue_type || (order as any).failure_reason || 'Sin especificar')}
                    </p>
                    <p className="text-xs text-gray-500">{safeDate(delivery.updatedAt)}</p>
                  </div>
                )}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}