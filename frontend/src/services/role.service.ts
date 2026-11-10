import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";
import { validatePermissions, validateRoles } from "@/lib/role-catalog";

export interface Permission {
  id: string;
  name: string;
  module: string;
  description?: string | null;
}
export interface Role {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  permissions: string[];
  users_count: number;
  is_system: boolean;
  created_at?: string | null;
}
export interface RoleCreateInput {
  name: string;
  slug: string;
  description?: string;
  permissions: string[];
}
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const session = captureAuthSession(),
    result = await request();
  if (!isCurrentAuthSession(session)) throw new SessionChangedError();
  return result;
}
function readOnly(): never {
  throw new Error("Los roles y permisos de sistema solo se pueden consultar.");
}
export const roleService = {
  getAll: async (): Promise<Role[]> =>
    validateRoles(await inSession(() => api.get<unknown>("/roles"))),
  getPermissions: async (): Promise<Permission[]> =>
    validatePermissions(
      await inSession(() => api.get<unknown>("/roles/permissions")),
    ),
  // Preserve the public signatures while respecting the API's read-only system roles.
  create: async (_data: RoleCreateInput): Promise<Role> => readOnly(),
  update: async (_id: string, _data: Partial<RoleCreateInput>): Promise<Role> =>
    readOnly(),
  delete: async (_id: string): Promise<void> => readOnly(),
};
