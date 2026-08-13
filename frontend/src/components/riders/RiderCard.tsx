'use client';

import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MapPin, Phone, Mail, Star } from 'lucide-react';
import type { Rider } from '@/types/rider';
import type { Vehicle } from '@/services/vehicle.service';

interface RiderCardProps {
  rider: Rider; 
  companyVehicles?: Vehicle[]; // Lista opcional de vehículos de empresa para resolver IDs
  onViewDetails?: (id: string) => void;
  onEdit?: (id: string) => void;
}

export default function RiderCard({ rider, companyVehicles = [], onViewDetails, onEdit }: RiderCardProps) {
  const getStatusColor = (status: string) => {
    const s = status.toUpperCase();
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
  const getVehicleInfo = () => {
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

  const vehicleInfo = getVehicleInfo();

  return (
    <Card className="hover:shadow-lg transition-shadow duration-200">
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-lg">
              {rider.fullName ? rider.fullName.split(' ').map(n => n[0]).join('').slice(0, 2) : 'RD'}
            </div>
            <div>
              <h3 className="font-semibold text-lg">{rider.fullName || 'Sin nombre'}</h3>
              <Badge className={getStatusColor(rider.status)}>{rider.status}</Badge>
            </div>
          </div>
          {rider.isOnline && (
            <div className="flex items-center gap-1 text-green-600 text-sm">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span>En línea</span>
            </div>
          )}
        </div>
      </CardHeader>
      
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="flex items-center gap-2 text-gray-600">
            <Phone className="w-4 h-4" />
            <span>{rider.phone || 'N/A'}</span>
          </div>
          <div className="flex items-center gap-2 text-gray-600">
            <Mail className="w-4 h-4" />
            <span className="truncate">{rider.email || 'N/A'}</span>
          </div>
        </div>
        
        {rider.operatingZone && (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <MapPin className="w-4 h-4" />
            <span>Zona: {rider.operatingZone}</span>
          </div>
        )}
        
        <div className="space-y-2 pt-2 border-t">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl">{vehicleInfo.icon}</span>
              <div className="space-y-0.5">
                <span className="text-sm font-medium text-gray-700">{vehicleInfo.type}</span>
                {vehicleInfo.plate && (
                  <div className="text-[10px] uppercase bg-slate-100 px-1.5 py-0.5 rounded text-slate-600 font-mono tracking-wide inline-block">
                    {vehicleInfo.plate}
                  </div>
                )}
              </div>
            </div>
            {vehicleInfo.ownershipType === 'EMPRESA' && (
              <Badge variant="outline" className="text-[9px] bg-blue-50 text-blue-700 border-blue-200 h-auto py-0 px-1">
                🏢 Empresa
              </Badge>
            )}
            {vehicleInfo.ownershipType === 'PROPIO' && (
              <Badge variant="outline" className="text-[9px] bg-green-50 text-green-700 border-green-200 h-auto py-0 px-1">
                🏠 Propio
              </Badge>
            )}
          </div>
          {rider.stats?.customerRating && (
            <div className="flex items-center gap-1 text-yellow-500 pt-1">
              <Star className="w-4 h-4 fill-current" />
              <span className="font-medium">{rider.stats.customerRating.toFixed(1)}</span>
            </div>
          )}
        </div>
        
        <div className="flex gap-2 pt-2">
          <Button 
            size="sm" 
            variant="outline" 
            className="flex-1"
            onClick={() => onViewDetails?.(rider.id)}
          >
            Ver Detalles
          </Button>
          {onEdit && (
            <Button 
              size="sm" 
              className="flex-1"
              onClick={() => onEdit?.(rider.id)}
            >
              Editar
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}