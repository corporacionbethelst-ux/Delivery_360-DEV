'use client';

import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRidersStore } from '@/stores/ridersStore';
import { vehicleService, type Vehicle } from '@/services/vehicle.service';
import { toast } from 'sonner';
import type { RiderVehicleType } from '@/types/rider';

// Esquema de validación: Mantenemos fullName en el form para facilidad del usuario,
// pero lo dividiremos antes de enviar.
const riderFormSchema = z.object({
  fullName: z.string().min(3, 'El nombre completo es requerido'),
  email: z.string().email('Email inválido'),
  phone: z.string().min(8, 'Teléfono inválido'),
  cpf: z.string().min(9, 'CPF/Documento requerido'),
  birthDate: z.string().min(1, 'Fecha de nacimiento requerida'),
  vehicleOwnershipType: z.enum(['PROPIO', 'EMPRESA']).default('PROPIO'),
  vehicleType: z.enum(['MOTO', 'BICICLETA', 'AUTO', 'PIE', 'NO_ESPECIFICADO']),
  vehiclePlate: z.string().optional(),
  assignedVehicleId: z.string().optional(),
  operatingZone: z.string().min(1, 'Zona requerida'),
  password: z.string().min(6, 'La contraseña debe tener al menos 6 caracteres'),
});

type RiderFormValues = z.infer<typeof riderFormSchema>;

interface RiderRegistrationFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

export default function RiderRegistrationForm({ onSuccess, onCancel }: RiderRegistrationFormProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [companyVehicles, setCompanyVehicles] = useState<Vehicle[]>([]);
  const [isLoadingVehicles, setIsLoadingVehicles] = useState(false);
  const { createRider } = useRidersStore();

  const form = useForm<RiderFormValues>({
    resolver: zodResolver(riderFormSchema),
    defaultValues: {
      fullName: '',
      email: '',
      phone: '',
      cpf: '',
      birthDate: '',
      vehicleOwnershipType: 'PROPIO',
      vehicleType: 'MOTO',
      vehiclePlate: '',
      assignedVehicleId: '',
      operatingZone: '',
      password: '',
    },
  });

  // Cargar vehículos de la empresa cuando se selecciona "EMPRESA"
  const vehicleOwnershipType = form.watch('vehicleOwnershipType');

  useEffect(() => {
    if (vehicleOwnershipType === 'EMPRESA') {
      setIsLoadingVehicles(true);
      vehicleService.getAvailableCompanyVehicles()
        .then((vehicles) => {
          setCompanyVehicles(vehicles);
          if (vehicles.length > 0 && !form.getValues('assignedVehicleId')) {
            form.setValue('assignedVehicleId', vehicles[0].id);
          }
        })
        .catch((error) => {
          console.error('Error loading company vehicles:', error);
          toast.error('No se pudieron cargar los vehículos de la empresa');
        })
        .finally(() => {
          setIsLoadingVehicles(false);
        });
    }
  }, [vehicleOwnershipType]);

  const onSubmit = async (data: RiderFormValues) => {
    setIsSubmitting(true);
    try {
      // Lógica robusta para dividir Nombre y Apellido
      const nameParts = data.fullName.trim().split(/\s+/);
      const first_name = nameParts[0] || 'Nombre';
      // Si hay más de una palabra, el resto es apellido. Si no, usamos un placeholder.
      const last_name = nameParts.length > 1 ? nameParts.slice(1).join(' ') : 'Apellido';

      // Construimos el payload manualmente para asegurar compatibilidad con RiderCreateInput del store
      const payload: any = {
        email: data.email,
        password: data.password,
        first_name,       // Campo requerido por RiderCreateInput
        last_name,        // Campo requerido por RiderCreateInput
        phone: data.phone,
        operating_zone: data.operatingZone,
        vehicle_ownership_type: data.vehicleOwnershipType,
      };

      // Si es vehículo propio, enviamos los datos del vehículo
      if (data.vehicleOwnershipType === 'PROPIO') {
        payload.vehicle_type = data.vehicleType as RiderVehicleType;
        payload.vehicle_plate = data.vehiclePlate || undefined;
      } else {
        // Si es vehículo de empresa, asignamos el ID del vehículo seleccionado
        payload.assigned_vehicle_id = data.assignedVehicleId;
        // Obtenemos el tipo de vehículo del vehículo de empresa seleccionado
        const selectedVehicle = companyVehicles.find(v => v.id === data.assignedVehicleId);
        if (selectedVehicle) {
          payload.vehicle_type = selectedVehicle.type;
          payload.vehicle_plate = selectedVehicle.plate;
        }
      }

      // El store espera campos snake_case según la interfaz RiderCreateInput
      await createRider(payload);
      
      form.reset();
      toast.success('Repartidor registrado exitosamente');
      onSuccess?.();
    } catch (error: any) {
      console.error('Error al crear repartidor:', error);
      toast.error(error.message || 'Error al crear repartidor');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Registrar Nuevo Repartidor</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="fullName"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nombre Completo</FormLabel>
                  <FormControl>
                    <Input placeholder="Ej. Juan Pérez" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" placeholder="juan@ejemplo.com" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="phone"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Teléfono</FormLabel>
                    <FormControl>
                      <Input placeholder="+55 11 99999-9999" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="cpf"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>CPF / Documento</FormLabel>
                    <FormControl>
                      <Input placeholder="000.000.000-00" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="birthDate"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Fecha de Nacimiento</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="vehicleOwnershipType"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tipo de Vehículo</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Selecciona tipo" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="PROPIO">🏠 Vehículo Propio</SelectItem>
                        <SelectItem value="EMPRESA">🏢 Vehículo de Empresa</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {vehicleOwnershipType === 'PROPIO' ? (
                <>
                  <FormField
                    control={form.control}
                    name="vehicleType"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Tipo de Vehículo</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Selecciona vehículo" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="MOTO">🏍️ Moto</SelectItem>
                            <SelectItem value="BICICLETA">🚴 Bicicleta</SelectItem>
                            <SelectItem value="AUTO">🚗 Auto</SelectItem>
                            <SelectItem value="PIE">🚶 A pie</SelectItem>
                            <SelectItem value="NO_ESPECIFICADO">📦 Sin especificar</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="vehiclePlate"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Placa / Patente (Opcional)</FormLabel>
                        <FormControl>
                          <Input placeholder="ABC-1234" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </>
              ) : (
                <>
                  <FormField
                    control={form.control}
                    name="assignedVehicleId"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2">
                        <FormLabel>Vehículo de Empresa Asignado</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder={isLoadingVehicles ? "Cargando vehículos..." : "Selecciona un vehículo"} />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {isLoadingVehicles ? (
                              <SelectItem value="loading" disabled>Cargando...</SelectItem>
                            ) : companyVehicles.length === 0 ? (
                              <SelectItem value="none" disabled>No hay vehículos disponibles</SelectItem>
                            ) : (
                              companyVehicles.map((vehicle) => (
                                <SelectItem key={vehicle.id} value={vehicle.id}>
                                  {vehicle.plate} - {vehicle.model} ({vehicle.type})
                                </SelectItem>
                              ))
                            )}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </>
              )}
            </div>

            <FormField
              control={form.control}
              name="operatingZone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Zona de Operación</FormLabel>
                  <FormControl>
                    <Input placeholder="Ej. Centro, Norte, Sur..." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Contraseña Temporal</FormLabel>
                  <FormControl>
                    <Input type="password" placeholder="******" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex gap-2 pt-4">
              <Button 
                type="button" 
                variant="outline" 
                className="flex-1"
                onClick={onCancel}
              >
                Cancelar
              </Button>
              <Button 
                type="submit" 
                className="flex-1"
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Registrando...' : 'Registrar Repartidor'}
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}