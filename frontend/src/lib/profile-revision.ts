/** Protect the personal/tier snapshot loaded by the editor. */
export class ProfileRevisionError extends Error {
  readonly status = 409;
  constructor() { super('Recarga y revisa el perfil antes de guardar sus datos personales o nivel'); this.name = 'ProfileRevisionError'; }
}
export function requireProfileRevision(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new ProfileRevisionError();
  return value;
}
export function hasProfileFields(value: object): boolean {
  const data = value as Record<string, unknown>;
  return ['first_name', 'last_name', 'phone', 'operating_zone', 'cpf', 'cnh', 'tier'].some(key => data[key] !== undefined && data[key] !== null);
}
