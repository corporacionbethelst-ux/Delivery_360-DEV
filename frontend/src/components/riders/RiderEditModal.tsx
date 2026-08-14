'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import type { Rider } from '@/types/user';
import type { Vehicle } from '@/services/vehicle.service';
import { vehicleService } from '@/services/vehicle.service';
import { riderService } from '@/services/rider.service';
import { toast } from 'sonner';

interface RiderEditModalProps {
  rider: Rider | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  companyVehicles?: Vehicle[]; // Lista opcional de vehículos de empresa
}

export default function RiderEditModal({
  rider,
  open,
  onOpenChange,
  onSuccess,
  companyVehicles: propCompanyVehicles = [],
}: RiderEditModalProps) {
  const [loading, setLoading] = useState(false);
  const [isLoadingVehicles, setIsLoadingVehicles] = useState(false);
  const [internalCompanyVehicles, setInternalCompanyVehicles] = useState<Vehicle[]>([]);
  
  // Usar los vehículos pasados por props o cargar internamente si no se proporcionan
  const companyVehicles = propCompanyVehicles.length > 0 ? propCompanyVehicles : internalCompanyVehicles;

  // Estados del formulario
  const [phone, setPhone] = useState('');
  const [vehicleOwnershipType, setVehicleOwnershipType] = useState<'PROPIO' | 'EMPRESA'>('PROPIO');
  const [assignedVehicleId, setAssignedVehicleId] = useState<string>('');
  
  // Datos de vehículo propio
  const [vehicleType, setVehicleType] = useState('');
  const [vehiclePlate, setVehiclePlate] = useState('');
  const [vehicleModel, setVehicleModel] = useState('');

  // Cargar vehículos de empresa cuando se abre el modal (solo si no vienen por props)
  useEffect(() => {
    if (open && propCompanyVehicles.length === 0) {
      loadCompanyVehicles();
    }
  }, [open, propCompanyVehicles.length]);

  // Cargar datos del rider cuando cambia
  useEffect(() => {
    if (rider) {
      setPhone(rider.phone || '');
      setVehicleOwnershipType(rider.vehicle_ownership_type || 'PROPIO');
      setAssignedVehicleId(rider.assigned_vehicle_id || '');
      setVehicleType(rider.vehicle_type || '');
      setVehiclePlate(rider.vehicle_plate || '');
      setVehicleModel(rider.vehicle_model || '');
    }
  }, [rider]);

  const loadCompanyVehicles = async () => {
    setIsLoadingVehicles(true);
    try {
      const vehicles = await vehicleService.getAvailableCompanyVehicles();
      setInternalCompanyVehicles(vehicles);
      
      // Auto-seleccionar si el rider ya tiene un vehículo asignado
      if (rider?.assigned_vehicle_id) {
        const stillAvailable = vehicles.find(v => v.id === rider.assigned_vehicle_id);
        if (stillAvailable) {
          setAssignedVehicleId(rider.assigned_vehicle_id);
        }
      }
    } catch (error) {
      console.error('Error loading company vehicles:', error);
      toast.error('No se pudieron cargar los vehículos de empresa');
      setInternalCompanyVehicles([]); // Asegurar lista vacía en caso de error
    } finally {
      setIsLoadingVehicles(false);
    }
  };

  const handleSave = async () => {
    if (!rider) return;

    // Validaciones estrictas antes de enviar
    if (vehicleOwnershipType === 'PROPIO' && !vehiclePlate.trim()) {
      toast.error('Debe ingresar la placa del vehículo propio');
      return;
    }

    if (vehicleOwnershipType === 'EMPRESA' && !assignedVehicleId) {
      toast.error('Debe seleccionar un vehículo de empresa');
      return;
    }

    setLoading(true);
    try {
      // Construir payload según el tipo de vehículo
      const updateData: any = {
        phone: phone || undefined,
      };

      if (vehicleOwnershipType === 'PROPIO') {
        // Para vehículo propio, enviar datos del vehículo
        updateData.vehicle_type = vehicleType || undefined;
        updateData.vehicle_plate = vehiclePlate || undefined;
        updateData.vehicle_model = vehicleModel || undefined;
        updateData.vehicle_ownership_type = 'PROPIO';
        updateData.assigned_vehicle_id = null; // Limpiar vehículo asignado
      } else {
        // Para vehículo de empresa, solo enviar ID
        updateData.assigned_vehicle_id = assignedVehicleId;
        updateData.vehicle_ownership_type = 'EMPRESA';
        
        // Obtener datos del vehículo seleccionado para enviar también tipo y placa
        const selectedVehicle = companyVehicles.find(v => v.id === assignedVehicleId);
        if (selectedVehicle) {
          updateData.vehicle_type = selectedVehicle.type;
          updateData.vehicle_plate = selectedVehicle.plate;
        }
        
        // Limpiar datos de vehículo propio
        updateData.vehicle_model = undefined;
      }

      await riderService.updateRider(rider.id, updateData);
      
      toast.success('Repartidor actualizado correctamente');
      onSuccess();
      onOpenChange(false);
    } catch (error: any) {
      console.error('Error updating rider:', error);
      toast.error(error.response?.data?.detail || 'Error al actualizar el repartidor');
    } finally {
      setLoading(false);
    }
  };

  const availableVehicles = companyVehicles.filter(v => v.status === 'ACTIVO');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Editar Repartidor</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Información básica */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Nombre</Label>
              <Input
                value={`${rider?.first_name || ''} ${rider?.last_name || ''}`.trim()}
                disabled
              />
            </div>
            <div>
              <Label>Email</Label>
              <Input value={rider?.email || ''} disabled />
            </div>
          </div>

          {/* Teléfono */}
          <div>
            <Label>Teléfono</Label>
            <Input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+55 11 99999-9999"
            />
          </div>

          {/* Tipo de Vehículo */}
          <div>
            <Label>Tipo de Vehículo</Label>
            <Select
              value={vehicleOwnershipType}
              onValueChange={(value: 'PROPIO' | 'EMPRESA') => {
                setVehicleOwnershipType(value);
                if (value === 'EMPRESA' && companyVehicles.length > 0) {
                  // Auto-seleccionar primer vehículo disponible
                  const firstAvailable = availableVehicles[0];
                  if (firstAvailable) {
                    setAssignedVehicleId(firstAvailable.id);
                  }
                }
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Seleccionar tipo" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="PROPIO">🏠 Vehículo Propio</SelectItem>
                <SelectItem value="EMPRESA">🏢 Vehículo de Empresa</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Campos condicionales según tipo de vehículo */}
          {vehicleOwnershipType === 'PROPIO' ? (
            <div className="space-y-4 p-4 border rounded-lg bg-gray-50">
              <h4 className="font-medium text-sm text-gray-700">Datos del Vehículo Propio</h4>
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Tipo</Label>
                  <Select value={vehicleType} onValueChange={setVehicleType}>
                    <SelectTrigger>
                      <SelectValue placeholder="Seleccionar tipo" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="MOTO">🏍️ Moto</SelectItem>
                      <SelectItem value="BICICLETA">🚴 Bicicleta</SelectItem>
                      <SelectItem value="AUTO">🚗 Auto</SelectItem>
                      <SelectItem value="FURGONETA">🚐 Furgoneta</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Placa</Label>
                  <Input
                    value={vehiclePlate}
                    onChange={(e) => setVehiclePlate(e.target.value.toUpperCase())}
                    placeholder="ABC-1234"
                  />
                </div>
              </div>
              
              <div>
                <Label>Modelo</Label>
                <Input
                  value={vehicleModel}
                  onChange={(e) => setVehicleModel(e.target.value)}
                  placeholder="Ej: Honda CG 160"
                />
              </div>
            </div>
          ) : (
            <div className="space-y-4 p-4 border rounded-lg bg-blue-50">
              <h4 className="font-medium text-sm text-blue-700 flex items-center gap-2">
                🏢 Vehículo de Empresa Asignado
              </h4>
              
              {isLoadingVehicles ? (
                <div className="text-center py-8">
                  <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
                    <p className="text-gray-500 text-sm">Cargando vehículos disponibles...</p>
                  </div>
                </div>
              ) : availableVehicles.length === 0 ? (
                <div className="text-center py-4 text-gray-500">
                  No hay vehículos de empresa disponibles
                </div>
              ) : (
                <div>
                  <Label>Seleccionar Vehículo</Label>
                  <Select value={assignedVehicleId} onValueChange={setAssignedVehicleId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Seleccionar vehículo" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableVehicles.map((vehicle) => (
                        <SelectItem key={vehicle.id} value={vehicle.id}>
                          {vehicle.type} - {vehicle.plate} ({vehicle.model})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  
                  {assignedVehicleId && (
                    <div className="mt-2 p-2 bg-white rounded border">
                      {(() => {
                        const selected = companyVehicles.find(v => v.id === assignedVehicleId);
                        return selected ? (
                          <div className="text-sm space-y-1">
                            <div><strong>Tipo:</strong> {selected.type}</div>
                            <div><strong>Placa:</strong> {selected.plate}</div>
                            <div><strong>Modelo:</strong> {selected.model}</div>
                            <div><strong>Año:</strong> {selected.year}</div>
                            <div><strong>Estado:</strong> 
                              <Badge variant="outline" className="ml-1 text-xs">
                                {selected.status}
                              </Badge>
                            </div>
                          </div>
                        ) : null;
                      })()}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Advertencia al cambiar de tipo */}
          {rider?.vehicle_ownership_type && 
           rider.vehicle_ownership_type !== vehicleOwnershipType && (
            <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
              ⚠️ Estás cambiando el tipo de vehículo. Si cambias de "Propio" a "Empresa", 
              se perderán los datos del vehículo propio actual.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancelar
          </Button>
          <Button onClick={handleSave} disabled={loading}>
            {loading ? 'Guardando...' : 'Guardar Cambios'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
