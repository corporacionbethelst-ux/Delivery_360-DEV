import type { Permission, Role } from "@/services/role.service";
import { alertDate } from "@/lib/alert-date";

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("La respuesta de roles y permisos no es válida.");
  return value as Record<string, unknown>;
}
const text = (value: unknown): value is string =>
  typeof value === "string" && !!value.trim();
const optionalText = (value: unknown) =>
  value == null || typeof value === "string";
export function validateRoles(value: unknown): Role[] {
  if (!Array.isArray(value))
    throw new Error("El servidor no devolvió una lista de roles.");
  const rows = value.map((value) => {
    const row = record(value);
    if (
      ![row.id, row.name, row.slug].every(text) ||
      !optionalText(row.description) ||
      !optionalText(row.created_at) ||
      !Number.isSafeInteger(row.users_count) ||
      (row.users_count as number) < 0 ||
      typeof row.is_system !== "boolean" ||
      !Array.isArray(row.permissions) ||
      !row.permissions.every(text) ||
      new Set(row.permissions).size !== row.permissions.length
    )
      throw new Error(
        "Un rol no informa sus datos, conteo y permisos de forma válida.",
      );
    return { ...row, permissions: [...row.permissions] } as unknown as Role;
  });
  if (
    new Set(rows.map((row) => row.id)).size !== rows.length ||
    new Set(rows.map((row) => row.slug)).size !== rows.length
  )
    throw new Error("La lista contiene roles duplicados.");
  return rows;
}
export function validatePermissions(value: unknown): Permission[] {
  if (!Array.isArray(value))
    throw new Error("El servidor no devolvió el catálogo de permisos.");
  const rows = value.map((value) => {
    const row = record(value);
    if (
      ![row.id, row.name, row.module].every(text) ||
      !optionalText(row.description)
    )
      throw new Error("Un permiso no informa su identidad, nombre y módulo.");
    return { ...row } as unknown as Permission;
  });
  if (new Set(rows.map((row) => row.id)).size !== rows.length)
    throw new Error("El catálogo contiene permisos duplicados.");
  return rows;
}
const modules = new Map(
  Object.entries({
    admin: "Administración",
    alerts: "Alertas",
    audit: "Auditoría",
    customer: "Cliente",
    deliveries: "Entregas",
    financial: "Finanzas",
    orders: "Órdenes",
    riders: "Repartidores",
    rider: "App Rider",
    settings: "Configuración",
    shifts: "Turnos",
    users: "Usuarios",
    vehicles: "Vehículos",
    zones: "Zonas",
  }),
);
export const permissionModuleName = (module: string) =>
  modules.get(module) ?? module;
export const normalizeRoleSearch = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es")
    .trim();
export const catalogTime = (at: unknown) =>
  alertDate(at)?.toLocaleString("es-VE", { timeZone: "America/Caracas" }) ??
  "Fecha no disponible";
export function sumRoleAccounts(roles: readonly Role[]): number | null {
  const sum = roles.reduce((sum, role) => sum + role.users_count, 0);
  return Number.isSafeInteger(sum) ? sum : null;
}
export type ComparisonMode = "ALL" | "COMMON" | "DIFFERENT";
export interface PermissionComparisonRow {
  id: string;
  permission: Permission | null;
  declarations: boolean[];
}
export function roleComparisonRows(
  roles: readonly Role[],
  permissions: readonly Permission[],
): PermissionComparisonRow[] {
  const byId = new Map(
    permissions.map((permission) => [permission.id, permission]),
  );
  const ids = new Set([
    ...permissions.map((permission) => permission.id),
    ...roles.flatMap((role) => role.permissions),
  ]);
  const declarations = roles.map((role) => new Set(role.permissions));
  return Array.from(ids, (id) => ({
    id,
    permission: byId.get(id) ?? null,
    declarations: declarations.map((set) => set.has(id)),
  }));
}
export function filterRoleComparison(
  rows: readonly PermissionComparisonRow[],
  search: string,
  module: string,
  mode: ComparisonMode,
): PermissionComparisonRow[] {
  const query = normalizeRoleSearch(search);
  return rows.filter((row) => {
    const matchesSearch = normalizeRoleSearch(
      [
        row.id,
        row.permission?.name,
        row.permission?.description,
        row.permission && permissionModuleName(row.permission.module),
      ]
        .filter(Boolean)
        .join(" "),
    ).includes(query);
    const matchesModule =
      module === "all" ||
      (module === "missing"
        ? !row.permission
        : !!row.permission && module === `module:${row.permission.module}`);
    const count = row.declarations.filter(Boolean).length;
    return (
      matchesSearch &&
      matchesModule &&
      (mode === "ALL" ||
        (mode === "COMMON"
          ? count > 0 && count === row.declarations.length
          : count > 0 && count < row.declarations.length))
    );
  });
}
export function comparisonCSV(
  rows: readonly PermissionComparisonRow[],
  roles: readonly Role[],
  rolesAt: Date,
  permissionsAt: Date,
): Record<string, unknown>[] {
  return rows.map((row) => {
    const record: Record<string, unknown> = {
      Permiso: row.id,
      Nombre: row.permission?.name ?? "Sin ficha en catálogo",
      Módulo: row.permission
        ? permissionModuleName(row.permission.module)
        : "Sin ficha en catálogo",
      "Consulta roles (Caracas)": catalogTime(rolesAt),
      "Consulta permisos (Caracas)": catalogTime(permissionsAt),
    };
    roles.forEach((role, index) => {
      record[`Rol ${index + 1}: ${role.name} [${role.id}]`] = row.declarations[
        index
      ]
        ? "Declarado"
        : "No declarado";
    });
    return record;
  });
}
