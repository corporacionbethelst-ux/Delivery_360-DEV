'use client';

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MoreHorizontal, Phone, Mail, MapPin } from 'lucide-react';
import type { Rider } from '@/types/rider';
import type { Vehicle } from '@/services/vehicle.service';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface RiderListProps {
  riders: Rider[];
  companyVehicles?: Vehicle[]; // Lista opcional de vehículos de empresa para resolver IDs
  onViewDetails?: (id: string) => void;
  onEdit?: (id: string) => void;
  onSuspend?: (id: string) => void;
  onActivate?: (id: string) => void;
}

export default function RiderList({ 
  riders, 
  companyVehicles = [],
  onViewDetails, 
  onEdit, 
  onSuspend, 
  onActivate 
}: RiderListProps) {
  const getStatusColor = (status: string) => {
    const s = status?.toUpperCase();
    switch(s) {
      case 'ACTIVO': return 'bg-green-100 text-green-800';
      case 'SUSPENDIDO': return 'bg-red-100 text-red-800';
      case 'PENDIENTE': return 'bg-yellow-100 text-yellow-800';
      case 'INACTIVO': return 'bg-gray-100 text-gray-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getVehicleIcon = (type: string) => {
    const t = type?.toUpperCase();
    switch(t) {
      case 'BICICLETA': 
      case 'BICYCLE': return '🚴';
      case 'MOTO': 
      case 'MOTORCYCLE': return '🏍️';
      case 'AUTO': 
      case 'CAR': return '🚗';
      case 'PIE': 
      case 'FOOT': return '🚶';
      default: return '📦';
    }
  };

  // Función auxiliar para obtener información del vehículo considerando tipo de propiedad
  const getVehicleInfo = (rider: Rider) => {
    // Si tiene vehicle_ownership_type === 'EMPRESA' y assigned_vehicle_id
    if (rider.vehicle_ownership_type === 'EMPRESA' && rider.assigned_vehicle_id) {
      const assignedVehicle = companyVehicles.find(v => v.id === rider.assigned_vehicle_id);
      if (assignedVehicle) {
        return {
          type: assignedVehicle.type,
          plate: assignedVehicle.plate,
          icon: getVehicleIcon(assignedVehicle.type),
          ownershipType: 'EMPRESA' as const
        };
      }
      // Si no se encuentra el vehículo en la lista, mostrar genérico
      return {
        type: 'Vehículo Empresa',
        plate: 'Asignado',
        icon: '🏢',
        ownershipType: 'EMPRESA' as const
      };
    }
    
    // Vehículo propio o sin especificar
    const vehicleType = rider.vehicle?.type || rider.vehicle_type || 'NO_ESPECIFICADO';
    const vehiclePlate = rider.vehicle?.plate || rider.vehicle_plate;
    const vehicleLabel = vehicleType === 'NO_ESPECIFICADO' ? 'No especificado' : vehicleType;
    
    return {
      type: vehicleLabel,
      plate: vehiclePlate,
      icon: getVehicleIcon(vehicleType),
      ownershipType: rider.vehicle_ownership_type === 'PROPIO' ? 'PROPIO' : undefined
    };
  };

  if (riders.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No hay repartidores para mostrar
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Repartidor</TableHead>
            <TableHead>Contacto</TableHead>
            <TableHead>Zona</TableHead>
            <TableHead>Vehículo</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead>En Línea</TableHead>
            <TableHead className="text-right">Acciones</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {riders.map((rider) => {
            const vehicleInfo = getVehicleInfo(rider);

            return (
              <TableRow key={rider.id} className="hover:bg-gray-50">
                <TableCell>
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-semibold text-sm">
                      {rider.fullName ? rider.fullName.split(' ').map(n => n[0]).join('').slice(0, 2) : 'RD'}
                    </div>
                    <div>
                      <div className="font-medium">{rider.fullName || 'Sin nombre'}</div>
                      <div className="text-xs text-gray-500">ID: {rider.id.slice(0, 8)}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <Phone className="w-3 h-3" />
                      {rider.phone || 'N/A'}
                    </div>
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <Mail className="w-3 h-3" />
                      <span className="max-w-[150px] truncate">{rider.email || 'N/A'}</span>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  {rider.operatingZone ? (
                    <div className="flex items-center gap-2 text-sm">
                      <MapPin className="w-4 h-4 text-gray-400" />
                      {rider.operatingZone}
                    </div>
                  ) : (
                    <span className="text-gray-400">-</span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{vehicleInfo.icon}</span>
                      <span className="text-sm font-medium">{vehicleInfo.type}</span>
                    </div>
                    {vehicleInfo.plate && (
                      <div className="flex items-center gap-1 ml-7">
                        <span className="text-[10px] uppercase bg-slate-100 px-1.5 py-0.5 rounded text-slate-600 font-mono tracking-wide">
                          {vehicleInfo.plate}
                        </span>
                      </div>
                    )}
                    {vehicleInfo.ownershipType === 'EMPRESA' && (
                      <Badge variant="outline" className="ml-7 mt-1 text-[9px] bg-blue-50 text-blue-700 border-blue-200 h-auto py-0 px-1">
                        🏢 Empresa
                      </Badge>
                    )}
                    {vehicleInfo.ownershipType === 'PROPIO' && (
                      <Badge variant="outline" className="ml-7 mt-1 text-[9px] bg-green-50 text-green-700 border-green-200 h-auto py-0 px-1">
                        🏠 Propio
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge className={getStatusColor(rider.status)}>{rider.status}</Badge>
                </TableCell>
                <TableCell>
                  {rider.isOnline ? (
                    <div className="flex items-center gap-2 text-green-600">
                      <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                      <span className="text-sm">Sí</span>
                    </div>
                  ) : (
                    <span className="text-gray-400 text-sm">No</span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon">
                        <MoreHorizontal className="w-4 h-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => onViewDetails?.(rider.id)}>
                        Ver Detalles
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onEdit?.(rider.id)}>
                        Editar
                      </DropdownMenuItem>
                      {rider.status === 'ACTIVO' ? (
                        <DropdownMenuItem 
                          onClick={() => onSuspend?.(rider.id)}
                          className="text-red-600"
                        >
                          Suspender
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem 
                          onClick={() => onActivate?.(rider.id)}
                          className="text-green-600"
                        >
                          Activar
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}