'use client';

import React, { useState, useEffect, useRef } from 'react';
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
import type { RiderTier } from '@/types/rider';
import type { Vehicle } from '@/services/vehicle.service';
import { vehicleService } from '@/services/vehicle.service';
import { riderService, type UpdateRiderPayload } from '@/services/rider.service';
import { isAssignmentConflict, requireAssignmentRevision } from '@/lib/assignment-revision';
import { toast } from 'sonner';
import { requireProfileRevision } from '@/lib/profile-revision';
import { requireVehicleRevision } from '@/lib/vehicle-revision';

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
  const [draft, setDraft] = useState<Rider | null>(null);
  const draftRef = useRef<Rider | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [isLoadingVehicles, setIsLoadingVehicles] = useState(false);
  const [internalCompanyVehicles, setInternalCompanyVehicles] = useState<Vehicle[]>([]);

  // Usar los vehículos pasados por props o cargar internamente si no se proporcionan
  const companyVehicles = propCompanyVehicles.length > 0 ? propCompanyVehicles : internalCompanyVehicles;

  // Estados del formulario
  const [phone, setPhone] = useState('');
  const [tier, setTier] = useState<RiderTier>('BRONCE');
  const [vehicleOwnershipType, setVehicleOwnershipType] = useState<'PROPIO' | 'EMPRESA'>('PROPIO');
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [assignedVehicleId, setAssignedVehicleId] = useState<string>('');

  // Datos de vehículo propio
  const [vehicleType, setVehicleType] = useState('');
  const [vehiclePlate, setVehiclePlate] = useState('');
  const [vehicleModel, setVehicleModel] = useState('');

  useEffect(() => () => { draftRef.current = null; }, []);

  // Cargar vehículos de empresa cuando se abre el modal (solo si no vienen por props)
  useEffect(() => {
    if (open && propCompanyVehicles.length === 0) {
      loadCompanyVehicles();
    }
  }, [open, propCompanyVehicles.length]);

  // Cargar datos del rider cuando cambia
  useEffect(() => {
    if (!open) {
      draftRef.current = null;
      setDraft(null);
      return;
    }
    if (rider && draftRef.current?.id !== rider.id) {
      const snapshot = { ...rider };
      draftRef.current = snapshot;
      setDraft(snapshot);
      setConflicted(false);
      setPhone(rider.phone || '');
      setTier(rider.tier || 'BRONCE');
      setVehicleOwnershipType(rider.vehicle_ownership_type || 'PROPIO');
      setAssignedVehicleId(rider.assigned_vehicle_id || '');
      setSelectedVehicle(null);
      setVehicleType(rider.vehicle_type || '');
      setVehiclePlate(rider.vehicle_plate || '');
      setVehicleModel(rider.vehicle_model || '');
    }
  }, [open, rider]);

  const loadCompanyVehicles = async () => {
    setIsLoadingVehicles(true);
    try {
      const vehicles = await vehicleService.getAvailableCompanyVehicles();
      setInternalCompanyVehicles(vehicles);

    } catch (error) {
      console.error('Error loading company vehicles:', error);
      toast.error('No se pudieron cargar los vehículos de empresa');
      setInternalCompanyVehicles([]); // Asegurar lista vacía en caso de error
    } finally {
      setIsLoadingVehicles(false);
    }
  };

  const handleSave = async () => {
    if (!draft || conflicted) return;
    const submittedDraft = draft;

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
      const updateData: UpdateRiderPayload = {
        expected_profile_revision: requireProfileRevision(draft.profile_revision),
        expected_assignment_revision: requireAssignmentRevision(draft.assignment_revision),
        phone: phone || undefined,
        tier: tier || undefined,  // Incluir nivel del repartidor
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
        updateData.expected_vehicle_revision = requireVehicleRevision(selectedVehicle?.revision ?? (assignedVehicleId === draft.assigned_vehicle_id ? draft.assigned_vehicle?.revision : undefined));
        updateData.assigned_vehicle_id = assignedVehicleId;
        updateData.vehicle_ownership_type = 'EMPRESA';

        // Obtener datos del vehículo seleccionado para enviar también tipo y placa
        // El backend obtiene los datos canónicos tras comprobar la revisión.

        // Limpiar datos de vehículo propio
        updateData.vehicle_model = undefined;
      }

      await riderService.updateRider(draft.id, updateData);
      if (draftRef.current !== submittedDraft) return;

      toast.success('Repartidor actualizado correctamente');
      onSuccess();
      onOpenChange(false);
    } catch (error: unknown) {
      if (draftRef.current !== submittedDraft) return;
      if (isAssignmentConflict(error)) {
        setConflicted(true);
        toast.error('Los datos del vehículo cambiaron. Cierra y recarga para revisarlos.');
      } else {
        toast.error(error instanceof Error ? error.message : 'Error al actualizar el repartidor');
      }
    } finally {
      setLoading(false);
    }
  };

  const currentAvailable = companyVehicles.filter(v => v.status === 'ACTIVO').map(v => v.id === selectedVehicle?.id ? selectedVehicle : v);
  const availableVehicles = selectedVehicle && !currentAvailable.some(v => v.id === selectedVehicle.id)
    ? [...currentAvailable, selectedVehicle] : currentAvailable;

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
                value={`${draft?.first_name || ''} ${draft?.last_name || ''}`.trim()}
                disabled
              />
            </div>
            <div>
              <Label>Email</Label>
              <Input value={draft?.email || ''} disabled />
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

          {/* Nivel del Repartidor (Gamificación) */}
          <div>
            <Label>Nivel del Repartidor</Label>
            <Select
              value={tier}
              onValueChange={(value: RiderTier) => setTier(value)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Seleccionar nivel" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="BRONCE">🥉 Bronce (0% extra)</SelectItem>
                <SelectItem value="PLATA">🥈 Plata (+5% extra)</SelectItem>
                <SelectItem value="ORO">🥇 Oro (+10% extra)</SelectItem>
                <SelectItem value="PLATINO">💎 Platino (+15% extra)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-gray-500 mt-1">
              El nivel afecta el bono por entrega. Ej: $2.50 base × 1.10 (Oro) = $2.75
            </p>
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
                    setSelectedVehicle({ ...firstAvailable });
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
              ) : availableVehicles.length === 0 && !draft?.assigned_vehicle_id ? (
                <div className="text-center py-4 text-gray-500">
                  No hay vehículos de empresa disponibles
                </div>
              ) : (
                <div>
                  <Label>Seleccionar Vehículo</Label>
                  <Select value={assignedVehicleId} onValueChange={id => { setAssignedVehicleId(id); const chosen = companyVehicles.find(v => v.id === id); setSelectedVehicle(chosen ? { ...chosen } : null); }}>
                    <SelectTrigger>
                      <SelectValue placeholder="Seleccionar vehículo" />
                    </SelectTrigger>
                    <SelectContent>
                      {draft?.assigned_vehicle_id && !availableVehicles.some(v => v.id === draft.assigned_vehicle_id) && (
                        <SelectItem value={draft.assigned_vehicle_id}>Vehículo actual: {draft.vehicle_plate || draft.assigned_vehicle_id}</SelectItem>
                      )}
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
                        const selected = selectedVehicle ?? companyVehicles.find(v => v.id === assignedVehicleId);
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
          {draft?.vehicle_ownership_type &&
           draft.vehicle_ownership_type !== vehicleOwnershipType && (
            <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
              ⚠️ Estás cambiando el tipo de vehículo. Si cambias de &quot;Propio&quot; a &quot;Empresa&quot;,
              se perderán los datos del vehículo propio actual.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancelar
          </Button>
          {conflicted && <Button variant="outline" onClick={() => { onSuccess(); onOpenChange(false); }}>Cerrar y recargar</Button>}
          <Button onClick={handleSave} disabled={loading || conflicted || !draft}>
            {loading ? 'Guardando...' : 'Guardar Cambios'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
