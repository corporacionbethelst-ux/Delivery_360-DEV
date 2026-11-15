import type { WithdrawalIntent } from "@/lib/withdrawal-intent";
import { normalizePayout } from "@/lib/payout-contract";

/** Amounts stay decimal text/BigInt; the existing v1 intent stores bounded integer cents. */
export function withdrawalAmount(value: string): string {
  if (!/^\d{1,8}(?:[.,]\d{1,2})?$/.test(value.trim()))
    throw new Error(
      "Usa un monto con hasta dos decimales y máximo 99.999.999,99 USD.",
    );
  const [whole, fraction = ""] = value.trim().replace(",", ".").split(".");
  return `${BigInt(whole)}.${fraction.padEnd(2, "0")}`;
}
export function intentAmount(intent: WithdrawalIntent): string {
  if (
    !Number.isSafeInteger(intent.amountCents) ||
    intent.amountCents < 1000 ||
    intent.amountCents > 9999999999
  )
    throw new Error("El importe de la solicitud requiere revisión.");
  const cents = BigInt(intent.amountCents);
  return `${cents / BigInt(100)}.${(cents % BigInt(100)).toString().padStart(2, "0")}`;
}
export function confirmExactWithdrawal(
  value: unknown,
  intent: WithdrawalIntent,
  riderId?: string,
) {
  const payout = normalizePayout(value);
  if (
    payout.currency !== "USD" ||
    payout.requested_by_user_id !== intent.userId ||
    payout.idempotency_key !== intent.key ||
    payout.method !== "TRANSFERENCIA" ||
    (payout.bank_account_last4 ?? "") !== intent.bankLast4 ||
    (riderId !== undefined && payout.rider_id !== riderId) ||
    withdrawalAmount(String(payout.amount)) !== intentAmount(intent)
  )
    throw new Error("El servidor no confirmó la misma solicitud de retiro.");
  return payout;
}
