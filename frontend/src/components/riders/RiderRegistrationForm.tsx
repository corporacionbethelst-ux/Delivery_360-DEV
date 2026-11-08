"use client";

import { isEmailConflict } from "@/lib/email-conflict";
import { useState, useEffect, useRef, useCallback } from "react";
import { Bike, KeyRound, UserRound } from "lucide-react";
import {
  OperationNotice,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { riderFormSchema } from "@/lib/rider-validation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { useRidersStore } from "@/stores/ridersStore";
import { vehicleService, type Vehicle } from "@/services/vehicle.service";
import { toast } from "sonner";
import type { CreateRiderPayload } from "@/services/rider.service";
import {
  requireVehicleRevision,
  VehicleRevisionError,
} from "@/lib/vehicle-revision";
import { isAssignmentConflict } from "@/lib/assignment-revision";
import type { RiderVehicleType } from "@/types/rider";

// Esquema de validación: Mantenemos fullName en el form para facilidad del usuario,
// pero lo dividiremos antes de enviar.

type RiderFormValues = z.infer<typeof riderFormSchema>;

interface RiderRegistrationFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

export default function RiderRegistrationForm({
  onSuccess,
  onCancel,
}: RiderRegistrationFormProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [vehicleError, setVehicleError] = useState<string | null>(null);
  const alive = useRef(false),
    vehicleRequests = useRef(0),
    submitting = useRef(false);
  useEffect(() => {
    const requests = vehicleRequests;
    alive.current = true;
    return () => {
      alive.current = false;
      requests.current++;
    };
  }, []);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [companyVehicles, setCompanyVehicles] = useState<Vehicle[]>([]);
  const [isLoadingVehicles, setIsLoadingVehicles] = useState(false);
  const { createRider } = useRidersStore();

  const form = useForm<
    z.input<typeof riderFormSchema>,
    unknown,
    RiderFormValues
  >({
    resolver: zodResolver(riderFormSchema),
    defaultValues: {
      fullName: "",
      email: "",
      phone: "",
      cpf: "",
      vehicleOwnershipType: "PROPIO",
      vehicleType: "MOTO",
      vehiclePlate: "",
      assignedVehicleId: "",
      operatingZone: "",
      password: "",
    },
  });

  // Cargar vehículos de la empresa cuando se selecciona "EMPRESA"
  const vehicleOwnershipType = form.watch("vehicleOwnershipType");

  const loadVehicles = useCallback(async () => {
    if (!alive.current) return;
    const ticket = ++vehicleRequests.current;
    setSelectedVehicle(null);
    form.setValue("assignedVehicleId", "");
    setCompanyVehicles([]);
    setVehicleError(null);
    setIsLoadingVehicles(true);
    const current = () =>
      alive.current &&
      ticket === vehicleRequests.current &&
      form.getValues("vehicleOwnershipType") === "EMPRESA";
    try {
      const vehicles = await vehicleService.getAvailableCompanyVehicles();
      if (!current()) return;
      setCompanyVehicles(vehicles);
      if (vehicles[0]) {
        form.setValue("assignedVehicleId", vehicles[0].id, {
          shouldValidate: true,
        });
        setSelectedVehicle({ ...vehicles[0] });
      }
    } catch {
      if (current()) {
        setVehicleError(
          "No se pudo comprobar la disponibilidad de vehículos. Reintenta la consulta.",
        );
        setCompanyVehicles([]);
      }
    } finally {
      if (current()) setIsLoadingVehicles(false);
    }
  }, [form]);
  useEffect(() => {
    if (vehicleOwnershipType === "EMPRESA") void loadVehicles();
    else {
      vehicleRequests.current++;
      setConflicted(false);
      setIsLoadingVehicles(false);
      setVehicleError(null);
      setSelectedVehicle(null);
      setCompanyVehicles([]);
      form.setValue("assignedVehicleId", "");
    }
  }, [vehicleOwnershipType, loadVehicles, form]);

  const onSubmit = async (data: RiderFormValues) => {
    if (conflicted || submitting.current || completed || !alive.current) return;
    submitting.current = true;
    setSubmitError(null);
    setIsSubmitting(true);
    try {
      // Lógica robusta para dividir Nombre y Apellido
      const nameParts = data.fullName.trim().split(/\s+/);
      const first_name = nameParts[0];
      // El formulario exige nombre y apellido antes de construir el payload.
      const last_name = nameParts.slice(1).join(" ");

      // Construimos el payload manualmente para asegurar compatibilidad con RiderCreateInput del store
      const payload: CreateRiderPayload = {
        vehicle_type: data.vehicleType,
        email: data.email,
        password: data.password,
        first_name, // Campo requerido por RiderCreateInput
        last_name, // Campo requerido por RiderCreateInput
        phone: data.phone,
        cpf: data.cpf,
        operating_zone: data.operatingZone,
        vehicle_ownership_type: data.vehicleOwnershipType,
      };

      // Si es vehículo propio, enviamos los datos del vehículo
      if (data.vehicleOwnershipType === "PROPIO") {
        payload.vehicle_type = data.vehicleType as RiderVehicleType;
        payload.vehicle_plate = data.vehiclePlate || undefined;
      } else {
        // Si es vehículo de empresa, asignamos el ID del vehículo seleccionado
        payload.assigned_vehicle_id = data.assignedVehicleId;
        if (!selectedVehicle || selectedVehicle.id !== data.assignedVehicleId)
          throw new VehicleRevisionError();
        payload.expected_vehicle_revision = requireVehicleRevision(
          selectedVehicle.revision,
        );
        payload.vehicle_type = selectedVehicle.type;
        payload.vehicle_plate = selectedVehicle.plate;
      }

      // El store espera campos snake_case según la interfaz RiderCreateInput
      await createRider(payload);

      if (!alive.current) return;
      setCompleted(true);
      form.reset();
      toast.success("Repartidor registrado exitosamente");
      try {
        onSuccess?.();
      } catch {
        setSubmitError(
          "El repartidor se registró, pero no se pudo continuar. Vuelve al listado.",
        );
      }
    } catch (error: any) {
      if (!alive.current) return;
      setSubmitError(
        error instanceof Error
          ? error.message
          : "No se pudo registrar el repartidor.",
      );
      if (isAssignmentConflict(error) && !isEmailConflict(error))
        setConflicted(true);
      toast.error(error.message || "Error al crear repartidor");
    } finally {
      submitting.current = false;
      if (alive.current) setIsSubmitting(false);
    }
  };

  const displayedCompanyVehicles =
    selectedVehicle && !companyVehicles.some((v) => v.id === selectedVehicle.id)
      ? [...companyVehicles, selectedVehicle]
      : companyVehicles.map((v) =>
          v.id === selectedVehicle?.id ? selectedVehicle : v,
        );

  const reloadVehicles = () => {
    setConflicted(false);
    setSubmitError(null);
    void loadVehicles();
  };

  return (
    <Card className={`${operationStyles.panel} overflow-hidden`}>
      <CardHeader className="border-b border-blue-100 bg-blue-50/60">
        <CardTitle className="text-lg">Registrar Nuevo Repartidor</CardTitle>
      </CardHeader>
      <CardContent className="pt-5">
        {submitError && (
          <OperationNotice role="alert" tone="warning">
            {submitError}
          </OperationNotice>
        )}
        {completed && (
          <OperationNotice role="status" tone="success">
            Repartidor registrado correctamente.
          </OperationNotice>
        )}
        {vehicleOwnershipType === "EMPRESA" && (
          <Button
            type="button"
            variant="outline"
            disabled={isSubmitting || completed || isLoadingVehicles}
            onClick={reloadVehicles}
          >
            Recargar vehículos
          </Button>
        )}
        {vehicleOwnershipType === "EMPRESA" && vehicleError && (
          <OperationNotice role="alert" tone="warning">
            {vehicleError}
          </OperationNotice>
        )}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
            <fieldset
              disabled={isSubmitting || completed}
              className="min-w-0 space-y-5"
            >
              <section className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/30 p-4">
                <SectionHeading icon={UserRound} title="Datos del repartidor" />
                <FormField
                  control={form.control}
                  name="fullName"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Nombre Completo</FormLabel>
                      <FormControl>
                        <Input
                          className={operationStyles.field}
                          placeholder="Ej. Juan Pérez"
                          {...field}
                        />
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
                          <Input
                            className={operationStyles.field}
                            type="email"
                            placeholder="juan@ejemplo.com"
                            {...field}
                          />
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
                          <Input
                            className={operationStyles.field}
                            placeholder="+55 11 99999-9999"
                            {...field}
                          />
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
                      <FormItem className="md:col-span-2">
                        <FormLabel>CPF / Documento</FormLabel>
                        <FormControl>
                          <Input
                            className={operationStyles.field}
                            placeholder="000.000.000-00"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </section>
              <section className="space-y-4 rounded-xl border border-violet-200 bg-violet-50/40 p-4">
                <SectionHeading
                  icon={Bike}
                  title="Vehículo y asignación"
                  tone="violet"
                />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="vehicleOwnershipType"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Propiedad del vehículo</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={field.value}
                        >
                          <FormControl>
                            <SelectTrigger className={operationStyles.field}>
                              <SelectValue placeholder="Selecciona tipo" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="PROPIO">
                              🏠 Vehículo Propio
                            </SelectItem>
                            <SelectItem value="EMPRESA">
                              🏢 Vehículo de Empresa
                            </SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  {vehicleOwnershipType === "PROPIO" ? (
                    <>
                      <FormField
                        control={form.control}
                        name="vehicleType"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Tipo de Vehículo</FormLabel>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value}
                            >
                              <FormControl>
                                <SelectTrigger
                                  className={operationStyles.field}
                                >
                                  <SelectValue placeholder="Selecciona vehículo" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="MOTO">🏍️ Moto</SelectItem>
                                <SelectItem value="BICICLETA">
                                  🚴 Bicicleta
                                </SelectItem>
                                <SelectItem value="AUTO">🚗 Auto</SelectItem>
                                <SelectItem value="PIE">🚶 A pie</SelectItem>
                                <SelectItem value="NO_ESPECIFICADO">
                                  📦 Sin especificar
                                </SelectItem>
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
                              <Input
                                className={operationStyles.field}
                                placeholder="ABC-1234"
                                {...field}
                              />
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
                        key="assigned-company-vehicle"
                        render={({ field }) => (
                          <FormItem className="md:col-span-2">
                            <FormLabel>Vehículo de Empresa Asignado</FormLabel>
                            <Select
                              disabled={
                                isLoadingVehicles || isSubmitting || completed
                              }
                              onValueChange={(id) => {
                                const chosen = companyVehicles.find(
                                  (v) => v.id === id,
                                );
                                if (!chosen) return;
                                field.onChange(id);
                                setSelectedVehicle({ ...chosen });
                              }}
                              value={field.value}
                            >
                              <FormControl>
                                <SelectTrigger
                                  className={operationStyles.field}
                                >
                                  <SelectValue
                                    placeholder={
                                      isLoadingVehicles
                                        ? "Cargando vehículos..."
                                        : "Selecciona un vehículo"
                                    }
                                  />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {isLoadingVehicles ? (
                                  <SelectItem value="loading" disabled>
                                    Cargando...
                                  </SelectItem>
                                ) : companyVehicles.length === 0 ? (
                                  <SelectItem value="none" disabled>
                                    {vehicleError
                                      ? "Disponibilidad no confirmada"
                                      : "No hay vehículos disponibles"}
                                  </SelectItem>
                                ) : (
                                  companyVehicles.map((vehicle) => (
                                    <SelectItem
                                      key={vehicle.id}
                                      value={vehicle.id}
                                    >
                                      {vehicle.plate} - {vehicle.model} (
                                      {vehicle.type})
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
              </section>
              <section className="space-y-4 rounded-xl border border-amber-200 bg-amber-50/40 p-4">
                <SectionHeading
                  icon={KeyRound}
                  title="Zona y acceso"
                  tone="amber"
                />
                <FormField
                  control={form.control}
                  name="operatingZone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Zona de Operación</FormLabel>
                      <FormControl>
                        <Input
                          className={operationStyles.field}
                          placeholder="Ej. Centro, Norte, Sur..."
                          {...field}
                        />
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
                        <Input
                          className={operationStyles.field}
                          type="password"
                          placeholder="******"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </section>
            </fieldset>
            <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-4">
              <Button
                type="button"
                variant="outline"
                className={operationStyles.button}
                disabled={isSubmitting || completed}
                onClick={onCancel}
              >
                Cancelar
              </Button>
              <Button
                type="submit"
                className={operationStyles.primaryButton}
                disabled={
                  isSubmitting ||
                  completed ||
                  conflicted ||
                  (vehicleOwnershipType === "EMPRESA" &&
                    (isLoadingVehicles || !selectedVehicle))
                }
              >
                {isSubmitting
                  ? "Registrando..."
                  : completed
                    ? "Repartidor registrado"
                    : "Registrar Repartidor"}
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
