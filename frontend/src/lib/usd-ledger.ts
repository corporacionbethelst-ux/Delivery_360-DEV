import type {
  FinancialTransaction,
  RiderEarnings,
  RiderEarningsBreakdown,
} from "@/services/financial.service";
import { payoutCents } from "@/lib/payout-contract";
import { normalizeTransaction } from "@/lib/transaction-contract";

const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("No se pudo confirmar el libro USD.");
  return value as Record<string, unknown>;
};
export function normalizeUsdEarnings(value: unknown): RiderEarnings {
  const r = object(value);
  if (
    r.currency !== "USD" ||
    typeof r.rider_id !== "string" ||
    !r.rider_id ||
    typeof r.rider_name !== "string" ||
    !Number.isSafeInteger(r.completed_deliveries) ||
    Number(r.completed_deliveries) < 0
  )
    throw new Error("El servidor no confirmó ganancias denominadas en USD.");
  return {
    rider_id: r.rider_id,
    rider_name: r.rider_name,
    currency: "USD",
    total_earned: payoutCents(r.total_earned) / 100,
    pending_payout: payoutCents(r.pending_payout) / 100,
    completed_deliveries: Number(r.completed_deliveries),
  };
}
export function normalizeRiderLedger(value: unknown): RiderEarningsBreakdown {
  const r = object(value);
  if (typeof r.rider_id !== "string" || !r.rider_id || !Array.isArray(r.items))
    throw new Error("Historial financiero incompleto.");
  const ids = new Set<string>();
  const items: FinancialTransaction[] = r.items.map((value) => {
    const entry = normalizeTransaction(value);
    if (entry.rider_id !== r.rider_id || ids.has(entry.id))
      throw new Error(
        "El historial pertenece a otra cuenta o contiene duplicados.",
      );
    ids.add(entry.id);
    return {
      ...entry,
      rider_id: r.rider_id as string,
      transaction_type: entry.type,
      description: entry.description ?? "Sin descripción",
    };
  });
  return { rider_id: r.rider_id, items };
}
