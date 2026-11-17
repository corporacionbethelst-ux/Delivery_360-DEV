/** Synthetic USD snapshots for v2 contracts; never a legacy response conversion. */
import type {
  ExactSettings,
  ExactScenario,
  BonusActor,
} from "../src/lib/bonus-settings-exact";
export function exactSettings(
  patch: Partial<ExactSettings> = {},
): ExactSettings {
  return {
    version: 2,
    currency: "USD",
    units_basis: "prospective_usd_parameters",
    legacy_revision: "s1-" + "a".repeat(64),
    revision: "s2-" + "a".repeat(64),
    delivery_fee_base: "0.00",
    commission_percentage: "12.1234",
    min_order_amount: null,
    rider_delivery_bonus: "2.50",
    rider_failed_attempt_bonus: "0.00",
    active_zones: ["Centro, Norte", "Sur"],
    support_email: null,
    maintenance_mode: false,
    updated_at: "2026-11-10T12:00:00",
    updated_by_user_id: "admin",
    field_issues: [],
    ...patch,
  };
}
function cents(v: bigint): string {
  const abs = v < BigInt(0) ? -v : v;
  return (
    (v < BigInt(0) ? "-" : "") +
    (abs / BigInt(100)).toString() +
    "." +
    (abs % BigInt(100)).toString().padStart(2, "0")
  );
}
export function bonusScenario({
  proposed = "2.50",
  days = 30,
  revision = "s2-" + "a".repeat(64),
  completed = 10,
  failed = 2,
  recordedCompleted = "100.00",
  recordedFailed = "10.00",
  actor = { user_id: "admin", role: "SUPERADMIN" },
  exclusions = {
    undated: 0,
    unknown_currency: 0,
    other_currency: 0,
    no_bonus: 0,
    invalid_snapshot: 0,
  },
}: {
  proposed?: string;
  days?: number;
  revision?: string;
  completed?: number;
  failed?: number;
  recordedCompleted?: string;
  recordedFailed?: string;
  actor?: BonusActor;
  exclusions?: ExactScenario["exclusions"];
} = {}): ExactScenario {
  const success = BigInt(recordedCompleted.replace(".", "")),
    failure = BigInt(recordedFailed.replace(".", "")),
    historical = success + failure;
  const scenario =
      BigInt(proposed.replace(".", "")) * BigInt(completed) + failure,
    difference = scenario - historical;
  const percent = difference * BigInt(10000),
    absolute = percent < BigInt(0) ? -percent : percent;
  const end = "2026-11-13T02:00:00.000000Z";
  return {
    version: 2,
    scope: "uniform_bonus_usd_scenario",
    currency: "USD",
    actor,
    settings_revision: revision,
    snapshot_basis: "single_statement_visibility",
    history_days: days,
    period_start: new Date(Date.parse(end) - days * 86400000)
      .toISOString()
      .replace("Z", "000Z"),
    period_end: end,
    generated_at: end,
    comparison_basis: "flat_bonus_same_usd_deliveries",
    current_base_bonus: "2.50",
    applied_bonus: proposed,
    completed_deliveries: completed,
    failed_bonus_deliveries: failed,
    recorded_completed_bonus: recordedCompleted,
    recorded_failed_bonus: recordedFailed,
    historical_cost: cents(historical),
    scenario_cost: cents(scenario),
    difference: cents(difference),
    percentage_change: historical
      ? cents(
          ((absolute * BigInt(2) + historical) / (historical * BigInt(2))) *
            (percent < BigInt(0) ? -BigInt(1) : BigInt(1)),
        )
      : null,
    candidate_deliveries:
      completed + failed + Object.values(exclusions).reduce((n, c) => n + c, 0),
    exclusions,
    bank_verified: false,
    content_sha256: "e".repeat(64),
  };
}
