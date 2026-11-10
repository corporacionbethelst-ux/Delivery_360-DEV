"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  roleService,
  type Permission,
  type Role,
} from "@/services/role.service";

export type CatalogSnapshot<T> = { rows: T[]; at: Date };
export function useRoleCatalog() {
  const [roles, setRoles] = useState<CatalogSnapshot<Role> | null>(null),
    [permissions, setPermissions] =
      useState<CatalogSnapshot<Permission> | null>(null);
  const [rolesLoading, setRolesLoading] = useState(true),
    [permissionsLoading, setPermissionsLoading] = useState(true);
  const [rolesError, setRolesError] = useState<string | null>(null),
    [permissionsError, setPermissionsError] = useState<string | null>(null);
  const alive = useRef(false),
    rolesSequence = useRef(0),
    permissionsSequence = useRef(0);
  const loadRoles = useCallback(async () => {
    const ticket = ++rolesSequence.current;
    setRolesLoading(true);
    setRolesError(null);
    try {
      const rows = await roleService.getAll();
      if (alive.current && ticket === rolesSequence.current)
        setRoles({ rows, at: new Date() });
    } catch {
      if (alive.current && ticket === rolesSequence.current)
        setRolesError(
          "No se pudieron actualizar los roles. Se conserva su última consulta confirmada, si existe.",
        );
    } finally {
      if (alive.current && ticket === rolesSequence.current)
        setRolesLoading(false);
    }
  }, []);
  const loadPermissions = useCallback(async () => {
    const ticket = ++permissionsSequence.current;
    setPermissionsLoading(true);
    setPermissionsError(null);
    try {
      const rows = await roleService.getPermissions();
      if (alive.current && ticket === permissionsSequence.current)
        setPermissions({ rows, at: new Date() });
    } catch {
      if (alive.current && ticket === permissionsSequence.current)
        setPermissionsError(
          "No se pudo actualizar el catálogo de permisos. Se conserva su última consulta confirmada, si existe.",
        );
    } finally {
      if (alive.current && ticket === permissionsSequence.current)
        setPermissionsLoading(false);
    }
  }, []);
  useEffect(() => {
    const roleReads = rolesSequence,
      permissionReads = permissionsSequence;
    alive.current = true;
    void loadRoles();
    void loadPermissions();
    return () => {
      alive.current = false;
      roleReads.current++;
      permissionReads.current++;
    };
  }, [loadRoles, loadPermissions]);
  return {
    roles,
    permissions,
    rolesLoading,
    permissionsLoading,
    rolesError,
    permissionsError,
    refresh: () => {
      void loadRoles();
      void loadPermissions();
    },
    retryRoles: () => void loadRoles(),
    retryPermissions: () => void loadPermissions(),
  };
}
