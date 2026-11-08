"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowLeft,
  Save,
  Truck,
  AlertCircle,
  CheckCircle,
  Loader2,
  Calendar,
  ShieldAlert,
  User,
  Edit3,
  RefreshCw,
  ScanLine,
  StickyNote,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  vehicleService,
  Vehicle,
  VehicleStatus,
  VehicleType,
  type VehicleUpdateInput,
} from "@/services/vehicle.service";
import { toast } from "sonner";
import { isAssignmentConflict } from "@/lib/assignment-revision";
import { isVehiclePlateConflict } from "@/lib/vehicle-revision";
import {
  OperationNotice,
  OperationsHeader,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { cn } from "@/lib/utils";

function insuranceDateLabel(value: string) {
  if (!value) return "Fecha no informada";
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return value < today
    ? "Fecha de vencimiento pasada"
    : value === today
      ? "Vence hoy"
      : "Vencimiento futuro";
}

export default function EditVehiclePage() {
  const router = useRouter();
  const params = useParams();
  const vehicleId = typeof params.id === "string" ? params.id : "";

  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const snapshotRef = useRef<{ id: string; revision?: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [conflicted, setConflicted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Estado inicial vacío
  const [formData, setFormData] = useState<{
    plate: string;
    type: VehicleType;
    model: string;
    color: string;
    year: number;
    status: VehicleStatus;
    insurance_expiry: string;
    notes: string;
    rider_name?: string | null;
    rider_id?: string | null;
    rider_profile_id?: string | null;
  }>({
    plate: "",
    type: "MOTO",
    model: "",
    color: "",
    year: new Date().getFullYear(),
    status: "ACTIVO",
    insurance_expiry: "",
    notes: "",
    rider_name: null,
    rider_id: null,
    rider_profile_id: null,
  });

  useEffect(() => {
    let active = true;
    snapshotRef.current = null;
    setConflicted(false);
    setSuccess(false);
    setSaving(false);
    const loadVehicle = async () => {
      if (!vehicleId) {
        setError("ID de vehículo no informado.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const data = await vehicleService.getById(vehicleId);
        if (!active) return;
        if (
          typeof data.id !== "string" ||
          data.id.toLowerCase() !== vehicleId.toLowerCase()
        )
          throw new Error("La ficha no coincide con el vehículo solicitado.");
        snapshotRef.current = { id: vehicleId, revision: data.edit_revision };
        setFormData({
          plate: data.plate,
          type: data.type,
          model: data.model,
          color: data.color,
          year: data.year,
          status: data.status,
          insurance_expiry: data.insurance_expiry || "",
          notes: data.notes || "",
          rider_name: data.rider_name,
          rider_id: data.rider_id,
          rider_profile_id: data.rider_profile_id ?? null,
        });
      } catch (err: any) {
        if (!active) return;
        const msg =
          err.message || "No se pudo cargar la información del vehículo.";
        setError(msg);
        toast.error(msg);
      } finally {
        if (active) setLoading(false);
      }
    };

    loadVehicle();
    const timers = redirectTimer;
    return () => {
      active = false;
      snapshotRef.current = null;
      if (timers.current) {
        clearTimeout(timers.current);
        timers.current = null;
      }
    };
  }, [vehicleId, reloadKey]);

  const handleChange = (field: string, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (error && !conflicted) setError(null);
  };

  const handleSave = async () => {
    const snapshot = snapshotRef.current;
    if (!snapshot || snapshot.id !== vehicleId || conflicted || saving) return;
    // Validaciones básicas
    if (
      !formData.plate.trim() ||
      !formData.model.trim() ||
      !formData.color.trim()
    ) {
      setError(
        "Por favor completa los campos obligatorios (Placa, Modelo, Color).",
      );
      return;
    }
    if (
      !Number.isInteger(formData.year) ||
      formData.year < 1900 ||
      formData.year > new Date().getFullYear() + 1
    ) {
      setError("Año del vehículo inválido.");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      // Limpieza de datos: Convertir null a undefined y excluir campos de solo lectura
      const payload: VehicleUpdateInput = {
        plate: formData.plate,
        type: formData.type,
        model: formData.model,
        color: formData.color,
        year: formData.year,
        status: formData.status,
        // Null expresa que el usuario limpió el campo; undefined lo dejaría sin cambios.
        insurance_expiry: formData.insurance_expiry || null,
        notes: formData.notes || null,
      };

      await vehicleService.update(snapshot.id, payload, snapshot.revision);
      if (snapshotRef.current !== snapshot) return;

      setSuccess(true);
      redirectTimer.current = setTimeout(() => {
        if (snapshotRef.current === snapshot)
          router.push("/manager/fleet/vehicles");
      }, 1500);
    } catch (err: any) {
      if (snapshotRef.current !== snapshot) return;
      if (isAssignmentConflict(err) && !isVehiclePlateConflict(err))
        setConflicted(true);
      setError(err.message || "Error al guardar los cambios.");
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center bg-gray-50">
        <div className="text-center">
          <Loader2 className="animate-spin motion-reduce:animate-none h-10 w-10 text-blue-600 mx-auto mb-4" />
          <p className="text-gray-500">Cargando datos del vehículo...</p>
        </div>
      </div>
    );
  }

  if (!snapshotRef.current || snapshotRef.current.id !== vehicleId)
    return (
      <div className={cn(operationStyles.page, "max-w-4xl")}>
        <OperationsHeader
          icon={Truck}
          eyebrow="Flota · Ficha"
          title="Editar Vehículo"
          description="Carga la ficha registrada antes de editar."
          actions={
            <>
              <Button
                className={operationStyles.button}
                onClick={() => router.back()}
              >
                <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                Volver
              </Button>
              <Button
                className={operationStyles.button}
                onClick={() => setReloadKey((key) => key + 1)}
              >
                <RefreshCw aria-hidden="true" className="h-4 w-4" />
                Recargar ficha
              </Button>
            </>
          }
        />
        <OperationNotice role="alert" tone="error">
          {error || "La ficha no está disponible para editar."}
        </OperationNotice>
      </div>
    );

  return (
    <div className={cn(operationStyles.page, "max-w-4xl")}>
      <OperationsHeader
        icon={Truck}
        eyebrow="Flota · Ficha de vehículo"
        title="Editar Vehículo"
        description="Gestiona la información técnica y estado."
        actions={
          <>
            <Button
              variant="outline"
              className={operationStyles.button}
              disabled={saving}
              onClick={() => router.back()}
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver
            </Button>
            <Button
              variant="outline"
              className={operationStyles.button}
              disabled={saving}
              onClick={() => setReloadKey((key) => key + 1)}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Recargar ficha
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <span className="break-all font-mono">ID vehículo: {vehicleId}</span>
        <Badge
          variant={
            formData.status === "ACTIVO"
              ? "default"
              : formData.status === "BAJA"
                ? "destructive"
                : "secondary"
          }
        >
          {formData.status}
        </Badge>
      </div>

      {error && (
        <Alert
          variant="destructive"
          className="bg-red-50 border-red-200 animate-in fade-in slide-in-from-top-2"
        >
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert className="bg-green-50 border-green-200 text-green-800 animate-in fade-in slide-in-from-top-2">
          <CheckCircle className="h-4 w-4 text-green-600" />
          <AlertTitle>Éxito</AlertTitle>
          <AlertDescription>
            Vehículo actualizado correctamente. Redirigiendo...
          </AlertDescription>
        </Alert>
      )}

      <Card className={`${operationStyles.panel} overflow-hidden`}>
        <CardHeader className="border-b border-blue-100 bg-blue-50/60">
          <SectionHeading icon={ScanLine} title="Detalles del Vehículo" />
          <CardDescription>
            Información técnica, estado y asignación actual.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-5">
          <fieldset
            disabled={saving || success || conflicted}
            className="min-w-0 space-y-6"
          >
            {/* Fila 1: Datos Básicos */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="plate">Placa / Matrícula *</Label>
                <Input
                  id="plate"
                  value={formData.plate}
                  onChange={(e) =>
                    handleChange("plate", e.target.value.toUpperCase())
                  }
                  placeholder="ABC-123"
                  className={cn(
                    operationStyles.field,
                    "uppercase font-mono bg-white",
                  )}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="type">Tipo de Vehículo *</Label>
                <Select
                  value={formData.type}
                  onValueChange={(v: any) => handleChange("type", v)}
                >
                  <SelectTrigger id="type" className={operationStyles.field}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MOTO">🏍️ Moto</SelectItem>
                    <SelectItem value="AUTO">🚗 Auto</SelectItem>
                    <SelectItem value="FURGONETA">🚚 Furgoneta</SelectItem>
                    <SelectItem value="BICICLETA">🚲 Bicicleta</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="status">Estado Operativo *</Label>
                <Select
                  value={formData.status}
                  onValueChange={(v: any) => handleChange("status", v)}
                >
                  <SelectTrigger id="status" className={operationStyles.field}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ACTIVO">
                      <span className="text-green-600 font-bold mr-2">●</span>{" "}
                      Activo
                    </SelectItem>
                    <SelectItem value="MANTENIMIENTO">
                      <span className="text-yellow-600 font-bold mr-2">●</span>{" "}
                      Mantenimiento
                    </SelectItem>
                    <SelectItem value="BAJA">
                      <span className="text-red-600 font-bold mr-2">●</span> De
                      Baja
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Fila 2: Detalles Técnicos */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="model">Modelo *</Label>
                <Input
                  id="model"
                  value={formData.model}
                  onChange={(e) => handleChange("model", e.target.value)}
                  placeholder="Ej: Yamaha MT-03"
                  className={cn(operationStyles.field, "bg-white")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="color">Color *</Label>
                <Input
                  id="color"
                  value={formData.color}
                  onChange={(e) => handleChange("color", e.target.value)}
                  placeholder="Ej: Azul"
                  className={cn(operationStyles.field, "bg-white")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="year">Año *</Label>
                <Input
                  id="year"
                  type="number"
                  value={formData.year}
                  onChange={(e) => handleChange("year", Number(e.target.value))}
                  min={1900}
                  max={new Date().getFullYear() + 1}
                  className={cn(operationStyles.field, "bg-white")}
                />
              </div>
            </div>

            {/* Fila 3: Asignación y Seguros */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-gray-100">
              <div className="space-y-2">
                <Label className="flex items-center gap-2 text-gray-700">
                  <User className="w-4 h-4" /> Asignado a
                </Label>
                <div className="flex items-center justify-between p-3 bg-gray-50 border border-gray-200 rounded-md">
                  {formData.rider_name ? (
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-sm">
                        {formData.rider_name.charAt(0).toUpperCase()}
                      </div>
                      <span className="font-medium text-gray-900">
                        {formData.rider_name}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-gray-500 italic">
                      <ShieldAlert className="w-4 h-4" />
                      {formData.rider_id || formData.rider_profile_id
                        ? "Nombre de repartidor no informado"
                        : "Sin asignar"}
                    </div>
                  )}

                  {formData.rider_profile_id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                      onClick={() =>
                        router.push(
                          `/manager/fleet/riders/${encodeURIComponent(formData.rider_profile_id!)}`,
                        )
                      }
                    >
                      <Edit3 className="w-4 h-4 mr-1" /> Ver Rider
                    </Button>
                  )}
                </div>
                <p className="text-xs text-gray-500">
                  Para cambiar la asignación, gestiona al repartidor desde su
                  perfil.
                </p>
              </div>

              <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <SectionHeading
                  icon={Calendar}
                  title="Seguro del vehículo"
                  tone="amber"
                />
                <Label htmlFor="insurance" className="flex items-center gap-2">
                  <Calendar className="w-4 h-4" /> Vencimiento Seguro
                </Label>
                <Input
                  id="insurance"
                  type="date"
                  value={formData.insurance_expiry || ""}
                  onChange={(e) =>
                    handleChange("insurance_expiry", e.target.value)
                  }
                  className={cn(operationStyles.field, "bg-white")}
                />
                <p className="text-xs text-slate-600">
                  {insuranceDateLabel(formData.insurance_expiry)}
                </p>
              </div>
            </div>

            {/* Notas */}
            <div className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/50 p-4">
              <SectionHeading
                icon={StickyNote}
                title="Observaciones"
                tone="violet"
              />
              <Label htmlFor="notes">Notas Internas</Label>
              <Textarea
                id="notes"
                value={formData.notes || ""}
                onChange={(e) => handleChange("notes", e.target.value)}
                placeholder="Observaciones sobre mantenimiento, multas, historial..."
                rows={3}
                className={cn(operationStyles.field, "bg-white")}
              />
            </div>
          </fieldset>
        </CardContent>

        <CardFooter className="flex flex-wrap justify-between gap-3 border-t border-slate-100 bg-slate-50 p-4">
          <Button
            variant="outline"
            onClick={() => router.back()}
            disabled={saving}
            className={operationStyles.button}
          >
            Cancelar
          </Button>
          <Button
            onClick={handleSave}
            disabled={
              saving ||
              success ||
              conflicted ||
              snapshotRef.current?.id !== vehicleId
            }
            className={operationStyles.primaryButton}
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Guardando...
              </>
            ) : (
              <>
                <Save className="mr-2 h-4 w-4" /> Guardar Cambios
              </>
            )}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
