export function isEmailConflict(error: any): boolean {
  return error?.code === 'USER_EMAIL_CONFLICT' || error?.response?.data?.detail?.code === 'USER_EMAIL_CONFLICT';
}
export function emailConflictMessage(error: any): string | undefined {
  if (!isEmailConflict(error)) return undefined;
  return error?.response?.data?.detail?.message || error?.message || 'El correo ya está registrado. Use otro correo';
}
