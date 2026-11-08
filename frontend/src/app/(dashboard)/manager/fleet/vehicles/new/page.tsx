"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft,
  Save,
  Loader2,
  AlertCircle,
  CheckCircle,
  Truck,
  ShieldCheck,
  StickyNote,
  ScanLine,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Textarea } from "@/components/ui/textarea";
import { vehicleService, VehicleType } from "@/services/vehicle.service";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  OperationsHeader,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";

export default function NewVehiclePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    plate: "",
    type: "" as VehicleType | "",
    model: "",
    color: "",
    year: new Date().getFullYear().toString(),
    insurance_expiry: "",
    notes: "",
  });

  const validateForm = () => {
    if (!formData.plate.trim()) return "La placa es requerida";
    if (!formData.type) return "El tipo de vehículo es requerido";
    if (!formData.model.trim()) return "El modelo es requerido";
    if (!formData.color.trim()) return "El color es requerido";

    const yearNum = Number(formData.year);
    if (
      !formData.year ||
      !Number.isInteger(yearNum) ||
      yearNum < 1900 ||
      yearNum > new Date().getFullYear() + 1
    )
      return "Año inválido (debe ser entre 1900 y el año siguiente)";

    return null;
  };

  const handleChange = (field: string, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    // Limpiar error cuando el usuario empieza a corregir
    if (error) setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateForm();

    if (validationError) {
      setError(validationError);
      toast.error(validationError);
      return;
    }

    setLoading(true);

    try {
      await vehicleService.create({
        plate: formData.plate.toUpperCase().replace(/\s/g, ""), // Eliminar espacios
        type: formData.type as VehicleType,
        model: formData.model,
        color: formData.color,
        year: Number(formData.year),
        insurance_expiry: formData.insurance_expiry || undefined,
        notes: formData.notes || undefined,
      });

      setSuccess(true);
      toast.success("Vehículo registrado exitosamente");

      // Pequeña pausa para mostrar el éxito antes de redirigir
      setTimeout(() => router.push("/manager/fleet/vehicles"), 1500);
    } catch (err: any) {
      console.error("Error creating vehicle");
      const msg =
        err.message ||
        "No se pudo registrar el vehículo. Verifica que la placa no exista.";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="p-6 max-w-2xl mx-auto flex items-center justify-center min-h-[60vh]">
        <Card className="bg-green-50 border-green-200 shadow-lg w-full">
          <CardContent className="py-12 flex flex-col items-center text-center">
            <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mb-4">
              <CheckCircle className="w-10 h-10 text-green-600" />
            </div>
            <h2 className="text-2xl font-bold text-green-800">
              ¡Vehículo Registrado!
            </h2>
            <p className="text-green-700 mt-2 max-w-md">
              El vehículo ha sido añadido exitosamente a la flota. Redirigiendo
              al listado...
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className={cn(operationStyles.page, "max-w-3xl")}>
      <OperationsHeader
        icon={Truck}
        eyebrow="Flota · Registro"
        title="Registrar Nuevo Vehículo"
        description="Ingresa los datos para añadirlo a la flota operativa"
        actions={
          <Button
            type="button"
            variant="outline"
            className={operationStyles.button}
            onClick={() => router.back()}
          >
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Volver
          </Button>
        }
      />

      {error && (
        <Alert
          variant="destructive"
          className="bg-red-50 border-red-200 text-red-800 animate-in fade-in slide-in-from-top-2"
        >
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error de Validación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className={`${operationStyles.panel} overflow-hidden`}>
        <CardHeader className="border-b border-blue-100 bg-blue-50/60">
          <SectionHeading icon={ScanLine} title="Información del Vehículo" />
          <CardDescription className="text-slate-500">
            Los campos marcados con * son obligatorios.
          </CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit}>
          <CardContent className="p-6 space-y-6">
            {/* Sección 1: Identificación Básica */}
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <div className="space-y-2">
                <Label
                  htmlFor="plate"
                  className="text-sm font-medium text-slate-700"
                >
                  Placa / Patente *
                </Label>
                <Input
                  id="plate"
                  value={formData.plate}
                  onChange={(e) =>
                    handleChange("plate", e.target.value.toUpperCase())
                  }
                  placeholder="ABC-123"
                  className={`${operationStyles.field} uppercase font-mono tracking-wide`}
                  disabled={loading}
                />
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="type"
                  className="text-sm font-medium text-slate-700"
                >
                  Tipo de Vehículo *
                </Label>
                <Select
                  value={formData.type}
                  onValueChange={(val) => handleChange("type", val)}
                  disabled={loading}
                >
                  <SelectTrigger id="type" className={operationStyles.field}>
                    <SelectValue placeholder="Seleccionar tipo" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MOTO">🏍️ Motocicleta</SelectItem>
                    <SelectItem value="BICICLETA">🚲 Bicicleta</SelectItem>
                    <SelectItem value="AUTO">🚗 Automóvil</SelectItem>
                    <SelectItem value="FURGONETA">🚚 Furgoneta</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="model"
                  className="text-sm font-medium text-slate-700"
                >
                  Modelo *
                </Label>
                <Input
                  id="model"
                  value={formData.model}
                  onChange={(e) => handleChange("model", e.target.value)}
                  placeholder="Ej: Yamaha MT-03"
                  disabled={loading}
                  className={operationStyles.field}
                />
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="color"
                  className="text-sm font-medium text-slate-700"
                >
                  Color *
                </Label>
                <Input
                  id="color"
                  value={formData.color}
                  onChange={(e) => handleChange("color", e.target.value)}
                  placeholder="Ej: Azul Noche"
                  disabled={loading}
                  className={operationStyles.field}
                />
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="year"
                  className="text-sm font-medium text-slate-700"
                >
                  Año *
                </Label>
                <Input
                  id="year"
                  type="number"
                  value={formData.year}
                  onChange={(e) => handleChange("year", e.target.value)}
                  min="1900"
                  max={new Date().getFullYear() + 1}
                  disabled={loading}
                  className={operationStyles.field}
                />
              </div>
              <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4 md:col-span-2">
                <SectionHeading
                  icon={ShieldCheck}
                  title="Seguro del vehículo"
                  tone="amber"
                  description="Registra la fecha de vencimiento cuando esté disponible."
                />
                <Label
                  htmlFor="insurance"
                  className="text-sm font-medium text-slate-700"
                >
                  Vencimiento del Seguro
                </Label>
                <Input
                  id="insurance"
                  type="date"
                  value={formData.insurance_expiry}
                  onChange={(e) =>
                    handleChange("insurance_expiry", e.target.value)
                  }
                  disabled={loading}
                  className={`${operationStyles.field} [&::-webkit-calendar-picker-indicator]:opacity-70 [&::-webkit-calendar-picker-indicator]:hover:opacity-100`}
                />
              </div>
            </div>

            {/* Separador */}
            <div className="relative py-2">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-slate-200" />
              </div>
            </div>

            {/* Sección 2: Notas */}
            <div className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/50 p-4">
              <SectionHeading
                icon={StickyNote}
                title="Observaciones"
                tone="violet"
              />
              <Label
                htmlFor="notes"
                className="text-sm font-medium text-slate-700"
              >
                Notas Adicionales
              </Label>
              <Textarea
                id="notes"
                value={formData.notes}
                onChange={(e) => handleChange("notes", e.target.value)}
                placeholder="Detalles adicionales sobre el vehículo, accesorios especiales, etc..."
                rows={3}
                disabled={loading}
                className={`${operationStyles.field} resize-none`}
              />
            </div>
          </CardContent>

          <CardFooter className="flex flex-wrap justify-end gap-3 border-t border-slate-100 bg-slate-50 p-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => router.back()}
              disabled={loading}
              className={operationStyles.button}
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              disabled={loading}
              className={operationStyles.primaryButton}
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" />{" "}
                  Guardando...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" /> Guardar Vehículo
                </>
              )}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
