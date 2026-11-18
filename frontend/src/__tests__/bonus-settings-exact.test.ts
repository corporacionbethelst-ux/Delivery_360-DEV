import {
  parameterInput,
  settingsChanges,
  settingsDraft,
  validateExactSettings,
  validateScenario,
  usdText,
} from "@/lib/bonus-settings-exact";
import { settingsService } from "@/services/bonus-settings-exact.service";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import { exactSettings, bonusScenario } from "../../test-fixtures/bonus-exact";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() },
}));
const actor = { user_id: "admin", role: "SUPERADMIN" },
  request = {
    new_base_bonus: "2.50",
    days_projection: 30,
    expected_settings_revision: "s2-" + "a".repeat(64),
  };
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "token-a", refresh_token: "refresh-a" });
});
afterEach(() => clearStoredTokens());
it.each(["", "1.001", "-0.01", "1e2", "NaN", "Infinity", "100000000.00"])(
  "rejects imprecise or missing money %s",
  (value) => expect(() => parameterInput(value)).toThrow(),
);
it.each([
  ["0", "0.00"],
  ["0,10", "0.10"],
  ["99999999.99", "99999999.99"],
  ["000.10", "0.10"],
])("normalizes text without binary money %s", (input, expected) =>
  expect(parameterInput(input)).toBe(expected),
);
it("keeps percent precision and exact large cents", () => {
  expect(parameterInput("12.123456789012345678", true)).toBe(
    "12.123456789012345678",
  );
  expect(() => parameterInput("100.000000000000000001", true)).toThrow();
  expect(usdText("99999999.99")).toBe("USD 99.999.999,99");
});
it("rejects numeric responses and legacy revisions without silently upgrading them", () => {
  expect(() =>
    validateExactSettings({ ...exactSettings(), rider_delivery_bonus: 2.5 }),
  ).toThrow();
  expect(() =>
    validateExactSettings({
      ...exactSettings(),
      revision: "s1-" + "a".repeat(64),
    }),
  ).toThrow();
});
it("keeps null and invalid parameters distinct and permits explicit repair", () => {
  const value = validateExactSettings(
    exactSettings({
      rider_delivery_bonus: null,
      field_issues: [
        { field: "rider_delivery_bonus", reason: "PARAMETRO_NO_VALIDO" },
      ],
    }),
  );
  const draft = settingsDraft(value);
  expect(draft.rider_delivery_bonus).toBe("");
  expect(draft.delivery_fee_base).toBe("0.00");
  expect(
    settingsChanges(value, { ...draft, rider_delivery_bonus: "0,10" }),
  ).toEqual({ rider_delivery_bonus: "0.10" });
  expect(
    validateExactSettings(exactSettings({ legacy_revision: null }))
      .legacy_revision,
  ).toBeNull();
});
it("does not patch equivalent formatting or replace missing money with zero", () => {
  const base = exactSettings(),
    draft = settingsDraft(base);
  expect(settingsChanges(base, { ...draft, delivery_fee_base: "0" })).toEqual(
    {},
  );
  expect(() =>
    settingsChanges(base, { ...draft, rider_delivery_bonus: "" }),
  ).toThrow();
});
it("reads and updates only the exact routes with text and strong revision", async () => {
  jest.mocked(api.get).mockResolvedValue(exactSettings());
  await settingsService.getSettings();
  jest
    .mocked(api.patch)
    .mockResolvedValue(exactSettings({ rider_delivery_bonus: "0.10" }));
  const revision = exactSettings().revision;
  await settingsService.updateSettings(
    { rider_delivery_bonus: "0.10" },
    revision,
  );
  expect(api.get).toHaveBeenCalledWith("/settings/exact/v2");
  expect(api.patch).toHaveBeenCalledWith(
    "/settings/exact/v2",
    { rider_delivery_bonus: "0.10" },
    { headers: { "If-Match": `"${revision}"` } },
  );
});
it("posts a captured proposal and validates its actor and exact totals", async () => {
  jest.mocked(api.post).mockResolvedValue(bonusScenario());
  const result = await settingsService.simulateBonusImpact(request, actor);
  expect(result.historical_cost).toBe("110.00");
  expect(api.post).toHaveBeenCalledWith(
    "/settings/simulate-bonus/exact/v2",
    request,
  );
});
it.each([
  { currency: "VES" },
  { actor: { ...actor, user_id: "other" } },
  { settings_revision: "s2-" + "b".repeat(64) },
  { historical_cost: 110 },
  { difference: "-0.00" },
  { scenario_cost: "35.01" },
  { percentage_change: "1.00" },
  { candidate_deliveries: 13 },
  { period_start: "2026-02-30T00:00:00.000000Z" },
  { content_sha256: "bad" },
  { completed_deliveries: 0 },
  { bank_verified: true },
])("rejects contradictory scenario %j", (patch) =>
  expect(() =>
    validateScenario({ ...bonusScenario(), ...patch }, request, actor),
  ).toThrow(),
);
it("keeps unknown-currency exclusions and zero USD scenarios honest", () => {
  const response = bonusScenario({
    completed: 0,
    failed: 0,
    recordedCompleted: "0.00",
    recordedFailed: "0.00",
    exclusions: {
      undated: 2,
      unknown_currency: 4,
      other_currency: 1,
      no_bonus: 0,
      invalid_snapshot: 0,
    },
  });
  const result = validateScenario(response, request, actor);
  expect(result.historical_cost).toBe("0.00");
  expect(result.percentage_change).toBeNull();
  expect(result.exclusions.unknown_currency).toBe(4);
});
it("does not expose a completed response after credentials change", async () => {
  let resolve!: (value: any) => void;
  jest.mocked(api.get).mockReturnValue(new Promise((done) => (resolve = done)));
  const pending = settingsService.getSettings();
  storeTokens({ access_token: "token-b", refresh_token: "refresh-b" });
  resolve(exactSettings());
  await expect(pending).rejects.toThrow(/sesión cambió/i);
});
