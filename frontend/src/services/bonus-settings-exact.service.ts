import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";
import {
  validateExactSettings,
  validateSettingsUpdate,
  validateBonusRequest,
  validateScenario,
  type ExactSettingsUpdate,
  type BonusRequest,
  type BonusActor,
} from "@/lib/bonus-settings-exact";
export type {
  ExactSettings as PlatformSettings,
  ExactSettingsUpdate as PlatformSettingsUpdate,
  ExactScenario as BonusSimulationResponse,
} from "@/lib/bonus-settings-exact";
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const s = captureAuthSession();
  const v = await request();
  if (!isCurrentAuthSession(s)) throw new SessionChangedError();
  return v;
}
export const settingsService = {
  getSettings: async () =>
    validateExactSettings(
      await inSession(() => api.get<unknown>("/settings/exact/v2")),
    ),
  updateSettings: async (patch: ExactSettingsUpdate, revision: string) => {
    validateSettingsUpdate(patch);
    if (!/^s2-[0-9a-f]{64}$/.test(revision))
      throw new Error("Recarga la configuración antes de guardar.");
    const captured = {
      ...patch,
      ...(patch.active_zones ? { active_zones: [...patch.active_zones] } : {}),
    };
    return validateExactSettings(
      await inSession(() =>
        api.patch<unknown>("/settings/exact/v2", captured, {
          headers: { "If-Match": `"${revision}"` },
        }),
      ),
    );
  },
  simulateBonusImpact: async (request: BonusRequest, actor: BonusActor) => {
    const captured = { ...request },
      identity = { ...actor };
    validateBonusRequest(captured);
    return validateScenario(
      await inSession(() =>
        api.post<unknown>("/settings/simulate-bonus/exact/v2", captured),
      ),
      captured,
      identity,
    );
  },
};
