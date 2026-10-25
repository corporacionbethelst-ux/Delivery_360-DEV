/** A fleet-state precondition, never an authorization credential. */
export class AssignmentRevisionError extends Error {
  readonly status = 409;
  constructor() {
    super('Recarga el perfil para revisar los datos actuales del vehículo');
    this.name = 'AssignmentRevisionError';
  }
}
export function requireAssignmentRevision(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new AssignmentRevisionError();
  return value;
}
export function isAssignmentConflict(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error && error.status === 409;
}
export function hasFleetFields(data: object): boolean {
  return ['vehicle_type', 'vehicle_plate', 'vehicle_model', 'vehicle_ownership_type', 'assigned_vehicle_id']
    .some(key => Object.prototype.hasOwnProperty.call(data, key));
}
