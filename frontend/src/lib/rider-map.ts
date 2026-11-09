import type { Rider } from "@/types/user";
import { riderName, riderVehicle } from "@/lib/rider-display";

export const RIDER_MAP_POLL_MS = 20_000;
export const riderMapStatuses = {
  ACTIVO: "Activo",
  OCUPADO: "Ocupado",
  PENDIENTE: "Pendiente",
  SUSPENDIDO: "Suspendido",
  INACTIVO: "Inactivo",
};
export type RiderMapPoint = { rider: Rider; position: [number, number] };
export type RiderMapFocus = { position: [number, number]; sequence: number };
export function riderMapPosition(rider: Rider): [number, number] | null {
  const { last_lat: lat, last_lng: lng } = rider;
  return typeof lat === "number" &&
    Number.isFinite(lat) &&
    Math.abs(lat) <= 90 &&
    typeof lng === "number" &&
    Number.isFinite(lng) &&
    Math.abs(lng) <= 180
    ? [lat, lng]
    : null;
}
export const riderMapAvailability = (rider: Rider) =>
  rider.is_online === true
    ? "En línea"
    : rider.is_online === false
      ? "Desconectado"
      : "Disponibilidad no informada";
const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
export function riderMapMatches(
  rider: Rider,
  search: string,
  status: string,
  availability: string,
  location: string,
): boolean {
  const vehicle = riderVehicle(rider);
  const text = [
    rider.id,
    riderName(rider),
    rider.email,
    rider.phone,
    vehicle.plate,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    normalize(text).includes(normalize(search)) &&
    (status === "ALL" ||
      (status === "UNKNOWN" ? !rider.status : rider.status === status)) &&
    (availability === "ALL" ||
      (availability === "ONLINE"
        ? rider.is_online === true
        : availability === "OFFLINE"
          ? rider.is_online === false
          : rider.is_online == null)) &&
    (location === "ALL" ||
      (location === "VALID"
        ? !!riderMapPosition(rider)
        : !riderMapPosition(rider)))
  );
}
export function riderMapTelephone(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    !/^\+?[\d\s().-]+$/.test(value.trim()) ||
    !/\d/.test(value)
  )
    return null;
  return `tel:${value.trim().replace(/[\s().-]/g, "")}`;
}
