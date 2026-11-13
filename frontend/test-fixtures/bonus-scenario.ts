import type { BonusSimulationResponse } from "@/services/settings.service";

export function bonusScenario({
  proposed = 2.50001,
  days = 30,
  revision = "s1-" + "a".repeat(64),
  completed = 10,
  failed = 2,
  recordedCompleted = 100,
  recordedFailed = 10,
}: {
  proposed?: number;
  days?: number;
  revision?: string;
  completed?: number;
  failed?: number;
  recordedCompleted?: number;
  recordedFailed?: number;
} = {}): BonusSimulationResponse {
  const applied = Math.round((proposed + Number.EPSILON) * 100) / 100;
  const historical = recordedCompleted + recordedFailed;
  const scenario = applied * completed + recordedFailed;
  const difference = scenario - historical;
  const percentage = historical
    ? Math.round((difference / historical) * 10000) / 100
    : null;
  const end = "2026-11-13T02:00:00Z";
  return {
    current_monthly_cost: historical,
    projected_monthly_cost: scenario,
    difference,
    percentage_increase: percentage ?? 0,
    message: "Escenario sintético",
    comparison_basis: "flat_bonus_same_deliveries",
    history_days: days,
    period_start: new Date(Date.parse(end) - days * 86400000).toISOString(),
    period_end: end,
    completed_deliveries: completed,
    failed_bonus_deliveries: failed,
    undated_bonus_deliveries: 0,
    recorded_completed_bonus: recordedCompleted,
    recorded_failed_bonus: recordedFailed,
    historical_cost: historical,
    scenario_cost: scenario,
    applied_bonus: applied,
    current_base_bonus: 2.50001,
    proposed_base_bonus: proposed,
    settings_revision: revision,
    percentage_change: percentage,
    currency: null,
  };
}
