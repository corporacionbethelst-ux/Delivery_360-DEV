'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { orderService, Order } from '@/services/order.service';
import { ArrowLeft, MapPin, Phone, Package, DollarSign, Clock, Loader2, AlertCircle, ExternalLink, CheckCircle, XCircle, Bike, Truck } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatCurrency } from '@/lib/formatters';
import { resolveOrderCollectAmount } from '@/lib/order-amount';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

// --- CORRECCIÓN DEL ERROR DE TIPO ---
// Extendemos la interfaz Order localmente para incluir la propiedad 'delivery'
// que viene del backend pero no está definida en el tipo base del frontend.
interface DeliveryData {
  id: string;
  status: string;
  rider_id?: string;
  started_at?: string;
  completed_at?: string;
}

interface OrderWithDelivery extends Order {
  delivery?: DeliveryData;
}
// ------------------------------------

export default function OrderDetailPage() {
  const router = useRouter();
  const params = useParams();
  const orderId = (params?.id as string) || ''; 

  const { user, isAuthenticated } = useAuthStore();
  
  // Usamos la interfaz corregida aquí
  const [order, setOrder] = useState<OrderWithDelivery | null>(null);
  const [loading, setLoading] = useState(true);
  const [isMounted, setIsMounted] = useState(false);
  
  // Estados para acciones del repartidor
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [selectedIssueType, setSelectedIssueType] = useState('');
  const [issueDescription, setIssueDescription] = useState('');
  const [showFailDialog, setShowFailDialog] = useState(false);

  // Motivos de fallo atribuibles al cliente (generan pago - FASE 2)
  const customerFaultReasons = [
    { value: 'cliente_no_esta', label: 'Cliente no está en la dirección' },
    { value: 'direccion_incorrecta', label: 'Dirección incorrecta o no existe' },
    { value: 'cliente_rechaza', label: 'Cliente rechaza el pedido' },
    { value: 'otro_cliente', label: 'Otro motivo atribuible al cliente' },
  ];

  // Motivos de fallo NO atribuibles al cliente (no generan pago)
  const riderFaultReasons = [
    { value: 'vehiculo_descompuesto', label: 'Vehículo descompuesto' },
    { value: 'accidente', label: 'Accidente o emergencia' },
    { value: 'rider_no_quiere', label: 'Repartidor no quiere continuar' },
  ];

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    const allowedRoles = ['REPARTIDOR', 'SUPERADMIN', 'GERENTE', 'OPERADOR'];
    if (!allowedRoles.includes(user.role)) {
      router.push('/login');
      return;
    }

    if (!orderId) return;

    const fetchOrder = async () => {
      setLoading(true);
      try {
        const data = await orderService.getById(orderId);
        setOrder(data);
      } catch (error) {
        console.error('Error fetching order:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchOrder();
  }, [orderId, isMounted, isAuthenticated, user, router]);

  /**
   * Función principal para actualizar el estado de la entrega.
   * Conecta con el endpoint PATCH /api/v1/deliveries/{id}/status
   */
  const updateDeliveryStatus = async (status: string, issueType?: string, description?: string) => {
    setUpdatingStatus(true);
    try {
      // Obtener el delivery_id de la orden
      // Prioridad: delivery.id (si existe relación) > order.id (fallback si es la misma entidad)
      const deliveryId = order?.delivery?.id || order?.id;
      
      if (!deliveryId) {
        alert('No se pudo identificar la entrega asociada a esta orden.');
        return;
      }

      // Construir payload según el schema DeliveryStatusUpdate del backend
      const payload: any = {
        status, // Ej: 'RECOLECTADO', 'EN_RUTA', 'ENTREGADO', 'FALLIDO'
        lat: undefined, // Opcional: se podría agregar geolocalización aquí si se desea
        lng: undefined,
      };

      // Solo enviar datos de incidencia si es un fallo
      if (status === 'FALLIDO') {
        if (!issueType) {
          throw new Error('El motivo del fallo es requerido');
        }
        payload.issue_type = issueType;
        payload.issue_description = description || '';
      }

      // Petición al backend
      const response = await fetch(`/api/v1/deliveries/${deliveryId}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${typeof window !== 'undefined' ? localStorage.getItem('token') : ''}`,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Error al actualizar estado');
      }

      const updatedDelivery = await response.json();
      
      // Actualizar estado local optimista
      setOrder(prev => prev ? {
        ...prev,
        // Actualizamos el estado general de la orden para reflejar cambios visuales inmediatos
        status: status === 'ENTREGADO' ? 'ENTREGADO' : status === 'FALLIDO' ? 'CANCELADO' : prev.status,
        delivery: updatedDelivery,
      } : null);

      // Feedback al usuario
      const successMessage = status === 'FALLIDO' 
        ? 'Incidencia reportada correctamente. El bono correspondiente se está procesando.' 
        : `Estado actualizado exitosamente a: ${status}`;
        
      alert(successMessage);
      
      // Limpiar formulario de incidencias
      setShowFailDialog(false);
      setSelectedIssueType('');
      setIssueDescription('');
      
      // Recargar la página para asegurar que toda la UI (badges, tarjetas) esté sincronizada con el backend
      setTimeout(() => window.location.reload(), 1000);
      
    } catch (error: any) {
      console.error('Error updating status:', error);
      alert(`Error: ${error.message}`);
    } finally {
      setUpdatingStatus(false);
    }
  };

  /**
   * Determina qué botones mostrar según el estado actual de la entrega.
   * Mapea los estados del backend a acciones de UI.
   */
  const getAvailableActions = () => {
    // Ahora TypeScript sabe que order.delivery puede existir gracias a OrderWithDelivery
    if (!order?.delivery) return [];
    
    const deliveryStatus = order.delivery.status;
    const actions = [];

    // Lógica de transición de estados basada en el backend
    switch (deliveryStatus) {
      case 'INICIADA':
        // Paso 1: El repartidor confirma que recogió el pedido
        actions.push({ key: 'RECOLECTADO', label: '✅ Pedido Recolectado', icon: CheckCircle, variant: 'default' as const });
        break;
      
      case 'EN_PICKUP':
        // Paso 2: El repartidor sale del restaurante hacia el cliente
        actions.push({ key: 'EN_RUTA', label: '🚗 En Ruta a Entrega', icon: Truck, variant: 'default' as const });
        break;
      
      case 'EN_ROUTE':
        // Paso 3: Llegó a destino. Puede entregar o reportar problema.
        actions.push(
          { key: 'ENTREGADO', label: '✅ Marcar como Entregado', icon: CheckCircle, variant: 'success' as const },
          { key: 'FALLIDO', label: '❌ Reportar Incidencia', icon: XCircle, variant: 'destructive' as const }
        );
        break;
      
      case 'EN_DESTINO':
        // Variante de paso 3 (si el backend usa este estado intermedio)
        actions.push(
          { key: 'ENTREGADO', label: '✅ Confirmar Entrega', icon: CheckCircle, variant: 'success' as const },
          { key: 'FALLIDO', label: '❌ Reportar Problema', icon: XCircle, variant: 'destructive' as const }
        );
        break;
      
      default:
        // Estados finales (COMPLETADA, FALLIDA) o inválidos no muestran acciones
        break;
    }

    return actions;
  };

  if (!isMounted || !isAuthenticated || !user || loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin h-12 w-12 text-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Cargando detalles...</p>
        </div>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="p-6 flex flex-col items-center justify-center min-h-screen bg-gray-50">
        <AlertCircle className="w-16 h-16 text-red-400 mb-4" />
        <h2 className="text-xl font-bold text-gray-900 mb-2">Orden no encontrada</h2>
        <Button onClick={() => router.back()} variant="outline">Volver</Button>
      </div>
    );
  }

  // Función para abrir mapa
  const handleOpenMap = () => {
    if (!order.delivery_address) return;
    const address = encodeURIComponent(order.delivery_address);
    // Abre Google Maps en una nueva pestaña
    window.open(`https://www.google.com/maps/search/?api=1&query=${address}`, '_blank');
  };

  // Función para llamar al cliente
  const handleCallCustomer = () => {
    // Prioridad: Contacto de entrega -> Teléfono del cliente -> Teléfono del restaurante (fallback)
    const phoneNumber = order.delivery_contact || order.customer_phone;
    
    if (!phoneNumber) {
      alert('No hay número de teléfono disponible para esta orden.');
      return;
    }

    // Eliminar caracteres no numéricos excepto '+' para formar un enlace tel: limpio
    const cleanNumber = phoneNumber.replace(/[^\d+]/g, '');
    
    // Abrir marcador telefónico
    window.location.href = `tel:${cleanNumber}`;
  };

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-3xl mx-auto">
        <Button variant="ghost" onClick={() => router.back()} className="mb-6 pl-0 hover:bg-transparent hover:text-blue-600">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver a mis órdenes
        </Button>

        <Card className="mb-6 border-t-4 border-t-blue-500 shadow-md overflow-hidden">
          <CardHeader className="bg-gray-50 border-b">
            <div className="flex justify-between items-start">
              <div>
                <CardTitle className="text-2xl text-gray-900">Orden #{order.external_id}</CardTitle>
                <p className="text-gray-500 text-sm mt-1 font-mono">{order.id}</p>
              </div>
              <Badge className={`text-sm px-3 py-1 border ${
                order.status === 'ENTREGADO' ? 'bg-green-100 text-green-800 border-green-200' :
                order.status === 'CANCELADO' ? 'bg-red-100 text-red-800 border-red-200' :
                'bg-blue-100 text-blue-800 border-blue-200'
              }`}>
                {order.status}
              </Badge>
            </div>
          </CardHeader>
          
          <CardContent className="space-y-6 pt-6">
            {/* Dirección */}
            <div className="flex items-start gap-4 p-4 bg-blue-50/50 rounded-lg border border-blue-100">
              <div className="p-2 bg-white rounded-full shadow-sm">
                <MapPin className="w-6 h-6 text-blue-600 shrink-0" />
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-gray-900 text-sm uppercase tracking-wide mb-1">Dirección de Entrega</h3>
                <p className="text-gray-700 font-medium">{order.delivery_address}</p>
                {order.delivery_reference && (
                  <p className="text-sm text-gray-500 mt-1">Ref: {order.delivery_reference}</p>
                )}
              </div>
            </div>

            {/* Items */}
            <div>
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <Package className="w-5 h-5 text-gray-500" /> Productos
              </h3>
              <div className="border rounded-lg overflow-hidden shadow-sm">
                <table className="w-full text-sm text-left">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">Producto</th>
                      <th className="px-4 py-3 font-medium text-center">Cant.</th>
                      <th className="px-4 py-3 font-medium text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y bg-white">
                    {order.items && order.items.length > 0 ? (
                      order.items.map((item, idx) => (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-gray-900 font-medium">{item.product_name || 'Sin nombre'}</td>
                          <td className="px-4 py-3 text-center text-gray-600">x{item.quantity}</td>
                          <td className="px-4 py-3 text-right font-bold text-gray-900">
                            {formatCurrency(item.unit_price * item.quantity)}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3} className="px-4 py-6 text-center text-gray-400 italic">No hay productos listados</td>
                      </tr>
                    )}
                  </tbody>
                  <tfoot className="bg-gray-50 font-bold text-gray-900">
                    <tr>
                      <td colSpan={2} className="px-4 py-3 text-right">TOTAL A PAGAR</td>
                      <td className="px-4 py-3 text-right text-blue-700 text-base">
                        {formatCurrency(resolveOrderCollectAmount(order))}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>

            {/* Totales y Info Extra */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t">
              <div className="flex items-center gap-3 p-3 bg-white rounded-lg border shadow-sm">
                <div className="p-2 bg-green-100 rounded-full">
                  <DollarSign className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-semibold uppercase">Total a cobrar</p>
                  <p className="font-bold text-lg text-gray-900">{formatCurrency(resolveOrderCollectAmount(order))}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 bg-white rounded-lg border shadow-sm">
                <div className="p-2 bg-gray-100 rounded-full">
                  <Clock className="w-5 h-5 text-gray-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-semibold uppercase">Creado el</p>
                  <p className="font-medium text-gray-900 text-sm">{new Date(order.created_at).toLocaleString()}</p>
                </div>
              </div>
            </div>

            {/* Acciones Generales (Llamar, Mapa) */}
            <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t mt-6">
              <Button 
                className="flex-1 bg-green-600 hover:bg-green-700 text-white shadow-md h-12 text-base"
                onClick={handleCallCustomer}
                disabled={!order.delivery_contact && !order.customer_phone}
              >
                <Phone className="w-5 h-5 mr-2" /> 
                {!order.delivery_contact && !order.customer_phone ? 'Sin Teléfono' : 'Llamar al Cliente'}
              </Button>
              
              <Button 
                variant="outline" 
                className="flex-1 border-blue-200 text-blue-700 hover:bg-blue-50 h-12 text-base"
                onClick={handleOpenMap}
                disabled={!order.delivery_address}
              >
                <MapPin className="w-5 h-5 mr-2" /> 
                Ver en Mapa
                <ExternalLink className="w-4 h-4 ml-2 opacity-70" />
              </Button>
            </div>

            {/* SECCIÓN DE ACCIONES PARA EL REPARTIDOR - FASE 2 */}
            {user.role === 'REPARTIDOR' && order?.delivery && (
              <Card className="mt-6 border-t-4 border-t-orange-500 shadow-md">
                <CardHeader className="bg-orange-50 border-b">
                  <CardTitle className="text-lg text-orange-900 flex items-center gap-2">
                    <Bike className="w-5 h-5" />
                    Acciones de Entrega
                  </CardTitle>
                  <p className="text-sm text-orange-700">
                    Estado actual: <span className="font-bold">{order.delivery.status}</span>
                  </p>
                </CardHeader>
                <CardContent className="pt-6">
                  {getAvailableActions().length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {getAvailableActions().map((action) => {
                        const Icon = action.icon;
                        return (
                          <Button
                            key={action.key}
                            className={`h-14 text-base font-semibold ${
                              action.variant === 'success' ? 'bg-green-600 hover:bg-green-700 text-white' :
                              action.variant === 'destructive' ? 'bg-red-600 hover:bg-red-700 text-white' :
                              'bg-blue-600 hover:bg-blue-700 text-white'
                            }`}
                            onClick={() => {
                              if (action.key === 'FALLIDO') {
                                setShowFailDialog(true);
                              } else {
                                updateDeliveryStatus(action.key);
                              }
                            }}
                            disabled={updatingStatus}
                          >
                            <Icon className="w-5 h-5 mr-2" />
                            {updatingStatus ? 'Procesando...' : action.label}
                          </Button>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-gray-500 text-center py-4">
                      {order.delivery.status === 'COMPLETADA' || order.delivery.status === 'FALLIDA' 
                        ? 'Esta entrega ya ha sido finalizada'
                        : 'Esperando asignación para comenzar acciones'}
                    </p>
                  )}
                </CardContent>
              </Card>
            )}

            {/* DIALOGO PARA REPORTAR FALLIDOS - FASE 2 */}
            <Dialog open={showFailDialog} onOpenChange={setShowFailDialog}>
              <DialogContent className="sm:max-w-[500px]">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2 text-red-700">
                    <XCircle className="w-6 h-6" />
                    Reportar Incidencia / Entrega Fallida
                  </DialogTitle>
                  <DialogDescription>
                    Selecciona el motivo del fallo. Si es por causa del cliente, recibirás un bono compensatorio configurable.
                  </DialogDescription>
                </DialogHeader>
                
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="issue-type">Motivo del Fallo *</Label>
                    <Select value={selectedIssueType} onValueChange={setSelectedIssueType}>
                      <SelectTrigger id="issue-type">
                        <SelectValue placeholder="Selecciona un motivo" />
                      </SelectTrigger>
                      <SelectContent>
                        {/* Motivos que generan pago (FASE 2) */}
                        <optgroup label="📌 Culpa del Cliente (Generan Bono)">
                          {customerFaultReasons.map((reason) => (
                            <SelectItem key={reason.value} value={reason.value}>
                              {reason.label}
                            </SelectItem>
                          ))}
                        </optgroup>
                        {/* Motivos que NO generan pago */}
                        <optgroup label="⚠️ Problemas del Repartidor (Sin Bono)">
                          {riderFaultReasons.map((reason) => (
                            <SelectItem key={reason.value} value={reason.value}>
                              {reason.label}
                            </SelectItem>
                          ))}
                        </optgroup>
                      </SelectContent>
                    </Select>
                    {selectedIssueType && customerFaultReasons.some(r => r.value === selectedIssueType) && (
                      <p className="text-xs text-green-600 font-medium mt-1 flex items-center gap-1">
                        <CheckCircle className="w-3 h-3" />
                        Este motivo genera un bono compensatorio automático
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="issue-description">Descripción Adicional</Label>
                    <Textarea
                      id="issue-description"
                      placeholder="Describe brevemente lo sucedido (opcional)..."
                      value={issueDescription}
                      onChange={(e) => setIssueDescription(e.target.value)}
                      rows={3}
                    />
                  </div>
                </div>

                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => setShowFailDialog(false)}
                    disabled={updatingStatus}
                  >
                    Cancelar
                  </Button>
                  <Button
                    className="bg-red-600 hover:bg-red-700 text-white"
                    onClick={() => {
                      if (!selectedIssueType) {
                        alert('Debes seleccionar un motivo del fallo');
                        return;
                      }
                      updateDeliveryStatus('FALLIDO', selectedIssueType, issueDescription);
                    }}
                    disabled={updatingStatus || !selectedIssueType}
                  >
                    {updatingStatus ? 'Procesando...' : 'Confirmar Reporte'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}