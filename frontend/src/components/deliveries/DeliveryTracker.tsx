"use client"; 

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Package,
  CheckCircle,
  Clock,
  MapPin,
  User,
  Phone,
  Search,
  Eye,
  AlertCircle,
  Truck,
} from "lucide-react";
// ✅ IMPORTANTE: Usar tipos globales
import type { Delivery } from "@/types/delivery";
// ⚠️ CORRECCIÓN: Asegúrate de que el nombre del store sea correcto (deliveriesStore vs deliveryStore)
import { useDeliveriesStore } from "@/stores/deliveriesStore"; 
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";

/**
 * Componente principal para el seguimiento de entregas
 */
export default function DeliveryTracker() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState("");
  
  // Usamos el store corregido
  const { deliveries, fetchDeliveries, isLoading } = useDeliveriesStore();
  
  const [selectedDelivery, setSelectedDelivery] = useState<Delivery | null>(null);

  // Cargar entregas al montar si usas el store
  useEffect(() => {
    if (deliveries.length === 0 && !isLoading) {
      fetchDeliveries({ limit: 50 });
    }
  }, []);

  // Lógica de filtrado
  const filteredDeliveries = deliveries.filter((delivery) => {
    // Filtro por estado
    if (statusFilter !== "all" && delivery.status !== statusFilter) {
      return false;
    }

    // Filtro por búsqueda (ID, cliente, dirección, repartidor)
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      // Manejo seguro de propiedades snake_case / camelCase
      const customerId = (delivery.order as any)?.customer_id?.toLowerCase() || "";
      const customerName = ((delivery.order as any)?.customer_name || (delivery.order as any)?.customerName || "").toLowerCase();
      const address = delivery.deliveryLocation?.address?.toLowerCase() || "";
      const riderName = (delivery.rider?.full_name || delivery.rider?.first_name || "").toLowerCase();
      
      const idMatch = delivery.id.toLowerCase().includes(term);

      if (
        !idMatch &&
        !customerId.includes(term) &&
        !customerName.includes(term) &&
        !address.includes(term) &&
        !riderName.includes(term)
      ) {
        return false;
      }
    }
    return true;
  });

  // ✅ CORRECCIÓN CRÍTICA: Cambiar tipo a string para evitar errores de unión estrecha
  const getStatusConfig = (status: string) => {
    // Normalizamos a mayúsculas por si acaso viene en otro formato
    const s = status.toUpperCase();

    switch (s) {
      case "PENDIENTE":
        return { color: "bg-yellow-100 text-yellow-800 border-yellow-300", label: "Pendiente", icon: <Clock className="h-3 w-3 mr-1" /> };
      case "ASIGNADO":
        return { color: "bg-blue-100 text-blue-800 border-blue-300", label: "Asignado", icon: <User className="h-3 w-3 mr-1" /> };
      case "RECOGIDO":
        return { color: "bg-indigo-100 text-indigo-800 border-indigo-300", label: "Recogido", icon: <Package className="h-3 w-3 mr-1" /> };
      case "EN_CAMINO":
      case "EN_ROUTE": // Soporte para variante en inglés/otro formato
        return { color: "bg-cyan-100 text-cyan-800 border-cyan-300", label: "En Camino", icon: <Truck className="h-3 w-3 mr-1" /> };
      case "ENTREGADO":
      case "COMPLETADA":
        return { color: "bg-green-100 text-green-800 border-green-300", label: "Entregado", icon: <CheckCircle className="h-3 w-3 mr-1" /> };
      case "FALLIDO":
      case "FALLIDA":
        return { color: "bg-red-100 text-red-800 border-red-300", label: "Fallido", icon: <AlertCircle className="h-3 w-3 mr-1" /> };
      case "CANCELADO":
      case "CANCELADA":
        return { color: "bg-gray-100 text-gray-800 border-gray-300", label: "Cancelado", icon: <AlertCircle className="h-3 w-3 mr-1" /> };
      case "INICIADA":
        return { color: "bg-orange-100 text-orange-800 border-orange-300", label: "Iniciada", icon: <Truck className="h-3 w-3 mr-1" /> };
      case "EN_PICKUP":
        return { color: "bg-purple-100 text-purple-800 border-purple-300", label: "En Pickup", icon: <Package className="h-3 w-3 mr-1" /> };
      case "EN_DESTINO":
        return { color: "bg-sky-100 text-sky-800 border-sky-300", label: "En Destino", icon: <MapPin className="h-3 w-3 mr-1" /> };
      default:
        return { color: "bg-gray-100 text-gray-800", label: status, icon: <Package className="h-3 w-3 mr-1" /> };
    }
  };

  // Helper para obtener nombre del cliente de forma segura
  const getCustomerName = (delivery: Delivery) => {
    return (
      (delivery.order as any)?.customer_name || 
      (delivery.order as any)?.customerName || 
      "Cliente no especificado"
    );
  };

  // Helper para dirección
  const getAddress = (delivery: Delivery) => {
    const loc = delivery.deliveryLocation;
    if (!loc) return "Sin dirección";
    return `${loc.address || ""}${loc.city ? `, ${loc.city}` : ""}`;
  };

  // Helper para repartidor
  const getRiderName = (delivery: Delivery) => {
    if (!delivery.rider) return null;
    return (
      (delivery.rider as any).full_name || 
      `${(delivery.rider as any).first_name || ""} ${(delivery.rider as any).last_name || ""}`.trim() || 
      "Repartidor"
    );
  };

  // Helper seguro para fechas
  const getFormattedDate = (dateStr: string | number | Date | undefined | null) => {
    if (!dateStr) return "Reciente";
    try {
      return formatDistanceToNow(new Date(dateStr), { addSuffix: true, locale: es });
    } catch (e) {
      return "Fecha inválida";
    }
  };

  if (isLoading && deliveries.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Package className="h-12 w-12 text-muted-foreground mx-auto mb-4 animate-pulse" />
          <p className="text-muted-foreground">Cargando entregas...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Seguimiento de Entregas</h1>
          <p className="text-muted-foreground mt-1">
            Monitoreo en tiempo real del estado de las entregas
          </p>
        </div>
        <div className="flex items-center gap-2">
           <Badge variant="outline" className="text-sm">
             Total: {filteredDeliveries.length}
           </Badge>
        </div>
      </div>

      {/* Controles de filtro y búsqueda */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Buscar por ID, cliente, dirección o repartidor..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-full md:w-[200px]">
                <SelectValue placeholder="Filtrar por estado" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos los estados</SelectItem>
                <SelectItem value="PENDIENTE">Pendientes</SelectItem>
                <SelectItem value="ASIGNADO">Asignados</SelectItem>
                <SelectItem value="EN_CAMINO">En Camino</SelectItem>
                <SelectItem value="ENTREGADO">Entregados</SelectItem>
                <SelectItem value="FALLIDO">Fallidos</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Tabla de entregas */}
      <Card>
        <CardHeader>
          <CardTitle>Lista de Entregas</CardTitle>
        </CardHeader>
        <CardContent>
          {filteredDeliveries.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Package className="h-12 w-12 mx-auto mb-4 opacity-20" />
              <p>No se encontraron entregas con los filtros actuales.</p>
            </div>
          ) : (
            <div className="rounded-md border overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/50">
                  <TableRow>
                    <TableHead className="w-[100px]">ID</TableHead>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Dirección</TableHead>
                    <TableHead>Repartidor</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Tiempo</TableHead>
                    <TableHead className="text-right">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredDeliveries.map((delivery) => {
                    const statusConfig = getStatusConfig(delivery.status);
                    const customerName = getCustomerName(delivery);
                    const address = getAddress(delivery);
                    const riderName = getRiderName(delivery);

                    return (
                      <TableRow key={delivery.id} className="hover:bg-muted/50 transition-colors">
                        <TableCell className="font-mono text-xs font-medium">
                          {delivery.id.slice(0, 8)}...
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <User className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="truncate max-w-[150px]" title={customerName}>
                              {customerName}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2 max-w-[200px]">
                            <MapPin className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="truncate" title={address}>
                              {address}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {riderName ? (
                            <div className="flex items-center gap-2">
                              <Truck className="h-4 w-4 text-muted-foreground shrink-0" />
                              <span className="truncate max-w-[120px]">{riderName}</span>
                            </div>
                          ) : (
                            <span className="text-muted-foreground text-xs italic">Sin asignar</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`${statusConfig.color} border-transparent font-medium`}>
                            {statusConfig.icon}
                            {statusConfig.label}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                           {getFormattedDate((delivery as any).updated_at || delivery.updatedAt)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedDelivery(delivery)}
                            title="Ver detalles"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Modal / Panel de Detalles de entrega seleccionada */}
      {selectedDelivery && (
        <Card className="border-2 border-primary shadow-lg animate-in fade-in zoom-in-95 duration-200">
          <CardHeader className="bg-muted/30 border-b">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Package className="h-5 w-5 text-primary" />
                Detalles de Entrega - {selectedDelivery.id.slice(0, 12)}
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setSelectedDelivery(null)}>
                Cerrar
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="grid gap-6 md:grid-cols-2">
              {/* Columna Izquierda: Cliente y Dirección */}
              <div className="space-y-4">
                <div>
                  <h4 className="font-semibold text-sm uppercase text-muted-foreground mb-2">Información del Cliente</h4>
                  <div className="bg-card border rounded-lg p-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <User className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{getCustomerName(selectedDelivery)}</span>
                    </div>
                    {(selectedDelivery.order as any)?.customer_phone && (
                      <div className="flex items-center gap-2">
                        <Phone className="h-4 w-4 text-muted-foreground" />
                        <a href={`tel:${(selectedDelivery.order as any).customer_phone}`} className="text-primary hover:underline text-sm">
                          {(selectedDelivery.order as any).customer_phone}
                        </a>
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold text-sm uppercase text-muted-foreground mb-2">Dirección de Entrega</h4>
                  <div className="bg-card border rounded-lg p-4">
                    <div className="flex items-start gap-2">
                      <MapPin className="h-4 w-4 text-muted-foreground mt-1" />
                      <div>
                        <p className="font-medium">{getAddress(selectedDelivery)}</p>
                        {selectedDelivery.deliveryLocation?.reference && (
                          <p className="text-xs text-muted-foreground mt-1">
                            Ref: {selectedDelivery.deliveryLocation.reference}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Columna Derecha: Estado y Repartidor */}
              <div className="space-y-4">
                <div>
                  <h4 className="font-semibold text-sm uppercase text-muted-foreground mb-2">Estado Actual</h4>
                  <div className="bg-card border rounded-lg p-4">
                     {(() => {
                       const config = getStatusConfig(selectedDelivery.status);
                       return (
                         <div className="flex items-center gap-3">
                           <div className={`p-2 rounded-full ${config.color.split(' ')[0]}`}>
                             {config.icon}
                           </div>
                           <div>
                             <p className="font-bold text-lg">{config.label}</p>
                             <p className="text-xs text-muted-foreground">
                               Actualizado {getFormattedDate((selectedDelivery as any).updated_at || selectedDelivery.updatedAt)}
                             </p>
                           </div>
                         </div>
                       );
                     })()}
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold text-sm uppercase text-muted-foreground mb-2">Repartidor Asignado</h4>
                  <div className="bg-card border rounded-lg p-4">
                    {getRiderName(selectedDelivery) ? (
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold">
                            {(getRiderName(selectedDelivery) || "R").charAt(0)}
                          </div>
                          <div>
                            <p className="font-medium">{getRiderName(selectedDelivery)}</p>
                            {(selectedDelivery.rider as any)?.phone && (
                              <p className="text-xs text-muted-foreground">{(selectedDelivery.rider as any).phone}</p>
                            )}
                          </div>
                        </div>
                        <Button variant="outline" size="sm">
                          <Phone className="h-3 w-3 mr-2" />
                          Llamar
                        </Button>
                      </div>
                    ) : (
                      <div className="text-center py-2 text-muted-foreground italic">
                        No hay repartidor asignado aún.
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Métricas rápidas si existen */}
                <div className="grid grid-cols-2 gap-2">
                   <div className="border rounded-lg p-3 text-center">
                      <p className="text-xs text-muted-foreground">Distancia</p>
                      <p className="font-semibold">{(selectedDelivery as any).distance_km || (selectedDelivery as any).distanceKm || 0} km</p>
                   </div>
                   <div className="border rounded-lg p-3 text-center">
                      <p className="text-xs text-muted-foreground">Tarifa</p>
                      <p className="font-semibold">${Number((selectedDelivery as any).delivery_fee || (selectedDelivery as any).deliveryFee || 0).toFixed(2)}</p>
                   </div>
                </div>
              </div>
            </div>
            
            <div className="mt-8 flex justify-end gap-2 pt-4 border-t">
               <Button variant="outline" onClick={() => setSelectedDelivery(null)}>
                 Cerrar Detalles
               </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}