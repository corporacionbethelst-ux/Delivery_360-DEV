/** Bind commands to the vehicle record actually selected, without refreshing it. */
export class VehicleRevisionError extends Error {
  readonly status = 409;
  constructor() { super('Recarga los vehículos y revisa la ficha antes de seleccionarlo de nuevo'); this.name = 'VehicleRevisionError'; }
}
export function requireVehicleRevision(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new VehicleRevisionError();
  return value;
}
