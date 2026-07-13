"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { orderService } from "@/services/order.service";
import { deliveryService } from "@/services/delivery.service";
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

export default function RiderOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  // Estados
  const [order, setOrder] = useState<Order | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  
  // Estado para modal de fallo
  const [showFailModal, setShowFailModal] = useState(false);
  const [failReason, setFailReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadOrderData();
  }, [id]);

  const loadOrderData = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await orderService.getById(id);
      
      if (!data) {
        setError("Orden no encontrada");
        return;
      }

      setOrder(data);
      
      // Manejo seguro del objeto delivery (puede venir anidado o ser null)
      const deliveryData = (data as any).delivery || null;
      setDelivery(deliveryData);

    } catch (err: any) {
      console.error("Error cargando orden:", err);
      setError(err.message || "Error al cargar los datos de la orden");
    } finally {
      setLoading(false);
    }
  };

  // Validación de transiciones permitidas
  const canTransitionTo = (target: DeliveryStatus): boolean => {
    if (!delivery) return false;

    switch (delivery.status) {
      case DeliveryStatus.INICIADA:
        return target === DeliveryStatus.EN_PICKUP;
      case DeliveryStatus.EN_PICKUP:
        return target === DeliveryStatus.EN_ROUTE;
      case DeliveryStatus.EN_ROUTE:
        return target === DeliveryStatus.COMPLETE || target === DeliveryStatus.FAILED;
      default:
        return false;
    }
  };

  const handleQuickAction = (newStatus: DeliveryStatus) => {
    if (!delivery) return;

    if (newStatus === DeliveryStatus.FAILED) {
      setShowFailModal(true);
      return;
    }

    executeStatusChange(newStatus);
  };

  const executeStatusChange = async (newStatus: DeliveryStatus, reason?: string) => {
    if (!delivery) return;

    setActionLoading(newStatus);
    try {
      const payload: any = { new_status: newStatus };
      if (reason) payload.failure_reason = reason;

      await deliveryService.updateStatus(delivery.id, payload);
      
      // Recargar datos para obtener el estado actualizado
      await loadOrderData();
      
      alert(`Estado actualizado correctamente a: ${newStatus}`);
    } catch (err: any) {
      console.error("Error actualizando estado:", err);
      alert(err.message || "Error al actualizar el estado de la entrega");
    } finally {
      setActionLoading(null);
      setShowFailModal(false);
      setFailReason("");
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

  // Si la orden está asignada pero AÚN NO hay registro de entrega (caso borde raro)
  if (!delivery) {
    return (
      <div className="container mx-auto p-6 text-center">
        <div className="bg-yellow-50 text-yellow-800 p-6 rounded-lg inline-block max-w-md">
          <Clock className="w-12 h-12 mx-auto mb-4 animate-pulse" />
          <h2 className="text-xl font-bold mb-2">Esperando confirmación</h2>
          <p className="mb-4">
            La orden ha sido asignada, pero el sistema de entregas aún no ha generado tu hoja de ruta.
          </p>
          <p className="text-sm italic">
            Por favor espera unos segundos y recarga la página, o contacta al manager.
          </p>
          <button 
            onClick={() => loadOrderData()}
            className="mt-4 px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700"
          >
            Reintentar Carga
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 max-w-5xl space-y-6 pb-20">
      
      {/* Modal de Reporte de Fallo */}
      {showFailModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
            <div className="bg-red-50 p-4 border-b border-red-100 flex items-center gap-3">
              <AlertCircle className="w-6 h-6 text-red-600" />
              <h3 className="text-lg font-bold text-red-800">Reportar Entrega Fallida</h3>
            </div>
            
            <div className="p-6">
              <p className="text-sm text-gray-600 mb-4">
                Es obligatorio especificar el motivo detallado para procesar el reporte y calcular el bono parcial (si aplica).
              </p>
              
              <textarea
                className="w-full border border-gray-300 rounded-lg p-3 focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none transition-shadow min-h-[120px]"
                placeholder="Describe qué sucedió (ej: Cliente no abre, dirección incorrecta, negocio cerrado...)"
                value={failReason}
                onChange={(e) => setFailReason(e.target.value)}
                autoFocus
              />
              
              <div className="mt-6 flex justify-end gap-3">
                <button
                  onClick={() => {
                    setShowFailModal(false);
                    setFailReason("");
                  }}
                  className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors font-medium"
                >
                  Cancelar
                </button>
                <button
                  onClick={() => executeStatusChange(DeliveryStatus.FAILED, failReason)}
                  disabled={!failReason.trim()}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium flex items-center gap-2"
                >
                  <XCircle className="w-4 h-4" />
                  Confirmar Reporte
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Header de Navegación y Título */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <Link href="/rider/my-orders" className="text-sm text-gray-500 hover:text-primary flex items-center gap-1 mb-2 w-fit">
            ← Volver al listado
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">Orden #{order.id}</h1>
        </div>
        <div className="flex gap-2">
          <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border
            ${order.status === 'ASIGNADO' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-gray-50 text-gray-600 border-gray-200'}
          `}>
            Orden: {order.status}
          </span>
          <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border
            ${delivery.status === 'COMPLETE' ? 'bg-green-50 text-green-700 border-green-200' : 
              delivery.status === 'FAILED' ? 'bg-red-50 text-red-700 border-red-200' :
              delivery.status === 'EN_ROUTE' ? 'bg-blue-50 text-blue-700 border-blue-200' :
              'bg-yellow-50 text-yellow-700 border-yellow-200'}
          `}>
            Entrega: {delivery.status.replace('_', ' ')}
          </span>
        </div>
      </div>

      {/* Panel Principal */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        
        {/* Sección de Acciones Rápidas (Solo si no está completada o fallida) */}
        {delivery.status !== 'COMPLETE' && delivery.status !== 'FAILED' && (
          <div className="bg-gray-50 border-b border-gray-200 p-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <Truck className="w-4 h-4" />
              Acciones de Entrega
            </h3>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {/* Botón: Recolectar */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.EN_PICKUP)}
                disabled={!canTransitionTo(DeliveryStatus.EN_PICKUP) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.EN_PICKUP)
                    ? 'bg-white border-gray-200 hover:border-orange-500 hover:shadow-md cursor-pointer' 
                    : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
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
                  ${canTransitionTo(DeliveryStatus.EN_ROUTE)
                    ? 'bg-white border-gray-200 hover:border-blue-500 hover:shadow-md cursor-pointer' 
                    : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
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
                onClick={() => handleQuickAction(DeliveryStatus.COMPLETE)}
                disabled={!canTransitionTo(DeliveryStatus.COMPLETE) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.COMPLETE)
                    ? 'bg-white border-gray-200 hover:border-green-500 hover:shadow-md cursor-pointer' 
                    : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.COMPLETE) ? 'bg-green-50 group-hover:bg-green-100' : 'bg-gray-200'}`}>
                  <CheckCircle className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.COMPLETE) ? 'text-green-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">Entregado</span>
                {actionLoading === DeliveryStatus.COMPLETE && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-green-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>

              {/* Botón: Reportar Fallo */}
              <button
                onClick={() => handleQuickAction(DeliveryStatus.FAILED)}
                disabled={!canTransitionTo(DeliveryStatus.FAILED) || !!actionLoading}
                className={`group relative flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-200
                  ${canTransitionTo(DeliveryStatus.FAILED)
                    ? 'bg-white border-gray-200 hover:border-red-500 hover:shadow-md cursor-pointer' 
                    : 'bg-gray-100 border-gray-100 opacity-50 cursor-not-allowed'}
                `}
              >
                <div className={`p-3 rounded-full mb-2 transition-colors ${canTransitionTo(DeliveryStatus.FAILED) ? 'bg-red-50 group-hover:bg-red-100' : 'bg-gray-200'}`}>
                  <AlertCircle className={`w-6 h-6 ${canTransitionTo(DeliveryStatus.FAILED) ? 'text-red-600' : 'text-gray-400'}`} />
                </div>
                <span className="font-semibold text-sm text-gray-700">Reportar Fallo</span>
                {actionLoading === DeliveryStatus.FAILED && (
                  <div className="absolute inset-0 bg-white/80 flex items-center justify-center rounded-xl">
                    <div className="animate-spin h-6 w-6 border-2 border-red-500 border-t-transparent rounded-full"></div>
                  </div>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Contenido Principal: Detalles */}
        <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          {/* Columna Izquierda: Ubicaciones */}
          <div className="space-y-6">
            {/* Restaurante */}
            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-orange-500" />
                Punto de Recolección
              </h4>
              <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                <h5 className="font-bold text-lg text-gray-900">{order.restaurant_name}</h5>
                <p className="text-gray-600 mt-1">{order.restaurant_address}</p>
                {order.restaurant_phone && (
                  <a href={`tel:${order.restaurant_phone}`} className="inline-flex items-center gap-2 mt-3 text-sm font-medium text-orange-600 hover:text-orange-700 bg-orange-50 px-3 py-1.5 rounded-lg transition-colors">
                    <Phone className="w-4 h-4" />
                    Llamar al Restaurante
                  </a>
                )}
              </div>
            </div>

            {/* Cliente */}
            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-blue-500" />
                Punto de Entrega
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
                    <Phone className="w-4 h-4" />
                    Llamar al Cliente
                  </a>
                )}
              </div>
            </div>
          </div>

          {/* Columna Derecha: Finanzas y Timeline */}
          <div className="space-y-6">
            
            {/* Resumen Financiero */}
            <div className="bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl p-5 border border-green-100">
              <h4 className="text-xs font-bold text-green-800 uppercase tracking-wider mb-4 flex items-center gap-2">
                <DollarSign className="w-4 h-4" />
                Resumen de Ganancia
              </h4>
              
              <div className="space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-green-700/80">Bono por Entrega Exitosa:</span>
                  <span className="font-bold text-green-900">
                    ${order.rider_delivery_bonus?.toFixed(2) || "0.00"}
                  </span>
                </div>
                
                {delivery.status === 'FAILED' && (
                  <div className="pt-3 border-t border-green-200/50">
                    <p className="text-xs text-red-600 font-medium mb-1 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      Entrega Fallida
                    </p>
                    <p className="text-xs text-gray-600">
                      El pago está sujeto a revisión según el motivo: <br/>
                      <span className="italic">"{delivery.failure_reason}"</span>
                    </p>
                  </div>
                )}

                <div className="pt-4 mt-2 border-t border-green-200/50 flex justify-between items-end">
                  <span className="text-sm font-medium text-green-800">Total Estimado:</span>
                  <span className="text-2xl font-extrabold text-green-700">
                    ${(order.rider_delivery_bonus || 0).toFixed(2)}
                  </span>
                </div>
              </div>
            </div>

            {/* Timeline de Estados */}
            <div>
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Clock className="w-4 h-4" />
                Bitácora de Eventos
              </h4>
              
              <div className="relative border-l-2 border-gray-200 ml-3 space-y-6 pb-2">
                {/* Evento: Iniciada */}
                <div className="relative pl-6">
                  <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 ${['INICIADA', 'EN_PICKUP', 'EN_ROUTE', 'COMPLETE', 'FAILED'].includes(delivery.status) ? 'bg-green-500 border-green-500' : 'bg-white border-gray-300'}`}></div>
                  <p className="text-sm font-medium text-gray-900">Entrega Iniciada</p>
                  <p className="text-xs text-gray-500">{new Date(delivery.created_at).toLocaleTimeString()}</p>
                </div>

                {/* Evento: Pickup */}
                {delivery.picked_up_at ? (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-green-500 border-2 border-green-500"></div>
                    <p className="text-sm font-medium text-gray-900">Pedido Recolectado</p>
                    <p className="text-xs text-gray-500">{new Date(delivery.picked_up_at).toLocaleTimeString()}</p>
                  </div>
                ) : (
                  <div className="relative pl-6 opacity-50">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-gray-300"></div>
                    <p className="text-sm text-gray-500">Esperando recolección...</p>
                  </div>
                )}

                {/* Evento: En Ruta */}
                {delivery.in_route_at ? (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-blue-500 border-2 border-blue-500"></div>
                    <p className="text-sm font-medium text-gray-900">En Ruta a Destino</p>
                    <p className="text-xs text-gray-500">{new Date(delivery.in_route_at).toLocaleTimeString()}</p>
                  </div>
                ) : (
                  <div className="relative pl-6 opacity-50">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-gray-300"></div>
                    <p className="text-sm text-gray-500">Pendiente de salida...</p>
                  </div>
                )}

                {/* Evento: Completado */}
                {delivery.completed_at && (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-green-600 border-2 border-green-600 shadow-lg shadow-green-200"></div>
                    <p className="text-sm font-bold text-green-700">¡Entrega Completada!</p>
                    <p className="text-xs text-gray-500">{new Date(delivery.completed_at).toLocaleTimeString()}</p>
                  </div>
                )}

                {/* Evento: Fallido */}
                {delivery.failed_at && (
                  <div className="relative pl-6">
                    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-red-500 border-2 border-red-500 shadow-lg shadow-red-200"></div>
                    <p className="text-sm font-bold text-red-700">Entrega Fallida</p>
                    <p className="text-xs text-red-600 italic mt-1">Motivo: {delivery.failure_reason}</p>
                    <p className="text-xs text-gray-500">{new Date(delivery.failed_at).toLocaleTimeString()}</p>
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