import type {
  PlatformSettings,
  PlatformSettingsUpdate,
  BonusSimulationRequest,
  BonusSimulationResponse,
} from "@/services/settings.service";
import { alertDate } from "@/lib/alert-date";

export const SETTING_NUMBERS = [
  "delivery_fee_base",
  "commission_percentage",
  "min_order_amount",
  "rider_delivery_bonus",
  "rider_failed_attempt_bonus",
] as const;
export const SETTING_LABELS = {
  delivery_fee_base: "Tarifa base de envío",
  commission_percentage: "Comisión (%)",
  min_order_amount: "Pedido mínimo",
  rider_delivery_bonus: "Bono por entrega",
  rider_failed_attempt_bonus: "Bono por intento fallido",
  support_email: "Email de soporte",
  active_zones: "Zonas activas",
  maintenance_mode: "Modo mantenimiento",
};
export type SettingsKey = keyof typeof SETTING_LABELS;
export type SettingsDraft = Record<(typeof SETTING_NUMBERS)[number], string> & {
  support_email: string;
  active_zones: string;
  maintenance_mode: boolean;
};
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Respuesta de configuración no válida.");
  return value as Record<string, unknown>;
};
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
export function validatePlatformSettings(value: unknown): PlatformSettings {
  const row = record(value);
  if (
    typeof row.revision !== "string" ||
    !/^s1-[0-9a-f]{64}$/.test(row.revision) ||
    SETTING_NUMBERS.some(
      (key) =>
        !(row[key] === null || (finite(row[key]) && (row[key] as number) >= 0)),
    ) ||
    (finite(row.commission_percentage) && row.commission_percentage > 100) ||
    !Array.isArray(row.active_zones) ||
    row.active_zones.some((zone) => typeof zone !== "string" || !zone.trim()) ||
    !(row.support_email === null || typeof row.support_email === "string") ||
    typeof row.maintenance_mode !== "boolean" ||
    [row.updated_at, row.updated_by_user_id].some(
      (value) => value != null && typeof value !== "string",
    )
  )
    throw new Error(
      "La configuración recibida tiene campos incompletos o no válidos.",
    );
  return {
    ...row,
    active_zones: [...row.active_zones],
  } as unknown as PlatformSettings;
}
export function validateSettingsUpdate(value: PlatformSettingsUpdate): void {
  const row = record(value),
    keys = Object.keys(row);
  if (!keys.length || keys.some((key) => !Object.hasOwn(SETTING_LABELS, key)))
    throw new Error(
      "La actualización no contiene cambios de configuración válidos.",
    );
  for (const key of SETTING_NUMBERS)
    if (
      Object.hasOwn(row, key) &&
      (!finite(row[key]) ||
        (row[key] as number) < 0 ||
        (key === "commission_percentage" && (row[key] as number) > 100))
    )
      throw new Error(
        `${SETTING_LABELS[key]} debe ser un número válido${key === "commission_percentage" ? " entre 0 y 100" : " no negativo"}.`,
      );
  if (
    Object.hasOwn(row, "maintenance_mode") &&
    typeof row.maintenance_mode !== "boolean"
  )
    throw new Error("Estado de mantenimiento no válido.");
  if (
    Object.hasOwn(row, "support_email") &&
    (typeof row.support_email !== "string" ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.support_email) ||
      row.support_email.length > 255)
  )
    throw new Error("Introduce un email de soporte válido.");
  if (
    Object.hasOwn(row, "active_zones") &&
    (!Array.isArray(row.active_zones) ||
      !row.active_zones.length ||
      row.active_zones.some(
        (zone) => typeof zone !== "string" || !zone.trim(),
      ) ||
      new Set(row.active_zones).size !== row.active_zones.length)
  )
    throw new Error("Introduce al menos una zona activa y evita duplicados.");
}
export function settingsDraft(row: PlatformSettings): SettingsDraft {
  return {
    delivery_fee_base:
      row.delivery_fee_base === null ? "" : String(row.delivery_fee_base),
    commission_percentage:
      row.commission_percentage === null
        ? ""
        : String(row.commission_percentage),
    min_order_amount:
      row.min_order_amount === null ? "" : String(row.min_order_amount),
    rider_delivery_bonus:
      row.rider_delivery_bonus === null ? "" : String(row.rider_delivery_bonus),
    rider_failed_attempt_bonus:
      row.rider_failed_attempt_bonus === null
        ? ""
        : String(row.rider_failed_attempt_bonus),
    support_email: row.support_email ?? "",
    active_zones: row.active_zones.join("\n"),
    maintenance_mode: row.maintenance_mode,
  };
}
export function settingsNumber(value: string, label: string): number {
  const text = value.trim();
  if (
    !/^(?:\d+(?:[.,]\d+)?|[.,]\d+)$/.test(text) ||
    !Number.isFinite(Number(text.replace(",", ".")))
  )
    throw new Error(
      `Introduce un número válido en ${label}; un campo vacío no equivale a cero.`,
    );
  return Number(text.replace(",", "."));
}
export const sameSetting = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
export function settingsChanges(
  base: PlatformSettings,
  draft: SettingsDraft,
): PlatformSettingsUpdate {
  const original = settingsDraft(base),
    patch: Record<string, unknown> = {};
  for (const key of SETTING_NUMBERS)
    if (draft[key] !== original[key]) {
      const value = settingsNumber(draft[key], SETTING_LABELS[key]);
      if (value !== base[key]) patch[key] = value;
    }
  if (
    draft.support_email !== original.support_email &&
    draft.support_email.trim() !== base.support_email
  )
    patch.support_email = draft.support_email.trim();
  if (draft.active_zones !== original.active_zones) {
    const zones = draft.active_zones
      .split(/\r?\n/)
      .map((zone) => zone.trim())
      .filter(Boolean);
    if (!sameSetting(zones, base.active_zones)) patch.active_zones = zones;
  }
  if (draft.maintenance_mode !== original.maintenance_mode)
    patch.maintenance_mode = draft.maintenance_mode;
  if (Object.keys(patch).length)
    validateSettingsUpdate(patch as PlatformSettingsUpdate);
  return patch as PlatformSettingsUpdate;
}
export function validateBonusRequest(value: BonusSimulationRequest): void {
  if (
    !finite(value.new_base_bonus) ||
    value.new_base_bonus < 0 ||
    value.new_base_bonus > 99999999.99 ||
    !Number.isSafeInteger(value.days_projection) ||
    (value.days_projection as number) < 1 ||
    (value.days_projection as number) > 90 ||
    (value.expected_settings_revision !== undefined &&
      !/^s1-[0-9a-f]{64}$/.test(value.expected_settings_revision))
  )
    throw new Error(
      "Introduce un bono no negativo y un período entero de 1 a 90 días.",
    );
}
export function validateBonusResult(
  value: unknown,
  expected?: BonusSimulationRequest,
): BonusSimulationResponse {
  const row = record(value);
  if (
    ![
      row.current_monthly_cost,
      row.projected_monthly_cost,
      row.difference,
      row.percentage_increase,
    ].every(finite) ||
    (row.current_monthly_cost as number) < 0 ||
    (row.projected_monthly_cost as number) < 0 ||
    typeof row.message !== "string" ||
    Math.abs(
      (row.current_monthly_cost as number) +
        (row.difference as number) -
        (row.projected_monthly_cost as number),
    ) > 0.021 ||
    row.comparison_basis !== "flat_bonus_same_deliveries" ||
    row.currency !== null ||
    typeof row.settings_revision !== "string" ||
    !/^s1-[0-9a-f]{64}$/.test(row.settings_revision) ||
    !Number.isSafeInteger(row.history_days) ||
    (row.history_days as number) < 1 ||
    (row.history_days as number) > 90 ||
    ![
      row.completed_deliveries,
      row.failed_bonus_deliveries,
      row.undated_bonus_deliveries,
    ].every((count) => Number.isSafeInteger(count) && (count as number) >= 0) ||
    ![
      row.recorded_completed_bonus,
      row.recorded_failed_bonus,
      row.historical_cost,
      row.scenario_cost,
      row.applied_bonus,
      row.current_base_bonus,
      row.proposed_base_bonus,
    ].every((amount) => finite(amount) && amount >= 0) ||
    (row.completed_deliveries === 0 && row.recorded_completed_bonus !== 0) ||
    (row.failed_bonus_deliveries === 0 && row.recorded_failed_bonus !== 0) ||
    (row.proposed_base_bonus as number) > 99999999.99 ||
    (row.applied_bonus as number) > 99999999.99 ||
    Math.abs(
      (row.applied_bonus as number) - (row.proposed_base_bonus as number),
    ) > 0.005001 ||
    typeof row.period_start !== "string" ||
    typeof row.period_end !== "string" ||
    !Number.isFinite(Date.parse(row.period_start)) ||
    !Number.isFinite(Date.parse(row.period_end)) ||
    !row.period_start.endsWith("Z") ||
    !row.period_end.endsWith("Z") ||
    Date.parse(row.period_end) - Date.parse(row.period_start) !==
      (row.history_days as number) * 86400000 ||
    row.current_monthly_cost !== row.historical_cost ||
    row.projected_monthly_cost !== row.scenario_cost ||
    Math.abs(
      (row.recorded_completed_bonus as number) +
        (row.recorded_failed_bonus as number) -
        (row.historical_cost as number),
    ) > 0.011 ||
    Math.abs(
      (row.applied_bonus as number) * (row.completed_deliveries as number) +
        (row.recorded_failed_bonus as number) -
        (row.scenario_cost as number),
    ) > 0.011 ||
    (row.historical_cost === 0
      ? row.percentage_change !== null || row.percentage_increase !== 0
      : !finite(row.percentage_change) ||
        Math.abs(
          (row.percentage_change as number) -
            ((row.difference as number) / (row.historical_cost as number)) *
              100,
        ) > 0.011 ||
        row.percentage_increase !== row.percentage_change) ||
    (expected &&
      (row.proposed_base_bonus !== expected.new_base_bonus ||
        row.history_days !== expected.days_projection ||
        row.settings_revision !== expected.expected_settings_revision))
  )
    throw new Error("El cálculo recibido no informa importes coherentes.");
  return { ...row } as unknown as BonusSimulationResponse;
}
export const settingsTime = (value: unknown) =>
  alertDate(value)?.toLocaleString("es-VE", { timeZone: "America/Caracas" }) ??
  "Fecha no disponible";
export const settingsValue = (value: unknown) =>
  value === null
    ? "Sin configurar"
    : Array.isArray(value)
      ? value.length
        ? value.join(" · ")
        : "Sin zonas informadas"
      : typeof value === "boolean"
        ? value
          ? "Activo"
          : "Inactivo"
        : String(value);
