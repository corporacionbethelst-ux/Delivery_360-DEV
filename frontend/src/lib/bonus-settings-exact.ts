import { exactRecordTime } from "@/lib/transaction-exact";
import { cashCents, cashText } from "@/lib/customer-cashbook";
import { record } from "@/lib/operational-catalog";
import {
  SETTING_LABELS,
  SETTING_NUMBERS,
  sameSetting,
  settingsTime,
  settingsValue,
  type SettingsDraft,
  type SettingsKey,
} from "@/lib/platform-settings";
export {
  SETTING_LABELS,
  SETTING_NUMBERS,
  sameSetting,
  settingsTime,
  settingsValue,
};
export type { SettingsDraft, SettingsKey };
export type NumericSetting = (typeof SETTING_NUMBERS)[number];
export type ExactSettings = Record<NumericSetting, string | null> & {
  version: 2;
  currency: "USD";
  units_basis: "prospective_usd_parameters";
  revision: string;
  legacy_revision: string | null;
  active_zones: string[];
  support_email: string | null;
  maintenance_mode: boolean;
  updated_at: string | null;
  updated_by_user_id: string | null;
  field_issues: { field: NumericSetting; reason: "PARAMETRO_NO_VALIDO" }[];
};
export type ExactSettingsUpdate = Partial<
  Record<NumericSetting, string> & {
    active_zones: string[];
    support_email: string;
    maintenance_mode: boolean;
  }
>;
function fail(): never {
  throw new Error(
    "No se pudo confirmar la configuración o el escenario decimal.",
  );
}
export function parameterInput(value: string, percentage = false): string {
  const text = value.trim().replace(",", ".");
  if (
    !(
      percentage
        ? /^(?:\d{1,8})(?:\.\d{1,18})?$/
        : /^(?:\d{1,8})(?:\.\d{1,2})?$/
    ).test(text)
  )
    throw new Error(
      percentage
        ? "Introduce un porcentaje decimal entre 0 y 100."
        : "Usa un importe de hasta dos decimales; un vacío no equivale a cero.",
    );
  const [whole, fractional = ""] = text.split(".");
  const integer = BigInt(whole).toString();
  if (percentage) {
    if (
      BigInt(integer) > BigInt(100) ||
      (integer === "100" && /[1-9]/.test(fractional))
    )
      fail();
    const fraction = fractional.replace(/0+$/, "");
    return integer + (fraction ? "." + fraction : "");
  }
  const normalized = integer + "." + fractional.padEnd(2, "0");
  if (cashCents(normalized) > BigInt(9999999999)) fail();
  return normalized;
}
function money(value: unknown, signed = false): string {
  cashCents(value, signed);
  return value as string;
}
function nullableText(v: unknown): string | null {
  if (v !== null && typeof v !== "string") fail();
  return v as string | null;
}
export function validateExactSettings(value: unknown): ExactSettings {
  const r = record(value);
  if (
    r.version !== 2 ||
    r.currency !== "USD" ||
    r.units_basis !== "prospective_usd_parameters" ||
    typeof r.revision !== "string" ||
    !/^s2-[0-9a-f]{64}$/.test(r.revision) ||
    (r.legacy_revision !== null &&
      (typeof r.legacy_revision !== "string" ||
        !/^s1-[0-9a-f]{64}$/.test(r.legacy_revision))) ||
    !Array.isArray(r.active_zones) ||
    r.active_zones.some((z) => typeof z !== "string" || !z.trim()) ||
    typeof r.maintenance_mode !== "boolean" ||
    !Array.isArray(r.field_issues)
  )
    fail();
  for (const key of SETTING_NUMBERS)
    if (
      r[key] !== null &&
      (typeof r[key] !== "string" ||
        parameterInput(r[key] as string, key === "commission_percentage") !==
          r[key])
    )
      fail();
  const issues = r.field_issues.map((v) => {
    const i = record(v);
    if (
      !SETTING_NUMBERS.includes(i.field as NumericSetting) ||
      i.reason !== "PARAMETRO_NO_VALIDO" ||
      r[i.field as string] !== null
    )
      fail();
    return {
      field: i.field as NumericSetting,
      reason: "PARAMETRO_NO_VALIDO" as const,
    };
  });
  if (new Set(issues.map((i) => i.field)).size !== issues.length) fail();
  return {
    ...r,
    active_zones: [...r.active_zones],
    support_email: nullableText(r.support_email),
    updated_at: nullableText(r.updated_at),
    updated_by_user_id: nullableText(r.updated_by_user_id),
    field_issues: issues,
  } as ExactSettings;
}
export function settingsDraft(r: ExactSettings): SettingsDraft {
  return {
    ...Object.fromEntries(SETTING_NUMBERS.map((k) => [k, r[k] ?? ""])),
    support_email: r.support_email ?? "",
    active_zones: r.active_zones.join("\n"),
    maintenance_mode: r.maintenance_mode,
  } as SettingsDraft;
}
export function validateSettingsUpdate(value: ExactSettingsUpdate) {
  const r = record(value),
    keys = Object.keys(r);
  if (!keys.length || keys.some((k) => !Object.hasOwn(SETTING_LABELS, k)))
    fail();
  for (const key of SETTING_NUMBERS)
    if (
      Object.hasOwn(r, key) &&
      (typeof r[key] !== "string" ||
        parameterInput(r[key] as string, key === "commission_percentage") !==
          r[key])
    )
      fail();
  if (
    Object.hasOwn(r, "support_email") &&
    (typeof r.support_email !== "string" ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.support_email) ||
      r.support_email.length > 255)
  )
    throw new Error("Introduce un email de soporte válido.");
  if (
    Object.hasOwn(r, "maintenance_mode") &&
    typeof r.maintenance_mode !== "boolean"
  )
    fail();
  if (
    Object.hasOwn(r, "active_zones") &&
    (!Array.isArray(r.active_zones) ||
      !r.active_zones.length ||
      r.active_zones.some((z) => typeof z !== "string" || !z.trim()) ||
      new Set(r.active_zones).size !== r.active_zones.length)
  )
    throw new Error("Introduce zonas activas únicas.");
}
export function settingsChanges(
  base: ExactSettings,
  draft: SettingsDraft,
): ExactSettingsUpdate {
  const original = settingsDraft(base),
    patch: ExactSettingsUpdate = {};
  for (const key of SETTING_NUMBERS)
    if (draft[key] !== original[key]) {
      const v = parameterInput(draft[key], key === "commission_percentage");
      if (v !== base[key]) patch[key] = v;
    }
  if (
    draft.support_email !== original.support_email &&
    draft.support_email.trim() !== base.support_email
  )
    patch.support_email = draft.support_email.trim();
  if (draft.active_zones !== original.active_zones) {
    const zones = draft.active_zones
      .split(/\r?\n/)
      .map((z) => z.trim())
      .filter(Boolean);
    if (!sameSetting(zones, base.active_zones)) patch.active_zones = zones;
  }
  if (draft.maintenance_mode !== base.maintenance_mode)
    patch.maintenance_mode = draft.maintenance_mode;
  if (Object.keys(patch).length) validateSettingsUpdate(patch);
  return patch;
}
export type BonusRequest = {
  new_base_bonus: string;
  days_projection: number;
  expected_settings_revision: string;
};
export type BonusActor = { user_id: string; role: string };
export type ExactScenario = {
  version: 2;
  scope: "uniform_bonus_usd_scenario";
  currency: "USD";
  actor: BonusActor;
  settings_revision: string;
  snapshot_basis: "single_statement_visibility";
  history_days: number;
  period_start: string;
  period_end: string;
  generated_at: string;
  comparison_basis: "flat_bonus_same_usd_deliveries";
  current_base_bonus: string;
  applied_bonus: string;
  completed_deliveries: number;
  failed_bonus_deliveries: number;
  recorded_completed_bonus: string;
  recorded_failed_bonus: string;
  historical_cost: string;
  scenario_cost: string;
  difference: string;
  percentage_change: string | null;
  candidate_deliveries: number;
  exclusions: Record<
    | "undated"
    | "unknown_currency"
    | "other_currency"
    | "no_bonus"
    | "invalid_snapshot",
    number
  >;
  bank_verified: false;
  content_sha256: string;
};
export function validateBonusRequest(r: BonusRequest) {
  if (
    typeof r.new_base_bonus !== "string" ||
    parameterInput(r.new_base_bonus) !== r.new_base_bonus ||
    !Number.isSafeInteger(r.days_projection) ||
    r.days_projection < 1 ||
    r.days_projection > 90 ||
    !/^s2-[0-9a-f]{64}$/.test(r.expected_settings_revision)
  )
    fail();
}
function integer(v: unknown): number {
  if (!Number.isSafeInteger(v) || (v as number) < 0) fail();
  return v as number;
}
const instant = exactRecordTime;

export function validateScenario(
  value: unknown,
  expected: BonusRequest,
  actor: BonusActor,
): ExactScenario {
  const r = record(value),
    a = record(r.actor),
    ex = record(r.exclusions);
  if (
    r.version !== 2 ||
    r.scope !== "uniform_bonus_usd_scenario" ||
    r.currency !== "USD" ||
    r.snapshot_basis !== "single_statement_visibility" ||
    r.comparison_basis !== "flat_bonus_same_usd_deliveries" ||
    r.bank_verified !== false ||
    a.user_id !== actor.user_id ||
    a.role !== actor.role ||
    !["SUPERADMIN", "GERENTE"].includes(actor.role) ||
    r.settings_revision !== expected.expected_settings_revision ||
    r.applied_bonus !== expected.new_base_bonus ||
    r.history_days !== expected.days_projection ||
    typeof r.content_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(r.content_sha256)
  )
    fail();
  const completed = integer(r.completed_deliveries),
    failed = integer(r.failed_bonus_deliveries),
    count = integer(r.candidate_deliveries);
  const reasons = [
    "undated",
    "unknown_currency",
    "other_currency",
    "no_bonus",
    "invalid_snapshot",
  ];
  if (
    Object.keys(ex).length !== reasons.length ||
    count !==
      completed + failed + reasons.reduce((n, k) => n + integer(ex[k]), 0) ||
    count > 10000
  )
    fail();
  const success = cashCents(money(r.recorded_completed_bonus)),
    failure = cashCents(money(r.recorded_failed_bonus)),
    historical = cashCents(money(r.historical_cost)),
    scenario = cashCents(money(r.scenario_cost)),
    difference = cashCents(money(r.difference, true), true);
  if (
    (!completed && success !== BigInt(0)) ||
    (!failed && failure !== BigInt(0)) ||
    success + failure !== historical ||
    cashCents(money(r.applied_bonus)) * BigInt(completed) + failure !==
      scenario ||
    scenario - historical !== difference ||
    parameterInput(money(r.current_base_bonus)) !== r.current_base_bonus
  )
    fail();
  if (
    historical === BigInt(0)
      ? r.percentage_change !== null
      : (() => {
          const n = difference * BigInt(10000);
          const absolute = n < BigInt(0) ? -n : n;
          const rounded =
            ((absolute * BigInt(2) + historical) / (historical * BigInt(2))) *
            (n < BigInt(0) ? -BigInt(1) : BigInt(1));
          return cashCents(money(r.percentage_change, true), true) !== rounded;
        })()
  )
    fail();
  if (
    Date.parse(instant(r.period_end)) - Date.parse(instant(r.period_start)) !==
      expected.days_projection * 86400000 ||
    instant(r.generated_at) !== r.period_end
  )
    fail();
  return { ...r, actor: { ...a }, exclusions: { ...ex } } as ExactScenario;
}
export const usdText = (v: string) => cashText(v, "USD");
export const decimalText = (v: string) => usdText(v).replace("USD ", "");
