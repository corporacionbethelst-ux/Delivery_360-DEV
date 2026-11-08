"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  ArrowLeft,
  Save,
  MapPin,
  AlertCircle,
  CheckCircle,
  Loader2,
  Globe,
  DollarSign,
  Clock,
  Users,
  Trash2,
  AlertTriangle,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { zoneService, Zone, ZoneCreateInput } from "@/services/zone.service";
import {
  OperationNotice,
  OperationsHeader,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { cn } from "@/lib/utils";

export default function EditZonePage() {
  const router = useRouter();
  const params = useParams();
  const zoneId = typeof params.id === "string" ? params.id : "";
  const snapshotRef = useRef<{ id: string } | null>(null);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [currentZone, setCurrentZone] = useState<Zone | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Usamos el tipo del servicio para mayor consistencia
  const [formData, setFormData] = useState<ZoneCreateInput>({
    name: "",
    code: "",
    description: "",
    delivery_fee_base: 0,
    cost_per_km: 0,
    estimated_time_min: 0,
    bonus_multiplier: 1.0,
    is_priority: false,
    is_active: true,
    color_hex: "#3b82f6",
    center_lat: null,
    center_lng: null,
  });

  useEffect(() => {
    let active = true;
    snapshotRef.current = null;
    setLoading(true);
    setCurrentZone(null);
    setSaving(false);
    setDeleting(false);
    setSuccess(false);
    setError(null);
    setShowDeleteDialog(false);
    const loadZone = async () => {
      if (!zoneId) {
        setError("ID de zona no informado.");
        setLoading(false);
        return;
      }
      try {
        const data = await zoneService.getById(zoneId);
        if (!active) return;
        if (
          typeof data.id !== "string" ||
          data.id.toLowerCase() !== zoneId.toLowerCase()
        )
          throw new Error("La ficha no coincide con la zona solicitada.");
        snapshotRef.current = { id: zoneId };
        setCurrentZone(data);
        setFormData({
          name: data.name,
          code: data.code,
          description: data.description ?? "",
          delivery_fee_base: data.delivery_fee_base,
          cost_per_km: data.cost_per_km,
          estimated_time_min: data.estimated_time_min,
          bonus_multiplier: data.bonus_multiplier ?? 1,
          is_priority: data.is_priority,
          is_active: data.is_active,
          color_hex: data.color_hex || "#3b82f6",
          center_lat: data.center_lat ?? null,
          center_lng: data.center_lng ?? null,
        });
      } catch (err: unknown) {
        if (active)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudo cargar la información de la zona.",
          );
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadZone();
    const timers = redirectTimer;
    return () => {
      active = false;
      snapshotRef.current = null;
      if (timers.current) {
        clearTimeout(timers.current);
        timers.current = null;
      }
    };
  }, [zoneId, reloadKey]);

  const handleChange = (field: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (error) setError(null);
  };
  const handleSave = async () => {
    const snapshot = snapshotRef.current;
    if (!snapshot || snapshot.id !== zoneId || saving || deleting || success)
      return;
    if (!formData.name.trim() || !formData.code.trim()) {
      setError("El nombre y código de la zona son obligatorios.");
      return;
    }
    if (
      ![formData.delivery_fee_base, formData.cost_per_km].every(
        (value) => Number.isFinite(value) && value >= 0,
      )
    ) {
      setError("Las tarifas deben ser números finitos no negativos.");
      return;
    }
    if (
      !Number.isInteger(formData.estimated_time_min) ||
      formData.estimated_time_min < 1 ||
      formData.estimated_time_min > 240
    ) {
      setError("El tiempo estimado debe ser un entero entre 1 y 240 minutos.");
      return;
    }
    if (
      typeof formData.bonus_multiplier !== "number" ||
      !Number.isFinite(formData.bonus_multiplier) ||
      formData.bonus_multiplier < 0.1 ||
      formData.bonus_multiplier > 5
    ) {
      setError("El multiplicador debe estar entre 0.1 y 5.");
      return;
    }
    if (
      (formData.center_lat != null &&
        (!Number.isFinite(formData.center_lat) ||
          Math.abs(formData.center_lat) > 90)) ||
      (formData.center_lng != null &&
        (!Number.isFinite(formData.center_lng) ||
          Math.abs(formData.center_lng) > 180))
    ) {
      setError(
        "Comprueba las coordenadas: latitud entre -90 y 90, longitud entre -180 y 180.",
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await zoneService.update(snapshot.id, { ...formData });
      if (snapshotRef.current !== snapshot) return;
      setSuccess(true);
      redirectTimer.current = setTimeout(() => {
        if (snapshotRef.current === snapshot)
          router.push("/manager/fleet/zones");
      }, 1500);
    } catch (err: unknown) {
      if (snapshotRef.current !== snapshot) return;
      setError(
        err instanceof Error ? err.message : "Error al guardar los cambios.",
      );
      setSaving(false);
    }
  };
  const handleDeleteConfirm = async () => {
    const snapshot = snapshotRef.current;
    if (!snapshot || snapshot.id !== zoneId || saving || deleting || success)
      return;
    setDeleting(true);
    setError(null);
    try {
      await zoneService.delete(snapshot.id);
      if (snapshotRef.current === snapshot)
        router.push("/manager/fleet/zones?deleted=true");
    } catch (err: unknown) {
      if (snapshotRef.current !== snapshot) return;
      setError(
        err instanceof Error ? err.message : "No se pudo eliminar la zona.",
      );
      setShowDeleteDialog(false);
      setDeleting(false);
    }
  };
  const busy = saving || deleting || success;

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="animate-spin motion-reduce:animate-none h-10 w-10 text-blue-600" />
      </div>
    );
  }

  if (!currentZone || snapshotRef.current?.id !== zoneId)
    return (
      <div className={cn(operationStyles.page, "max-w-5xl")}>
        <OperationsHeader
          audit
          icon={Globe}
          eyebrow="Flota · Ficha"
          title="Editar Zona"
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
    <div
      className={cn(
        operationStyles.page,
        "max-w-5xl pb-24 lg:pb-0 [&_h1]:break-words",
      )}
    >
      <OperationsHeader
        audit
        icon={Globe}
        eyebrow="Flota · Ficha de zona"
        title={`Editar Zona: ${currentZone.name}`}
        description="Configura tarifas, límites y reglas de esta área de reparto."
        actions={
          <>
            <Button
              variant="outline"
              className={operationStyles.button}
              disabled={busy}
              onClick={() => router.back()}
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver
            </Button>
            <Button
              variant="outline"
              className={operationStyles.button}
              disabled={busy}
              onClick={() => setReloadKey((key) => key + 1)}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Recargar ficha
            </Button>
          </>
        }
      />
      <p className="break-all font-mono text-xs text-slate-600">
        ID zona: {zoneId}
      </p>

      {error && (
        <Alert variant="destructive" className="bg-red-50 border-red-200">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert className="bg-green-50 border-green-200 text-green-800">
          <CheckCircle className="h-4 w-4 text-green-600" />
          <AlertDescription>
            Zona actualizada correctamente. Redirigiendo...
          </AlertDescription>
        </Alert>
      )}

      <fieldset
        disabled={busy}
        className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-3"
      >
        {/* Columna Izquierda: Configuración Principal */}
        <div className="lg:col-span-2 space-y-6">
          <Card className={operationStyles.panel}>
            <CardHeader className="border-b border-violet-100 bg-violet-50/60">
              <SectionHeading
                icon={Globe}
                title="Información General"
                tone="violet"
              />
              <CardDescription>
                Detalles identificativos de la zona.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Nombre de la Zona *</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) => handleChange("name", e.target.value)}
                    placeholder="Ej: Norte Industrial"
                    className={operationStyles.field}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="code">Código Corto *</Label>
                  <Input
                    id="code"
                    value={formData.code}
                    onChange={(e) =>
                      handleChange("code", e.target.value.toUpperCase())
                    }
                    placeholder="Ej: NRT"
                    className={cn(operationStyles.field, "uppercase font-mono")}
                    maxLength={5}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="desc">Descripción Operativa</Label>
                <Textarea
                  id="desc"
                  value={formData.description || ""}
                  onChange={(e) => handleChange("description", e.target.value)}
                  placeholder="Detalles sobre límites, referencias o restricciones..."
                  rows={3}
                  className={operationStyles.field}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="color">Color Identificativo</Label>
                <div className="flex gap-4 items-center">
                  <Input
                    id="color"
                    type="color"
                    value={formData.color_hex}
                    onChange={(e) => handleChange("color_hex", e.target.value)}
                    className={cn(
                      operationStyles.field,
                      "w-20 h-10 p-1 cursor-pointer",
                    )}
                  />
                  <span className="text-sm text-gray-500">
                    Color identificativo de la zona.
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className={operationStyles.panel}>
            <CardHeader className="border-b border-amber-100 bg-amber-50/60">
              <SectionHeading
                icon={DollarSign}
                title="Configuración de Tarifas y Tiempos"
                tone="amber"
              />
              <CardDescription>
                Importes configurados; esta consulta no informa moneda. No se
                realiza conversión.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-5">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label
                    htmlFor="fee"
                    className="flex items-center gap-2 text-gray-700"
                  >
                    <DollarSign aria-hidden="true" className="w-4 h-4" /> Tarifa
                    Base
                  </Label>
                  <Input
                    id="fee"
                    type="number"
                    step="0.01"
                    value={formData.delivery_fee_base}
                    onChange={(e) =>
                      handleChange("delivery_fee_base", Number(e.target.value))
                    }
                    min={0}
                    className={operationStyles.field}
                  />
                  <p className="text-xs text-gray-500">
                    Costo inicial del envío.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label
                    htmlFor="cost-km"
                    className="flex items-center gap-2 text-gray-700"
                  >
                    Costo por Km
                  </Label>
                  <Input
                    id="cost-km"
                    type="number"
                    step="0.01"
                    value={formData.cost_per_km}
                    onChange={(e) =>
                      handleChange("cost_per_km", Number(e.target.value))
                    }
                    min={0}
                    className={operationStyles.field}
                  />
                  <p className="text-xs text-gray-500">Variable distancia.</p>
                </div>
                <div className="space-y-2">
                  <Label
                    htmlFor="minutes"
                    className="flex items-center gap-2 text-gray-700"
                  >
                    <Clock className="w-4 h-4" /> Tiempo Est. (min)
                  </Label>
                  <Input
                    id="minutes"
                    type="number"
                    step="1"
                    max={240}
                    value={formData.estimated_time_min}
                    onChange={(e) =>
                      handleChange("estimated_time_min", Number(e.target.value))
                    }
                    min={1}
                    className={operationStyles.field}
                  />
                  <p className="text-xs text-gray-500">Promedio de entrega.</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Columna Derecha: Estado y Mapa */}
        <div className="space-y-6">
          <Card className={operationStyles.panel}>
            <CardHeader className="border-b border-emerald-100 bg-emerald-50/60">
              <SectionHeading
                icon={SlidersHorizontal}
                title="Estado y Prioridad"
                tone="emerald"
              />
            </CardHeader>
            <CardContent className="space-y-6 pt-5">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="zone-active" className="text-base">
                    Zona Activa
                  </Label>
                  <p className="text-xs text-gray-500">
                    Si se desactiva, no se aceptarán pedidos.
                  </p>
                </div>
                <Switch
                  id="zone-active"
                  checked={formData.is_active}
                  onCheckedChange={(v) => handleChange("is_active", v)}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="zone-priority" className="text-base">
                    Prioritaria
                  </Label>
                  <p className="text-xs text-gray-500">
                    Asignación preferente de repartidores.
                  </p>
                </div>
                <Switch
                  id="zone-priority"
                  checked={formData.is_priority}
                  onCheckedChange={(v) => handleChange("is_priority", v)}
                />
              </div>

              <div className="pt-4 border-t">
                <div className="flex items-center gap-2 text-sm text-gray-600 mb-2">
                  <Users className="w-4 h-4" /> Repartidores en zona
                </div>
                <div className="text-3xl font-bold text-gray-900">
                  {Number.isSafeInteger(currentZone.riders_count) &&
                  currentZone.riders_count >= 0
                    ? currentZone.riders_count
                    : "No informado"}
                </div>
              </div>

              {/* FASE 3: Multiplicador de Bono por Zona */}
              <div className="pt-4 border-t">
                <div className="space-y-3">
                  <Label
                    htmlFor="bonus"
                    className="text-base flex items-center gap-2"
                  >
                    <DollarSign className="w-4 h-4 text-indigo-600" />{" "}
                    Multiplicador de Bono
                  </Label>
                  <div className="flex items-center gap-3">
                    <Input
                      id="bonus"
                      type="number"
                      step="any"
                      min="0.1"
                      max="5.0"
                      value={formData.bonus_multiplier ?? 1.0}
                      onChange={(e) =>
                        handleChange("bonus_multiplier", Number(e.target.value))
                      }
                      className={cn(operationStyles.field, "w-24")}
                    />
                    <span className="text-sm text-gray-500">× (0.1 a 5.0)</span>
                  </div>
                  <p className="text-xs text-gray-500 leading-relaxed">
                    Este multiplicador se aplica al bono base de entregas. El
                    factor ajusta el bono base configurado. El ejemplo es
                    ilustrativo y no representa un pago.
                  </p>
                  {formData.bonus_multiplier &&
                    formData.bonus_multiplier !== 1.0 && (
                      <div className="mt-2 p-2 bg-indigo-50 border border-indigo-200 rounded text-xs text-indigo-800">
                        <strong>Ejemplo:</strong> Con base ilustrativa de 2.50
                        unidades × {formData.bonus_multiplier} ≈
                        <span className="font-bold ml-1">
                          {(2.5 * (formData.bonus_multiplier ?? 1.0)).toFixed(
                            2,
                          )}{" "}
                          unidades
                        </span>{" "}
                        por entrega exitosa
                      </div>
                    )}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className={`${operationStyles.panel} overflow-hidden`}>
            <CardHeader>
              <SectionHeading
                icon={MapPin}
                title="Ubicación Central"
                description="Coordenadas registradas. Vacío significa no informado; cero es una coordenada válida."
              />
            </CardHeader>
            <CardContent className="space-y-4 pt-5">
              <div className="space-y-2">
                <Label htmlFor="latitude">Latitud</Label>
                <Input
                  id="latitude"
                  type="number"
                  step="any"
                  min={-90}
                  max={90}
                  value={formData.center_lat ?? ""}
                  onChange={(e) =>
                    handleChange(
                      "center_lat",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                  className={operationStyles.field}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="longitude">Longitud</Label>
                <Input
                  id="longitude"
                  type="number"
                  step="any"
                  min={-180}
                  max={180}
                  value={formData.center_lng ?? ""}
                  onChange={(e) =>
                    handleChange(
                      "center_lng",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                  className={operationStyles.field}
                />
              </div>
            </CardContent>
          </Card>

          <Button
            variant="destructive"
            className="w-full mt-4"
            onClick={() => setShowDeleteDialog(true)}
          >
            <Trash2 className="w-4 h-4 mr-2" /> Eliminar Zona
          </Button>
        </div>
      </fieldset>

      <div className="fixed inset-x-0 bottom-0 z-30 flex flex-wrap justify-end gap-3 border-t border-slate-200 bg-white p-4 shadow-sm lg:static lg:rounded-2xl lg:border">
        <Button
          variant="outline"
          className={operationStyles.button}
          disabled={busy}
          onClick={() => router.back()}
        >
          Cancelar
        </Button>
        <Button
          className={operationStyles.primaryButton}
          onClick={handleSave}
          disabled={busy}
        >
          {saving ? (
            <>
              <Loader2
                aria-hidden="true"
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
              />
              Guardando...
            </>
          ) : (
            <>
              <Save aria-hidden="true" className="h-4 w-4" />
              Guardar Cambios
            </>
          )}
        </Button>
      </div>

      {/* Diálogo de Eliminación */}
      <Dialog
        open={showDeleteDialog}
        onOpenChange={(open) => {
          if (!deleting) setShowDeleteDialog(open);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <AlertTriangle className="w-5 h-5" /> Eliminar Zona
            </DialogTitle>
            <DialogDescription>
              ¿Estás seguro de eliminar la zona{" "}
              <strong>{currentZone.name}</strong>
              ?
              <br />
              <br />
              <span className="text-orange-600 font-medium">
                El backend liberará a los repartidores asignados a esta zona.
                Esta acción no se puede deshacer.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
              disabled={deleting}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />{" "}
                  Eliminando...
                </>
              ) : (
                "Sí, eliminar zona"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
