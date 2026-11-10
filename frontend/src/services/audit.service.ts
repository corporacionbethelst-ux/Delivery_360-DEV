import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";
import {
  auditQuery,
  validateAuditCsv,
  validateAuditLog,
  validateAuditPage,
  validateAuditSummary,
} from "@/lib/system-audit";

export type AuditStatus = "SUCCESS" | "WARNING" | "FAILURE";
export interface AuditLog {
  id: string;
  action: string;
  action_type?: string | null;
  status: AuditStatus | (string & {});
  success: boolean;
  user_id?: string | null;
  user_email?: string | null;
  user_role?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  description?: string | null;
  details?: string | null;
  old_values?: Record<string, unknown> | null;
  new_values?: Record<string, unknown> | null;
  changes_summary?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  request_method?: string | null;
  request_path?: string | null;
  status_code?: number | null;
  error_message?: string | null;
  contains_personal_data?: boolean;
  created_at?: string | null;
}
export interface AuditLogResponse {
  items: AuditLog[];
  total: number;
  limit: number;
  offset: number;
}
export interface AuditFilters {
  limit?: number;
  offset?: number;
  action?: string;
  status?: AuditStatus | "ALL";
  user_id?: string;
  resource_type?: string;
  resource_id?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
}
export interface AuditSummary {
  period_start: string;
  period_days: number;
  total: number;
  by_action: Record<string, number>;
  by_success: Record<string, number>;
}
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const session = captureAuthSession(),
    result = await request();
  if (!isCurrentAuthSession(session)) throw new SessionChangedError();
  return result;
}
export const auditService = {
  getLogs: async (
    filters: Readonly<AuditFilters> = {},
  ): Promise<AuditLogResponse> => {
    const captured = { ...filters },
      query = auditQuery(captured);
    return validateAuditPage(
      await inSession(() => api.get<unknown>(`/audit${query}`)),
      captured,
    );
  },
  getSummary: async (days = 7): Promise<AuditSummary> => {
    if (!Number.isSafeInteger(days) || days < 1 || days > 365)
      throw new Error("El período del resumen debe estar entre 1 y 365 días.");
    return validateAuditSummary(
      await inSession(() => api.get<unknown>(`/audit/summary?days=${days}`)),
      days,
    );
  },
  getById: async (id: string): Promise<AuditLog> => {
    if (typeof id !== "string" || !id.trim())
      throw new Error("ID de auditoría requerido.");
    const row = validateAuditLog(
      await inSession(() =>
        api.get<unknown>(`/audit/${encodeURIComponent(id)}`),
      ),
    );
    if (row.id !== id)
      throw new Error("La respuesta no corresponde al evento solicitado.");
    return row;
  },
  exportCsv: async (filters: Readonly<AuditFilters> = {}): Promise<string> => {
    const query = auditQuery({ ...filters }, true);
    return validateAuditCsv(
      await inSession(() =>
        api.get<unknown>(`/audit/export${query}`, { responseType: "text" }),
      ),
    );
  },
};
