import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";
import {
  validateBonusRequest,
  validateBonusResult,
  validatePlatformSettings,
  validateSettingsUpdate,
} from "@/lib/platform-settings";
export interface PlatformSettings {
  revision: string;
  delivery_fee_base: number | null;
  commission_percentage: number | null;
  min_order_amount: number | null;
  rider_delivery_bonus: number | null;
  rider_failed_attempt_bonus: number | null;
  active_zones: string[];
  support_email: string | null;
  maintenance_mode: boolean;
  updated_at?: string | null;
  updated_by_user_id?: string | null;
}
export type PlatformSettingsUpdate = Partial<{
  delivery_fee_base: number;
  commission_percentage: number;
  min_order_amount: number;
  rider_delivery_bonus: number;
  rider_failed_attempt_bonus: number;
  active_zones: string[];
  support_email: string;
  maintenance_mode: boolean;
}>;
export interface BonusSimulationRequest {
  new_base_bonus?: number;
  days_projection?: number;
  expected_settings_revision?: string;
}
export interface BonusSimulationResponse {
  current_monthly_cost: number;
  projected_monthly_cost: number;
  difference: number;
  percentage_increase: number;
  message: string;
  comparison_basis: "flat_bonus_same_deliveries";
  history_days: number;
  period_start: string;
  period_end: string;
  completed_deliveries: number;
  failed_bonus_deliveries: number;
  undated_bonus_deliveries: number;
  recorded_completed_bonus: number;
  recorded_failed_bonus: number;
  historical_cost: number;
  scenario_cost: number;
  applied_bonus: number;
  current_base_bonus: number;
  proposed_base_bonus: number;
  settings_revision: string;
  percentage_change: number | null;
  currency: null;
}
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const session = captureAuthSession(),
    result = await request();
  if (!isCurrentAuthSession(session)) throw new SessionChangedError();
  return result;
}
export const settingsService = {
  getSettings: async (): Promise<PlatformSettings> =>
    validatePlatformSettings(
      await inSession(() => api.get<unknown>("/settings")),
    ),
  updateSettings: async (
    settings: PlatformSettingsUpdate,
    revision: string,
  ): Promise<PlatformSettings> => {
    validateSettingsUpdate(settings);
    if (typeof revision !== "string" || !/^s1-[0-9a-f]{64}$/.test(revision))
      throw new Error(
        "Recarga la configuración para obtener una revisión válida.",
      );
    const captured = {
      ...settings,
      ...(settings.active_zones
        ? { active_zones: [...settings.active_zones] }
        : {}),
    };
    return validatePlatformSettings(
      await inSession(() =>
        api.patch<unknown>("/settings", captured, {
          headers: { "If-Match": `"${revision}"` },
        }),
      ),
    );
  },
  simulateBonusImpact: async (
    request: BonusSimulationRequest,
  ): Promise<BonusSimulationResponse> => {
    const captured = { ...request };
    validateBonusRequest(captured);
    if (!captured.expected_settings_revision)
      throw new Error(
        "Recarga la configuración antes de simular con su revisión.",
      );
    return validateBonusResult(
      await inSession(() =>
        api.post<unknown>("/settings/simulate-bonus", captured),
      ),
      captured,
    );
  },
};
