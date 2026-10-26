import { isEmailConflict } from '@/lib/email-conflict';
/** Bind user metadata writes to the record actually displayed. */
export class UserRevisionError extends Error {
  readonly status = 409;
  constructor() { super('Recarga y revisa el usuario antes de guardar o desactivarlo'); this.name = 'UserRevisionError'; }
}
export function requireUserRevision(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new UserRevisionError();
  return value;
}
export function isUserConflict(error: any): boolean {
  return !isEmailConflict(error) && (error?.status === 409 || error?.response?.status === 409);
}
