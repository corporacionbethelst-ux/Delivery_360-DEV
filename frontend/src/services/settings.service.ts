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
}
export interface BonusSimulationResponse {
  current_monthly_cost: number;
  projected_monthly_cost: number;
  difference: number;
  percentage_increase: number;
  message: string;
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
  ): Promise<PlatformSettings> => {
    validateSettingsUpdate(settings);
    const captured = {
      ...settings,
      ...(settings.active_zones
        ? { active_zones: [...settings.active_zones] }
        : {}),
    };
    return validatePlatformSettings(
      await inSession(() => api.patch<unknown>("/settings", captured)),
    );
  },
  simulateBonusImpact: async (
    request: BonusSimulationRequest,
  ): Promise<BonusSimulationResponse> => {
    const captured = { ...request };
    validateBonusRequest(captured);
    return validateBonusResult(
      await inSession(() =>
        api.post<unknown>("/settings/simulate-bonus", captured),
      ),
    );
  },
};
