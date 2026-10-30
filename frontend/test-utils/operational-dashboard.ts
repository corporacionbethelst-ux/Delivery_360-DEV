import type { DashboardSnapshot } from "@/services/operational-dashboard.service";

export function dashboardSnapshot(): DashboardSnapshot {
  return {
    summary: {
      orders_created: 12,
      completed_deliveries: 3,
      cancelled_orders: 0,
      pending_orders: 123,
      in_progress_orders: 4,
      active_deliveries: 2,
      riders_online: 8,
      available_riders: 6,
      active_shifts: 3,
      open_alerts: 2,
      active_users: 20,
      avg_delivery_minutes: null,
      valid_duration_count: 0,
      sla_percent: null,
      sla_known_count: 0,
      sla_unknown_count: 3,
    },
    series: [
      { date: "2026-10-29", orders_created: 5, completed_deliveries: 1 },
      { date: "2026-10-30", orders_created: 7, completed_deliveries: 2 },
    ],
    period_start: "2026-10-29T00:00:00Z",
    period_end: "2026-10-30T12:00:00Z",
    generated_at: "2026-10-30T12:00:00Z",
    timezone: "UTC",
    pending_orders: [],
    riders_online: [],
    queue_truncated: false,
    positions_truncated: false,
    source: "database_snapshot",
    financials_available: false,
  };
}
