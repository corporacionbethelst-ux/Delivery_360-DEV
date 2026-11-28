import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { requireProfileRevision } from '@/lib/profile-revision';
import { requireAssignmentRevision } from '@/lib/assignment-revision';
import { requireVehicleRevision } from '@/lib/vehicle-revision';

export const VEHICLE_OPTIONS = {
  MOTO: 'Motocicleta',
  BICICLETA: 'Bicicleta',
  PATINETA: 'Patineta',
  AUTO: 'Automóvil',
  FURGONETA: 'Furgoneta',
};
export const PROFILE_FIELDS = [
  'first_name',
  'last_name',
  'phone',
  'vehicle_type',
  'vehicle_plate',
] as const;
export type ProfileField = (typeof PROFILE_FIELDS)[number];
export type ProfileDraft = Record<ProfileField, string>;
export type SelfProfile = ProfileDraft & {
  id: string;
  user_id: string;
  email: string;
  profile_revision: string;
  assignment_revision: string;
  vehicle_ownership_type: 'PROPIO' | 'EMPRESA';
  assigned_vehicle_id: string | null;
  assigned_vehicle: { id: string; revision: string; type: string; plate: string } | null;
};
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Perfil no válido');
  return value as Record<string, unknown>;
};
const text = (value: unknown): string => {
  if (typeof value !== 'string') throw new Error('Campo de perfil no válido');
  return value;
};
const id = (value: unknown): string => {
  const s = text(value);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s))
    throw new Error('Identidad de perfil no válida');
  return s;
};
export function readSelfProfile(value: unknown, owner: string, expectedId?: string): SelfProfile {
  const row = record(value),
    profileId = id(row.id),
    userId = id(row.user_id);
  if (userId !== owner || (expectedId !== undefined && profileId !== expectedId))
    throw new Error('El perfil pertenece a otra identidad');
  if (row.vehicle_ownership_type !== 'PROPIO' && row.vehicle_ownership_type !== 'EMPRESA')
    throw new Error('Propiedad de vehículo no válida');
  const type = row.vehicle_type == null ? '' : text(row.vehicle_type);
  // Preserve unfamiliar historical types for display; a new selection must be supported.
  const assignedId = row.assigned_vehicle_id == null ? null : id(row.assigned_vehicle_id);
  const vehicle = row.assigned_vehicle == null ? null : record(row.assigned_vehicle);
  const assigned = vehicle
    ? {
        id: id(vehicle.id),
        revision: requireVehicleRevision(vehicle.revision),
        type: text(vehicle.type),
        plate: text(vehicle.plate),
      }
    : null;
  if (
    row.vehicle_ownership_type === 'EMPRESA'
      ? !assigned ||
        assigned.id !== assignedId ||
        assigned.type !== type ||
        assigned.plate !== row.vehicle_plate
      : !!assigned || assignedId !== null
  )
    throw new Error('Asignación de vehículo contradictoria');
  return {
    id: profileId,
    user_id: userId,
    email: text(row.email),
    first_name: text(row.first_name),
    last_name: text(row.last_name),
    phone: text(row.phone),
    vehicle_type: type,
    vehicle_plate: text(row.vehicle_plate),
    profile_revision: requireProfileRevision(row.profile_revision),
    assignment_revision: requireAssignmentRevision(row.assignment_revision),
    vehicle_ownership_type: row.vehicle_ownership_type,
    assigned_vehicle_id: assignedId,
    assigned_vehicle: assigned,
  };
}
export const profileDraft = (row: SelfProfile): ProfileDraft =>
  Object.fromEntries(PROFILE_FIELDS.map((key) => [key, row[key]])) as ProfileDraft;
export const changedProfileFields = (base: SelfProfile, draft: ProfileDraft): ProfileField[] =>
  PROFILE_FIELDS.filter((key) => base[key] !== draft[key]);
export const changesVehicle = (keys: readonly ProfileField[]): boolean =>
  keys.some((key) => key === 'vehicle_type' || key === 'vehicle_plate');
export const riderSelf = {
  async get(owner: string, expectedId?: string): Promise<SelfProfile> {
    const task = capturePrivateTask();
    const result = await api.get<unknown>('/riders/me');
    task.assertCurrent();
    return readSelfProfile(result, owner, expectedId);
  },
  async save(base: SelfProfile, draft: ProfileDraft, owner: string): Promise<SelfProfile> {
    const checked = readSelfProfile(base, owner, base.id),
      keys = changedProfileFields(checked, draft);
    if (
      !keys.length ||
      PROFILE_FIELDS.some((key) => typeof draft[key] !== 'string') ||
      !draft.first_name.trim() ||
      !draft.last_name.trim()
    )
      throw new Error('Revisa los datos personales');
    if (
      draft.first_name.length > 100 ||
      draft.last_name.length > 100 ||
      draft.phone.length > 20 ||
      draft.vehicle_plate.length > 20
    )
      throw new Error('Revisa la longitud de los datos');
    if (
      changesVehicle(keys) &&
      (base.vehicle_ownership_type !== 'PROPIO' ||
        !Object.prototype.hasOwnProperty.call(VEHICLE_OPTIONS, draft.vehicle_type))
    )
      throw new Error('El vehículo necesita revisión');
    const payload: Record<string, string> = Object.fromEntries(
      keys.map((key) => [key, draft[key]]),
    );
    if (keys.some((key) => ['first_name', 'last_name', 'phone'].includes(key)))
      payload.expected_profile_revision = checked.profile_revision;
    if (changesVehicle(keys)) payload.expected_assignment_revision = checked.assignment_revision;
    const task = capturePrivateTask();
    const result = await api.put<unknown>('/riders/me', payload);
    task.assertCurrent();
    const receipt = readSelfProfile(result, owner, checked.id);
    if (keys.some((key) => receipt[key] !== draft[key]))
      throw new Error('El acuse no confirma los cambios');
    return receipt;
  },
};
