"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  OperationNotice,
  OperationsHeader,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { payoutAmountLabel } from "@/lib/payout-contract";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  MapPin,
  Plus,
  Search,
  Globe,
  Edit,
  Trash2,
  Users,
  DollarSign,
  Clock,
  AlertCircle,
  Layers,
  CheckCircle,
  Loader2,
  AlertTriangle,
  RefreshCw, // MODIFICACIÓN: Agregado RefreshCw
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  zoneService,
  Zone as ZoneType,
  ZoneCreateInput,
} from "@/services/zone.service";

// Adaptamos la interfaz local para manejar tanto la respuesta de la API como la visualización
interface ZoneDisplay extends ZoneType {
  // Mapeamos campos snake_case a camelCase si es necesario para la UI local
  colorClass?: string; // Para mantener la lógica de colores visuales
}

// Mapa simple de códigos a colores Tailwind (en producción esto vendría de la DB 'color_hex')
const COLOR_MAP: Record<string, string> = {
  "#3b82f6": "bg-blue-500",
  "#22c55e": "bg-green-500",
  "#a855f7": "bg-purple-500",
  "#f97316": "bg-orange-500",
  "#ef4444": "bg-red-500",
  "#14b8a6": "bg-teal-500",
  "#6b7280": "bg-gray-500",
};

const DEFAULT_COLOR = "bg-gray-500";
const COLOR_NAMES: Record<string, string> = {
  "#3b82f6": "Azul",
  "#22c55e": "Verde",
  "#a855f7": "Violeta",
  "#f97316": "Naranja",
  "#ef4444": "Rojo",
  "#14b8a6": "Turquesa",
  "#6b7280": "Gris",
};
const countLabel = (value: number) =>
  Number.isSafeInteger(value) && value >= 0 ? value : "No informado";

export default function ZonesPage() {
  const router = useRouter();

  // Estados de Datos
  const [zones, setZones] = useState<ZoneDisplay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sequence = useRef(0);
  useEffect(() => {
    const requests = sequence;
    return () => {
      requests.current++;
    };
  }, []);

  // MODIFICACIÓN: Estado para el botón de actualizar
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Estados de UI
  const [searchTerm, setSearchTerm] = useState("");

  // Estados del diálogo de creación
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Estado para eliminación
  const [zoneToDelete, setZoneToDelete] = useState<ZoneDisplay | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Formulario de nueva zona
  const [newZoneData, setNewZoneData] = useState<ZoneCreateInput>({
    name: "",
    code: "",
    delivery_fee_base: 4000,
    cost_per_km: 0,
    estimated_time_min: 30,
    is_priority: false,
    is_active: true,
    color_hex: "#6b7280",
  });

  // Carga inicial de datos
  useEffect(() => {
    loadZones();
  }, []);

  const loadZones = async (isRefresh = false) => {
    const ticket = ++sequence.current;
    // MODIFICACIÓN: Solo mostrar spinner principal si no es un refresco manual
    if (!isRefresh) {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await zoneService.getAll({ limit: 100, page: 1 });
      if (ticket !== sequence.current) return;
      // Mapeamos datos de la API a nuestro formato de visualización
      const mappedZones = data.map((z) => ({
        ...z,
        colorClass: z.color_hex
          ? COLOR_MAP[z.color_hex] || DEFAULT_COLOR
          : DEFAULT_COLOR,
      }));
      setZones(mappedZones);
    } catch (err: any) {
      if (ticket !== sequence.current) return;
      console.error("Error loading zones");
      setError(err.message || "No se pudieron cargar las zonas.");
    } finally {
      if (ticket === sequence.current) {
        setLoading(false);
        setIsRefreshing(false);
      } // MODIFICACIÓN: Resetear estado de refresco
    }
  };

  // MODIFICACIÓN: Función para manejar el refresco manual
  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadZones(true);
  };

  // Filtrado optimizado en cliente
  const filteredZones = useMemo(() => {
    return zones.filter(
      (z) =>
        z.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        z.code.toLowerCase().includes(searchTerm.toLowerCase()),
    );
  }, [zones, searchTerm]);

  const handleCreateChange = (field: string, value: any) => {
    setNewZoneData((prev) => ({ ...prev, [field]: value }));
    if (createError) setCreateError(null);
  };

  const handleCreateSubmit = async () => {
    if (saving) return;
    // Validaciones
    if (!newZoneData.name.trim() || !newZoneData.code.trim()) {
      setCreateError("El nombre y el código son obligatorios.");
      return;
    }
    if (zones.some((z) => z.code === newZoneData.code.trim().toUpperCase())) {
      setCreateError("Ya existe una zona con ese código.");
      return;
    }

    setSaving(true);
    setCreateError(null);

    try {
      await zoneService.create({
        ...newZoneData,
        code: newZoneData.code.toUpperCase(),
        color_hex: newZoneData.color_hex || "#6b7280",
      });

      // Recargar lista y cerrar
      await loadZones();
      setIsCreateOpen(false);
      // Reset form
      setNewZoneData({
        name: "",
        code: "",
        delivery_fee_base: 4000,
        cost_per_km: 0,
        estimated_time_min: 30,
        is_priority: false,
        is_active: true,
        color_hex: "#6b7280",
      });
    } catch (err: any) {
      setCreateError(err.message || "Error al crear la zona.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!zoneToDelete || deleting) return;
    setDeleting(true);

    try {
      await zoneService.delete(zoneToDelete.id);
      await loadZones(); // Recargar para reflejar cambios
      setZoneToDelete(null);
    } catch (err: any) {
      alert(
        "Error al eliminar: " + (err.message || "No se pudo eliminar la zona."),
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className={operationStyles.page}>
      {/* Header */}
      <OperationsHeader
        audit
        icon={Globe}
        eyebrow="Flota · Cobertura"
        title="Zonas de Reparto"
        description="Configura áreas, tarifas y asignación de flota"
        actions={
          <>
            <Button
              variant="outline"
              className={operationStyles.button}
              onClick={handleRefresh}
              disabled={isRefreshing || loading}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-4 w-4 ${isRefreshing ? "animate-spin motion-reduce:animate-none" : ""}`}
              />
              Actualizar
            </Button>
            <Button
              className={operationStyles.primaryButton}
              onClick={() => setIsCreateOpen(true)}
              disabled={loading || isRefreshing}
            >
              <Plus aria-hidden="true" className="h-4 w-4" />
              Nueva Zona
            </Button>
          </>
        }
      />

      {error && (
        <Alert variant="destructive" className="bg-red-50 border-red-200">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void loadZones();
            }}
            className="ml-auto"
          >
            Reintentar
          </Button>
        </Alert>
      )}

      {/* Barra de Búsqueda y Filtros Rápidos */}
      <Card className={operationStyles.panel}>
        <CardHeader className="pb-3">
          <SectionHeading
            icon={Search}
            tone="violet"
            title="Buscar zonas cargadas"
            description="Búsqueda local sobre hasta 100 zonas de la primera página. No representa el catálogo completo."
          />
        </CardHeader>
        <CardContent className="p-4 flex flex-col md:flex-row gap-4 items-center">
          <div className="relative w-full md:flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
            <Input
              aria-label="Buscar zonas por nombre o código"
              placeholder="Buscar por nombre o código..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className={`${operationStyles.field} pl-10`}
              disabled={loading}
            />
          </div>
          <div className="text-sm text-gray-500 whitespace-nowrap">
            {loading
              ? "Cargando..."
              : error && !zones.length
                ? "Consulta no confirmada"
                : `Mostrando ${filteredZones.length} zonas cargadas`}
          </div>
        </CardContent>
      </Card>

      <Card
        className={operationStyles.panel}
        role="region"
        aria-label="Vista esquemática de zonas"
      >
        <CardHeader>
          <SectionHeading
            icon={Layers}
            tone="violet"
            title="Vista de zonas"
            description="Hasta ocho coincidencias de la consulta cargada. Representación esquemática, sin ubicación geográfica."
          />
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {loading ? (
            <p role="status" className="col-span-full p-5 text-slate-600">
              Consultando zonas…
            </p>
          ) : error && !zones.length ? (
            <p className="col-span-full text-sm text-slate-600">
              La vista estará disponible al confirmar la consulta.
            </p>
          ) : !filteredZones.length ? (
            <p className="col-span-full text-sm text-slate-600">
              Sin zonas para mostrar
            </p>
          ) : (
            filteredZones.slice(0, 8).map((zone) => (
              <Link
                key={zone.id}
                aria-label={`Ver zona ${zone.name}`}
                href={`/manager/fleet/zones/${encodeURIComponent(zone.id)}`}
                className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:border-violet-300 hover:bg-violet-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-600"
              >
                <span
                  aria-hidden="true"
                  className={`mb-3 block h-2 w-10 rounded-full ${zone.colorClass}`}
                />
                <p className="break-words text-sm font-semibold text-slate-900">
                  {zone.name}
                </p>
                <p className="mt-1 break-all font-mono text-xs text-slate-600">
                  {zone.code}
                </p>
                <p className="mt-2 text-xs text-slate-600">
                  {zone.is_active ? "Activa" : "Inactiva"}
                </p>
              </Link>
            ))
          )}
        </CardContent>
      </Card>

      {/* Grid de Tarjetas Detalladas */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card
              key={i}
              className="h-64 animate-pulse bg-gray-100 border-0"
            ></Card>
          ))}
        </div>
      ) : error && !zones.length ? (
        <OperationNotice>
          La consulta no está confirmada. Reintenta para conocer las zonas
          disponibles.
        </OperationNotice>
      ) : filteredZones.length === 0 ? (
        <div className="text-center py-20 bg-white rounded-xl border border-dashed border-gray-300">
          <Search className="w-12 h-12 mx-auto text-gray-300 mb-4" />
          <h3 className="text-lg font-medium text-gray-900">
            No se encontraron zonas
          </h3>
          <p className="text-gray-500">
            Intenta con otro término de búsqueda o crea una nueva.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredZones.map((zone) => (
            <Card
              key={zone.id}
              role="article"
              aria-label={`Zona ${zone.name}`}
              className={`${operationStyles.panel} group flex min-w-0 flex-col overflow-hidden transition-shadow hover:shadow-md`}
            >
              <div className={`h-2 w-full ${zone.colorClass}`} />
              <CardHeader className="pb-3 relative">
                <div className="flex justify-between items-start">
                  <div
                    className={`w-12 h-12 rounded-xl flex items-center justify-center text-white shadow-md motion-safe:transition-transform motion-safe:group-hover:scale-105 ${zone.colorClass}`}
                  >
                    <MapPin className="w-6 h-6" />
                  </div>
                  <div className="flex gap-1">
                    {zone.is_priority && (
                      <Badge
                        variant="destructive"
                        className="text-[10px] shadow-sm"
                      >
                        Prioritaria
                      </Badge>
                    )}
                    {!zone.is_active && (
                      <Badge
                        variant="secondary"
                        className="text-[10px] bg-gray-100 text-gray-600"
                      >
                        Inactiva
                      </Badge>
                    )}
                  </div>
                </div>
                <CardTitle className="mt-4 break-words text-lg">
                  <Link
                    className={operationStyles.link}
                    href={`/manager/fleet/zones/${encodeURIComponent(zone.id)}`}
                  >
                    {zone.name}
                  </Link>
                </CardTitle>
                <CardDescription className="flex items-center gap-2">
                  Código:{" "}
                  <span className="font-mono font-bold text-gray-700 bg-gray-100 px-2 py-0.5 rounded">
                    {zone.code}
                  </span>
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-4 flex-1">
                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-100">
                  <div className="space-y-1">
                    <div className="text-xs text-gray-500 flex items-center gap-1">
                      <Users className="w-3 h-3" /> Repartidores
                    </div>
                    <div className="font-bold text-lg text-gray-900">
                      {countLabel(zone.riders_count)}
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs text-gray-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" /> Pedidos Activos
                    </div>
                    <div className="font-bold text-lg text-gray-900">
                      {countLabel(zone.active_orders_count)}
                    </div>
                  </div>
                </div>

                <div className="flex justify-between items-center bg-gray-50 p-3 rounded-lg border border-gray-100">
                  <div className="text-sm text-gray-600 flex items-center gap-2">
                    <DollarSign className="w-4 h-4 text-gray-400" /> Tarifa Base
                  </div>
                  <div className="max-w-[60%] text-right text-sm font-bold text-indigo-800">
                    {payoutAmountLabel(zone.delivery_fee_base)}
                  </div>
                </div>
              </CardContent>

              <CardFooter className="pt-2 border-t bg-gray-50/50 p-3 gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50 transition-colors"
                  onClick={() =>
                    router.push(
                      `/manager/fleet/zones/${encodeURIComponent(zone.id)}`,
                    )
                  }
                >
                  <Edit className="w-3 h-3 mr-2" /> Configurar
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-red-500 hover:text-red-700 hover:bg-red-50"
                  onClick={() => setZoneToDelete(zone)}
                  aria-label={`Eliminar zona ${zone.name}`}
                  title="Eliminar zona"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {/* Diálogo de Creación de Zona */}
      <Dialog
        open={isCreateOpen}
        onOpenChange={(open) => {
          if (!saving) setIsCreateOpen(open);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus className="w-5 h-5 text-indigo-600" /> Crear Nueva Zona
            </DialogTitle>
            <DialogDescription>
              Define los parámetros básicos para una nueva área de reparto.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-4">
            {createError && (
              <Alert
                variant="destructive"
                className="bg-red-50 border-red-200 text-sm"
              >
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{createError}</AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Nombre *</Label>
                <Input
                  id="name"
                  disabled={saving}
                  value={newZoneData.name}
                  onChange={(e) => handleCreateChange("name", e.target.value)}
                  placeholder="Ej: Este Urbano"
                  className={operationStyles.field}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="code">Código *</Label>
                <Input
                  id="code"
                  disabled={saving}
                  value={newZoneData.code}
                  onChange={(e) =>
                    handleCreateChange("code", e.target.value.toUpperCase())
                  }
                  placeholder="EJ: EST"
                  className={`${operationStyles.field} uppercase font-mono`}
                  maxLength={5}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="fee">Tarifa Base</Label>
              <p className="text-xs text-slate-600">
                La consulta no informa moneda. Se guarda el importe configurado
                sin conversión.
              </p>
              <Input
                id="fee"
                disabled={saving}
                type="number"
                min="0"
                step="0.01"
                value={newZoneData.delivery_fee_base}
                onChange={(e) =>
                  handleCreateChange(
                    "delivery_fee_base",
                    Number(e.target.value),
                  )
                }
                className={operationStyles.field}
              />
            </div>

            <div className="flex items-center justify-between p-3 border rounded-lg bg-gray-50">
              <div className="space-y-0.5">
                <Label htmlFor="priority" className="text-sm font-semibold">
                  Zona Prioritaria
                </Label>
                <p className="text-xs text-gray-500">
                  Asignación preferente de riders.
                </p>
              </div>
              <Switch
                id="priority"
                disabled={saving}
                checked={newZoneData.is_priority}
                onCheckedChange={(v) => handleCreateChange("is_priority", v)}
              />
            </div>

            <div className="space-y-2">
              <p
                id="zone-color-label"
                className="text-sm font-semibold text-slate-700"
              >
                Color Identificativo
              </p>
              <div
                role="group"
                aria-labelledby="zone-color-label"
                className="flex gap-2 flex-wrap"
              >
                {Object.entries(COLOR_MAP).map(([hex, tailwindClass]) => (
                  <button
                    key={hex}
                    aria-label={`Color ${COLOR_NAMES[hex]}`}
                    aria-pressed={newZoneData.color_hex === hex}
                    disabled={saving}
                    type="button"
                    onClick={() => handleCreateChange("color_hex", hex)}
                    className={`w-8 h-8 rounded-full ${tailwindClass} motion-safe:transition-transform focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-700 focus-visible:ring-offset-2 ${newZoneData.color_hex === hex ? "ring-2 ring-offset-2 ring-gray-900 scale-110" : "hover:scale-105"}`}
                  />
                ))}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              className={operationStyles.button}
              variant="outline"
              onClick={() => setIsCreateOpen(false)}
              disabled={saving}
            >
              Cancelar
            </Button>
            <Button
              onClick={handleCreateSubmit}
              disabled={saving}
              className={operationStyles.primaryButton}
            >
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />{" "}
                  Guardando...
                </>
              ) : (
                "Crear Zona"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo de Confirmación de Eliminación */}
      <Dialog
        open={!!zoneToDelete}
        onOpenChange={() => {
          if (!deleting) setZoneToDelete(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <AlertTriangle className="w-5 h-5" /> Eliminar Zona
            </DialogTitle>
            <DialogDescription>
              ¿Estás seguro de eliminar la zona{" "}
              <strong>{zoneToDelete?.name}</strong>?
              <br />
              <br />
              <span className="text-orange-600 font-medium text-sm">
                Esta acción no se puede deshacer. Si hay repartidores asignados,
                el backend los liberará de esta zona.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setZoneToDelete(null)}
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
                  <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />{" "}
                  Eliminando...
                </>
              ) : (
                "Sí, eliminar"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
