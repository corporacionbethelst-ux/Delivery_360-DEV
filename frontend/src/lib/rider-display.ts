import { alertDate } from "@/lib/alert-date";
import type { Rider } from "@/types/user";

export const riderReadRoles = ["SUPERADMIN", "GERENTE", "OPERADOR"];
export const canManageRiders = (role?: string) =>
  role === "SUPERADMIN" || role === "GERENTE";
export function riderName(rider: Rider): string {
  return (
    [rider.first_name, rider.last_name].filter(Boolean).join(" ").trim() ||
    rider.full_name?.trim() ||
    "Nombre no informado"
  );
}
export function riderDate(value: unknown): string {
  return (
    alertDate(value)?.toLocaleString("es-VE", {
      timeZone: "America/Caracas",
    }) ?? "Fecha no informada"
  );
}
export function riderNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("es-VE", { maximumFractionDigits: 20 }).format(
        value,
      )
    : "No informado";
}
export function riderCoordinates(rider: Rider): string | null {
  const { last_lat: lat, last_lng: lng } = rider;
  return typeof lat === "number" &&
    Number.isFinite(lat) &&
    Math.abs(lat) <= 90 &&
    typeof lng === "number" &&
    Number.isFinite(lng) &&
    Math.abs(lng) <= 180
    ? `${lat.toFixed(6)}, ${lng.toFixed(6)}`
    : null;
}
export function riderVehicle(rider: Rider) {
  const assigned =
    rider.assigned_vehicle?.id === rider.assigned_vehicle_id
      ? rider.assigned_vehicle
      : undefined;
  return {
    type:
      (rider.vehicle_ownership_type === "EMPRESA"
        ? assigned?.type
        : rider.vehicle_type) || "Tipo no informado",
    plate:
      (rider.vehicle_ownership_type === "EMPRESA"
        ? assigned?.plate
        : rider.vehicle_plate) || "Placa no informada",
    ownership:
      rider.vehicle_ownership_type === "EMPRESA"
        ? "Empresa"
        : rider.vehicle_ownership_type === "PROPIO"
          ? "Propio"
          : "Propiedad no informada",
  };
}
