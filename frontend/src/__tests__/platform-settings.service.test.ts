import { api } from "@/lib/api";
import {
  settingsService,
  type PlatformSettings,
} from "@/services/settings.service";
import {
  settingsChanges,
  settingsDraft,
  settingsNumber,
  validatePlatformSettings,
  validateBonusResult,
} from "@/lib/platform-settings";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() },
}));
const mocked = jest.mocked(api);
const saved: PlatformSettings = {
  revision: "s1-" + "a".repeat(64),
  delivery_fee_base: 0,
  commission_percentage: 12.1234,
  min_order_amount: null,
  rider_delivery_bonus: 2.50001,
  rider_failed_attempt_bonus: 0,
  active_zones: ["Centro, Norte", "Sur"],
  support_email: null,
  maintenance_mode: false,
  updated_at: null,
  updated_by_user_id: null,
};
beforeEach(() => jest.resetAllMocks());
afterEach(() => clearStoredTokens());
it("preserves nulls, zero, false and fractional precision instead of inserting defaults", async () => {
  mocked.get.mockResolvedValue(saved);
  expect(await settingsService.getSettings()).toEqual(saved);
  expect(mocked.get).toHaveBeenCalledWith("/settings");
  expect(settingsDraft(saved)).toMatchObject({
    delivery_fee_base: "0",
    min_order_amount: "",
    support_email: "",
    rider_delivery_bonus: "2.50001",
    active_zones: "Centro, Norte\nSur",
    maintenance_mode: false,
  });
});
it.each([
  null,
  [],
  {},
  { ...saved, delivery_fee_base: undefined },
  { ...saved, rider_delivery_bonus: "2.5" },
  { ...saved, min_order_amount: -1 },
  { ...saved, commission_percentage: 101 },
  { ...saved, maintenance_mode: "false" },
  { ...saved, support_email: undefined },
  { ...saved, active_zones: [1] },
  { ...saved, active_zones: null },
  { ...saved, updated_at: {} },
  { ...saved, revision: undefined },
  { ...saved, revision: "old" },
])("rejects malformed read %j without fabricated values", async (value) => {
  mocked.get.mockResolvedValue(value);
  await expect(settingsService.getSettings()).rejects.toThrow();
});
it("copies frozen arrays and accepts the real unconfigured response", () => {
  const raw = Object.freeze({
    ...saved,
    active_zones: Object.freeze([...saved.active_zones]),
  });
  const read = validatePlatformSettings(raw);
  read.active_zones.push("Otro");
  expect(raw.active_zones).toHaveLength(2);
  expect(
    validatePlatformSettings({ ...saved, active_zones: [] }).active_zones,
  ).toEqual([]);
});
it.each(["", " ", "Infinity", "NaN", "1e3", "-1", "1.2.3"])(
  "rejects invalid amount text %j",
  (value) => {
    expect(() => settingsNumber(value, "importe")).toThrow();
  },
);
it.each([
  ["0", 0],
  [" 2,50001 ", 2.50001],
  [".25", 0.25],
] as const)("parses explicit decimal %s with no rounding", (text, expected) => {
  expect(settingsNumber(text, "importe")).toBe(expected);
});
it("only sends changed values, preserving commas in zones and nulls in untouched fields", () => {
  expect(
    settingsChanges(saved, {
      ...settingsDraft(saved),
      support_email: " support@example.com ",
    }),
  ).toEqual({ support_email: "support@example.com" });
  expect(
    settingsChanges(saved, {
      ...settingsDraft(saved),
      active_zones: "Centro, Norte\nOeste",
    }),
  ).toEqual({ active_zones: ["Centro, Norte", "Oeste"] });
  expect(settingsChanges(saved, settingsDraft(saved))).toEqual({});
});
it("recognizes numerically equal input without a false change", () => {
  expect(
    settingsChanges(saved, {
      ...settingsDraft(saved),
      delivery_fee_base: "0.00",
    }),
  ).toEqual({});
});
it.each([
  { delivery_fee_base: NaN },
  { rider_delivery_bonus: Infinity },
  { commission_percentage: 101 },
  { delivery_fee_base: -1 },
  { maintenance_mode: "false" },
  { support_email: "invalid" },
  { active_zones: [] },
  { active_zones: ["Norte", "Norte"] },
  { updated_at: "today" },
  {},
])("rejects invalid update %j before HTTP", async (patch) => {
  await expect(
    settingsService.updateSettings(patch as never, saved.revision),
  ).rejects.toThrow();
  expect(mocked.patch).not.toHaveBeenCalled();
});
it("PATCH sends the exact minimal payload and retains a valid false state", async () => {
  mocked.patch.mockResolvedValue(saved);
  const patch = Object.freeze({
    maintenance_mode: false,
    active_zones: Object.freeze(["Centro, Norte"]),
  });
  await settingsService.updateSettings(patch as never, saved.revision);
  expect(mocked.patch).toHaveBeenCalledWith("/settings", patch, {
    headers: { "If-Match": `"${saved.revision}"` },
  });
});
const calculation = {
  current_monthly_cost: 100,
  projected_monthly_cost: 110,
  difference: 10,
  percentage_increase: 10,
  message: "Cálculo",
};
it.each([
  { new_base_bonus: -1, days_projection: 30 },
  { new_base_bonus: NaN, days_projection: 30 },
  { new_base_bonus: 0, days_projection: 0 },
  { new_base_bonus: 1, days_projection: 91 },
  { new_base_bonus: 1, days_projection: 1.5 },
  {},
])(
  "rejects invalid simulation %j without a calculation request",
  async (body) => {
    await expect(settingsService.simulateBonusImpact(body)).rejects.toThrow();
    expect(mocked.post).not.toHaveBeenCalled();
  },
);
it("allows zero proposed bonus and an explicit history window without currency conversion", async () => {
  mocked.post.mockResolvedValue(calculation);
  expect(
    await settingsService.simulateBonusImpact({
      new_base_bonus: 0,
      days_projection: 7,
    }),
  ).toEqual(calculation);
  expect(mocked.post).toHaveBeenCalledWith("/settings/simulate-bonus", {
    new_base_bonus: 0,
    days_projection: 7,
  });
});
it.each([
  null,
  {},
  { ...calculation, projected_monthly_cost: NaN },
  { ...calculation, difference: "10" },
  { ...calculation, current_monthly_cost: -1 },
  { ...calculation, projected_monthly_cost: 1000 },
])("rejects invalid financial result %j", (value) => {
  expect(() => validateBonusResult(value)).toThrow();
});
it.each(["read", "save", "simulation"])(
  "retires a %s response from different credentials",
  async (source) => {
    let resolve!: (value: unknown) => void;
    const pending = new Promise((yes) => {
      resolve = yes;
    });
    mocked.get.mockReturnValue(pending);
    mocked.patch.mockReturnValue(pending);
    mocked.post.mockReturnValue(pending);
    const request =
      source === "read"
        ? settingsService.getSettings()
        : source === "save"
          ? settingsService.updateSettings(
              { maintenance_mode: true },
              saved.revision,
            )
          : settingsService.simulateBonusImpact({
              new_base_bonus: 0,
              days_projection: 30,
            });
    storeTokens({
      access_token: "settings85-change",
      refresh_token: "settings85-refresh",
    });
    resolve(source === "simulation" ? calculation : saved);
    await expect(request).rejects.toThrow("sesión cambió");
  },
);
it.each([
  undefined,
  null,
  "",
  "*",
  'W/"old"',
  "s1-bad",
  "s1-" + "g".repeat(64),
])("blocks writes with invalid revision %j before HTTP", async (revision) => {
  await expect(
    settingsService.updateSettings(
      { maintenance_mode: true },
      revision as never,
    ),
  ).rejects.toThrow(/revisión válida/);
  expect(mocked.patch).not.toHaveBeenCalled();
});
