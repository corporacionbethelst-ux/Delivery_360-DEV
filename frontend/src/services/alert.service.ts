import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";

export type AlertType =
  | "DELAY"
  | "FAILURE"
  | "VEHICLE"
  | "SYSTEM"
  | "PAYMENT"
  | "RIDER"
  | "SLA_WARNING";
export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export interface Alert {
  id: string;
  type: AlertType;
  severity: AlertSeverity;
  title: string;
  description: string;
  createdAt: string;
  orderId?: string | null;
  riderId?: string | null;
  isRead: boolean;
  isDismissed: boolean;
  status: "UNREAD" | "READ";
}
export interface AlertFilters {
  status?: "ALL" | "UNREAD" | "READ";
  limit?: number;
  offset?: number;
}
export interface AlertReadAllResponse {
  count: number;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Respuesta de alertas no válida.");
  return value as Record<string, unknown>;
}
export function validatePersonalAlert(value: unknown): Alert {
  const row = record(value);
  if (
    typeof row.id !== "string" ||
    !row.id.trim() ||
    ["type", "severity", "title", "description", "createdAt"].some(
      (field) => typeof row[field] !== "string",
    ) ||
    typeof row.isRead !== "boolean" ||
    typeof row.isDismissed !== "boolean" ||
    row.status !== (row.isRead ? "READ" : "UNREAD") ||
    [row.orderId, row.riderId].some(
      (id) => id != null && (typeof id !== "string" || !id.trim()),
    )
  )
    throw new Error(
      "La alerta recibida tiene datos incoherentes. Actualiza la bandeja.",
    );
  // Unknown type/severity strings remain visible; they must not become LOW/SYSTEM.
  return { ...row } as unknown as Alert;
}
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const session = captureAuthSession();
  const result = await request();
  if (!isCurrentAuthSession(session)) throw new SessionChangedError();
  return result;
}
const encodedId = (id: string) => {
  if (typeof id !== "string" || !id.trim())
    throw new Error("ID de alerta requerido.");
  return encodeURIComponent(id);
};
export const alertService = {
  getAll: async (params: AlertFilters = {}): Promise<Alert[]> => {
    const limit = params.limit ?? 50,
      offset = params.offset ?? 0;
    if (
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 200 ||
      !Number.isSafeInteger(offset) ||
      offset < 0 ||
      (params.status !== undefined &&
        !["ALL", "READ", "UNREAD"].includes(params.status))
    )
      throw new Error("Los filtros de alertas no son válidos.");
    const query = new URLSearchParams();
    if (params.status && params.status !== "ALL")
      query.set("status", params.status);
    if (params.limit !== undefined) query.set("limit", String(limit));
    if (params.offset !== undefined) query.set("offset", String(offset));
    const encoded = query.toString();
    const response = await inSession(() =>
      api.get<unknown>(`/alerts${encoded ? `?${encoded}` : ""}`),
    );
    if (!Array.isArray(response) || response.length > limit)
      throw new Error("Respuesta de alertas no válida. Reintenta la consulta.");
    const rows = response.map(validatePersonalAlert);
    if (
      new Set(rows.map((row) => row.id)).size !== rows.length ||
      (params.status &&
        params.status !== "ALL" &&
        rows.some((row) => row.status !== params.status))
    )
      throw new Error(
        "La respuesta de alertas no corresponde a la consulta. Actualiza la bandeja.",
      );
    return rows;
  },
  markAsRead: async (id: string): Promise<void> => {
    const encoded = encodedId(id);
    const result = record(
      await inSession(() => api.patch<unknown>(`/alerts/${encoded}/read`)),
    );
    if (result.id !== id)
      throw new Error(
        "No se pudo confirmar la alerta leída. Actualiza la bandeja.",
      );
  },
  markAllAsRead: async (): Promise<AlertReadAllResponse> => {
    const result = record(
      await inSession(() => api.post<unknown>("/alerts/read-all")),
    );
    if (
      typeof result.count !== "number" ||
      !Number.isSafeInteger(result.count) ||
      result.count < 0
    )
      throw new Error(
        "No se pudo confirmar el número de alertas leídas. Actualiza la bandeja antes de repetir.",
      );
    return { count: result.count };
  },
  dismiss: async (id: string): Promise<void> => {
    const encoded = encodedId(id);
    const result = record(
      await inSession(() => api.delete<unknown>(`/alerts/${encoded}`)),
    );
    if (result.id !== id)
      throw new Error(
        "No se pudo confirmar la alerta descartada. Actualiza la bandeja.",
      );
  },
};
