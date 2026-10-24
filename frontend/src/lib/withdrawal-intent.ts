/** Tab-scoped recovery metadata; never a source of authorization or balance. */
export interface WithdrawalIntent {
  version: 1;
  userId: string;
  key: string;
  amountCents: number;
  bankLast4: string;
}
const storageKey = (userId: string) => `delivery360-withdrawal-v1:${userId}`;
const valid = (value: unknown, userId: string): value is WithdrawalIntent => {
  if (typeof value !== 'object' || value === null) return false;
  return 'version' in value && value.version === 1 &&
    'userId' in value && value.userId === userId &&
    'key' in value && typeof value.key === 'string' && !!value.key.trim() && value.key.length <= 100 &&
    'amountCents' in value && typeof value.amountCents === 'number' && Number.isSafeInteger(value.amountCents) && value.amountCents >= 1000 && value.amountCents <= 9999999999 &&
    'bankLast4' in value && typeof value.bankLast4 === 'string' && /^(?:[0-9]{4})?$/.test(value.bankLast4);
};
export function loadWithdrawalIntent(userId: string): WithdrawalIntent | null {
  const raw = sessionStorage.getItem(storageKey(userId));
  if (raw === null) return null;
  const value: unknown = JSON.parse(raw);
  if (!valid(value, userId)) throw new Error('No se puede recuperar la solicitud. Revisa tu historial de retiros.');
  return value;
}
export function saveWithdrawalIntent(value: WithdrawalIntent): void {
  if (!valid(value, value.userId)) throw new Error('Datos de solicitud inválidos');
  sessionStorage.setItem(storageKey(value.userId), JSON.stringify(value));
}
export function clearWithdrawalIntent(userId: string, expectedKey: string): void {
  if (loadWithdrawalIntent(userId)?.key === expectedKey) sessionStorage.removeItem(storageKey(userId));
}
