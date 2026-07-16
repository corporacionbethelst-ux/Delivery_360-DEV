'use client'; 

import React, { useState, useEffect } from 'react';
import { Order } from '@/types/order';
import type { Rider } from '@/types/user';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { X, Search, User, Phone, Star, Bike } from 'lucide-react';
import { useRidersStore } from '@/stores/ridersStore';
import { formatCurrency } from '@/lib/formatters';

interface AssignRiderModalProps {
  order: Order;
  onClose: () => void;
  onAssign: (riderId: string) => void;
}

export default function AssignRiderModal({ order, onClose, onAssign }: AssignRiderModalProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedRiderId, setSelectedRiderId] = useState<string | null>(null);
  
  const { riders, fetchRiders, isLoading } = useRidersStore();

  useEffect(() => {
    // Filtramos solo activos y online
    // Nota: Ajusta los filtros según lo que acepte tu store real
    fetchRiders({ status: ['ACTIVO'] }); 
  }, [fetchRiders]);

  const availableRiders = riders.filter((rider: Rider) => {
    // Construir nombre completo de forma segura
    const fullName = rider.full_name || `${rider.first_name || ''} ${rider.last_name || ''}`.trim();
    const cpf = rider.cpf || '';
    
    const matchesSearch = 
      fullName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      cpf.includes(searchTerm);
    
    // Verificar estado online y activo
    return rider.is_online && rider.status === 'ACTIVO' && matchesSearch;
  });

  const handleAssign = () => {
    if (selectedRiderId) {
      onAssign(selectedRiderId);
    }
  };

  // Detección segura de asignación previa
  // Asumiendo que Order tiene assignedRider o similar, si no, ajustar según tu tipo Order
  const assignedRider = (order as any).assigned_rider || order.assignedRider;
  const isAssigned = !!(order as any).assigned_rider_id || !!order.assignedRiderId || !!assignedRider;
  const assignedRiderName = assignedRider?.full_name || 
                            `${(assignedRider as any)?.first_name || ''} ${(assignedRider as any)?.last_name || ''}`.trim() || 
                            'Repartidor';

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-6 border-b flex justify-between items-start">
          <div className="space-y-1">
            <h2 className="text-2xl font-bold">Asignar Repartidor</h2>
            <p className="text-sm text-gray-500">
              Orden #{(order as any).order_number || order.orderNumber || order.id.substring(0, 8)} 
              - {order.customerName || (order as any).customer_name} 
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="w-5 h-5" />
          </Button>
        </div>

        {/* Order Summary */}
        <div className="p-6 bg-gray-50 border-b">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-gray-500">Cliente</p>
              <p className="font-medium">{order.customerName || (order as any).customer_name}</p>
              <p className="text-xs text-gray-500">{order.customerPhone || (order as any).customer_phone}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Dirección</p>
              <p className="font-medium text-sm truncate">
                {(order.deliveryAddress as any)?.street || (order.deliveryAddress as any)?.address}, {(order.deliveryAddress as any)?.number}
              </p>
              <p className="text-xs text-gray-500 truncate">
                {(order.deliveryAddress as any)?.neighborhood}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Total</p>
              <p className="font-bold text-lg">{formatCurrency(order.total || (order as any).total_amount || 0)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Prioridad</p>
              <Badge variant={(order.priority === 'URGENTE' || (order as any).priority === 'URGENTE') ? 'destructive' : 'default'}>
                {order.priority || (order as any).priority}
              </Badge>
            </div>
          </div>
        </div>

        {/* Already Assigned Warning */}
        {isAssigned && (
          <div className="p-4 bg-blue-50 border-b">
            <div className="flex items-center gap-3">
              <User className="w-5 h-5 text-blue-600" />
              <div>
                <p className="font-medium text-blue-900">Orden ya asignada</p>
                <p className="text-sm text-blue-700">
                  Repartidor: {assignedRiderName}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Search */}
        <div className="p-4 border-b">
          <Label htmlFor="search-rider">Buscar Repartidor</Label>
          <div className="relative mt-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
            <Input
              id="search-rider"
              placeholder="Buscar por nombre o documento..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
              disabled={isLoading}
            />
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {availableRiders.length} repartidores disponibles
          </p>
        </div>

        {/* Riders List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading ? (
            <div className="text-center py-8 text-gray-500">Cargando repartidores...</div>
          ) : availableRiders.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <User className="w-12 h-12 mx-auto mb-2 opacity-50" />
              <p>No hay repartidores disponibles</p>
              {searchTerm && (
                <Button variant="link" onClick={() => setSearchTerm('')}>
                  Limpiar búsqueda
                </Button>
              )}
            </div>
          ) : (
            availableRiders.map((rider: Rider) => {
              // Extracción segura basada en la interfaz Rider real (propiedades planas)
              const vehicleType = rider.vehicle_type || 'No especificado';
              const vehiclePlate = rider.vehicle_plate || 'S/P';
              
              // Como la interfaz Rider no tiene 'stats' anidado ni 'customer_rating' directo en tu definición,
              // usamos valores por defecto o campos alternativos si existieran en una extensión futura.
              // Por ahora, simulamos rating 0 o buscamos en extensiones posibles.
              const rating = 0; // Valor por defecto seguro basado en tu interfaz actual
              const deliveries = 0; // Valor por defecto seguro

              const fullName = rider.full_name || `${rider.first_name || ''} ${rider.last_name || ''}`.trim() || 'Sin Nombre';

              return (
                <Card
                  key={rider.id}
                  className={`p-4 cursor-pointer transition-all hover:shadow-md ${
                    selectedRiderId === rider.id 
                      ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200' 
                      : 'hover:border-blue-300'
                  }`}
                  onClick={() => setSelectedRiderId(rider.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-start gap-3 flex-1">
                      <div className="w-12 h-12 rounded-full bg-gray-200 flex items-center justify-center shrink-0">
                        <User className="w-6 h-6 text-gray-600" />
                      </div>
                      <div className="flex-1 space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="font-semibold">{fullName}</h3>
                          {/* Mostramos badge solo si tuvieras rating real, por ahora oculto o estático */}
                          {rating >= 4.5 && (
                            <Badge className="bg-yellow-100 text-yellow-800 text-xs">
                              <Star className="w-3 h-3 fill-yellow-500 mr-1" />
                              {Number(rating).toFixed(1)}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-sm text-gray-600 flex-wrap">
                          <span className="flex items-center gap-1">
                            <Phone className="w-3 h-3" />
                            {rider.phone || 'Sin teléfono'}
                          </span>
                          <span className="flex items-center gap-1">
                            <Bike className="w-3 h-3" />
                            {vehicleType} - {vehiclePlate}
                          </span>
                        </div>
                        <div className="flex gap-2 pt-1 flex-wrap">
                          {/* Mostramos zona operativa si existe */}
                          {rider.operating_zone ? (
                             <Badge variant="outline" className="text-xs">
                               📍 {rider.operating_zone}
                             </Badge>
                          ) : null}
                          {/* Badge de nivel si existe */}
                          {rider.level ? (
                            <Badge variant="secondary" className="text-xs">
                              Nvl {rider.level}
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {selectedRiderId === rider.id && (
                      <div className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center shrink-0 ml-2">
                        <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                    )}
                  </div>
                </Card>
              );
            })
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-4 border-t bg-gray-50 flex justify-end gap-3">
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button 
            onClick={handleAssign} 
            disabled={!selectedRiderId || isAssigned}
            className="gap-2"
          >
            <User className="w-4 h-4" />
            {isAssigned ? 'Ya Asignado' : `Asignar Orden`}
          </Button>
        </div>
      </Card>
    </div>
  );
}