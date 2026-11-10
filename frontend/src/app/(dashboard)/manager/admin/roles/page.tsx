"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Download,
  GitCompareArrows,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  Search,
  Shield,
  Users,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationEmpty,
  OperationMetric,
  OperationNotice,
  OperationPill,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { useRoleCatalog } from "@/hooks/useRoleCatalog";
import {
  catalogTime,
  comparisonCSV,
  filterRoleComparison,
  normalizeRoleSearch,
  permissionModuleName,
  roleComparisonRows,
  sumRoleAccounts,
  type ComparisonMode,
} from "@/lib/role-catalog";
import { downloadCSV } from "@/lib/csv-export";

export default function AdminRolesPage() {
  return (
    <ManagerPageBoundary scope="role-permission-review">
      <RoleCatalog />
    </ManagerPageBoundary>
  );
}
function RoleCatalog() {
  const state = useRoleCatalog(),
    [roleSearch, setRoleSearch] = useState(""),
    [roleFilter, setRoleFilter] = useState("all"),
    [permissionSearch, setPermissionSearch] = useState(""),
    [moduleFilter, setModuleFilter] = useState("all"),
    [mode, setMode] = useState<ComparisonMode>("ALL"),
    [selectedIds, setSelectedIds] = useState<string[]>([]),
    [downloadNotice, setDownloadNotice] = useState<string | null>(null),
    [downloadError, setDownloadError] = useState<string | null>(null);
  const roles = state.roles?.rows,
    permissions = state.permissions?.rows;
  const permissionMap = useMemo(
    () =>
      new Map(
        (permissions ?? []).map((permission) => [permission.id, permission]),
      ),
    [permissions],
  );
  const modules = useMemo(
    () =>
      Array.from(
        new Set((permissions ?? []).map((permission) => permission.module)),
      ),
    [permissions],
  );
  const roleMap = useMemo(
    () => new Map((roles ?? []).map((role) => [role.id, role])),
    [roles],
  );
  const selected = selectedIds.flatMap((id) => {
      const role = roleMap.get(id);
      return role ? [role] : [];
    }),
    missingSelected = selectedIds.filter((id) => !roleMap.has(id));
  const selectedRows = roleComparisonRows(selected, permissions ?? []),
    comparison = filterRoleComparison(
      selectedRows,
      permissionSearch,
      moduleFilter,
      mode,
    );
  const catalogRows = filterRoleComparison(
    roleComparisonRows([], permissions ?? []),
    permissionSearch,
    moduleFilter,
    "ALL",
  );
  const unresolvedIds = Array.from(
    new Set((roles ?? []).flatMap((role) => role.permissions)),
  ).filter((id) => !permissionMap.has(id));
  const visibleRoles = (roles ?? []).filter(
    (role) =>
      (roleFilter === "all" || roleFilter === `role:${role.id}`) &&
      normalizeRoleSearch(
        [
          role.name,
          role.slug,
          role.id,
          role.description,
          ...role.permissions.flatMap((id) => [
            id,
            permissionMap.get(id)?.name ?? "",
          ]),
        ]
          .filter(Boolean)
          .join(" "),
      ).includes(normalizeRoleSearch(roleSearch)),
  );
  const busy = state.rolesLoading || state.permissionsLoading,
    canExport =
      !!state.roles &&
      !!state.permissions &&
      !busy &&
      !state.rolesError &&
      !state.permissionsError &&
      selected.length >= 2 &&
      !missingSelected.length &&
      !!comparison.length;
  const clearNotice = () => {
    setDownloadNotice(null);
    setDownloadError(null);
  };
  const select = (id: string) => {
    setSelectedIds((previous) =>
      previous.includes(id)
        ? previous.filter((value) => value !== id)
        : previous.length < 3
          ? [...previous, id]
          : previous,
    );
    clearNotice();
  };
  const clearFilters = () => {
    setRoleSearch("");
    setRoleFilter("all");
    setPermissionSearch("");
    setModuleFilter("all");
    setMode("ALL");
    clearNotice();
  };
  const exportComparison = () => {
    if (!canExport || !state.roles || !state.permissions) return;
    clearNotice();
    try {
      if (
        downloadCSV(
          comparisonCSV(
            comparison,
            selected,
            state.roles.at,
            state.permissions.at,
          ),
          "roles_comparacion",
        )
      )
        setDownloadNotice(
          `Se inició la descarga de ${comparison.length} ${comparison.length === 1 ? "permiso" : "permisos"} y ${selected.length} roles de la comparación visible.`,
        );
    } catch {
      setDownloadError(
        "No se pudo preparar el CSV de la comparación. Puedes reintentar la descarga.",
      );
    }
  };
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={Shield}
        eyebrow="Administración · Accesos"
        title="Roles y Permisos"
        description="Consulta los roles y las capacidades declaradas por el sistema. La autorización se comprueba en cada operación."
        actions={
          <>
            <button
              className={operationStyles.button}
              disabled={busy}
              onClick={() => {
                clearNotice();
                state.refresh();
              }}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar catálogo
            </button>
            <Link
              className={operationStyles.primaryButton}
              href="/manager/admin/users"
            >
              <Users aria-hidden="true" className="h-4 w-4" />
              Gestionar cuentas
            </Link>
          </>
        }
      />
      <OperationNotice>
        <p className="font-semibold">Roles de sistema · solo consulta</p>
        <p>
          Esta pantalla permite revisar y comparar las capacidades informadas.
          La comparación no cambia permisos ni asignaciones de cuentas.
        </p>
      </OperationNotice>
      {state.rolesLoading && (
        <OperationNotice role="status">Consultando roles…</OperationNotice>
      )}
      {state.rolesError && (
        <OperationNotice tone="warning" role="alert">
          <p>{state.rolesError}</p>
          <button
            className={operationStyles.button}
            disabled={state.rolesLoading}
            onClick={state.retryRoles}
          >
            Reintentar roles
          </button>
        </OperationNotice>
      )}
      {state.permissionsLoading && (
        <OperationNotice role="status">Consultando permisos…</OperationNotice>
      )}
      {state.permissionsError && (
        <OperationNotice tone="warning" role="alert">
          <p>{state.permissionsError}</p>
          <button
            className={operationStyles.button}
            disabled={state.permissionsLoading}
            onClick={state.retryPermissions}
          >
            Reintentar permisos
          </button>
        </OperationNotice>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        {state.roles && (
          <>
            <OperationMetric
              icon={Shield}
              label="Roles en la consulta confirmada"
              value={roles!.length}
            />
            <OperationMetric
              icon={Users}
              label="Cuentas en los roles cargados"
              value={sumRoleAccounts(roles!) ?? "Total no disponible"}
              tone="emerald"
            />
          </>
        )}
        {state.permissions && (
          <OperationMetric
            icon={KeyRound}
            label="Permisos con ficha confirmada"
            value={permissions!.length}
            tone="violet"
          />
        )}
      </div>
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Filtros de roles y permisos"
      >
        <SectionHeading
          icon={Search}
          title="Explorar los accesos"
          description="Los filtros actúan sobre los catálogos cargados. No consultan ni modifican cuentas."
        />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-2 text-sm font-medium">
            Buscar roles
            <input
              className={operationStyles.field}
              value={roleSearch}
              onChange={(e) => setRoleSearch(e.target.value)}
              placeholder="Nombre, ID o permiso declarado"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Rol a consultar
            <select
              className={operationStyles.field}
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="all">Todos los roles cargados</option>
              {(roles ?? []).map((role) => (
                <option key={role.id} value={`role:${role.id}`}>
                  {role.name} [{role.slug}]
                </option>
              ))}
              {roleFilter !== "all" &&
                !(roles ?? []).some(
                  (role) => roleFilter === `role:${role.id}`,
                ) && (
                  <option value={roleFilter}>
                    Rol ya no disponible: {roleFilter.slice(5)}
                  </option>
                )}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Buscar permisos
            <input
              className={operationStyles.field}
              value={permissionSearch}
              onChange={(e) => {
                setPermissionSearch(e.target.value);
                clearNotice();
              }}
              placeholder="Nombre, ID, descripción o módulo"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Módulo de permisos
            <select
              className={operationStyles.field}
              value={moduleFilter}
              onChange={(e) => {
                setModuleFilter(e.target.value);
                clearNotice();
              }}
            >
              <option value="all">Todos los módulos cargados</option>
              {modules.map((module) => (
                <option key={module} value={`module:${module}`}>
                  {permissionModuleName(module)}
                </option>
              ))}
              {unresolvedIds.length > 0 && (
                <option value="missing">Sin ficha disponible</option>
              )}
              {moduleFilter.startsWith("module:") &&
                !modules.includes(moduleFilter.slice(7)) && (
                  <option value={moduleFilter}>
                    Módulo ya no disponible: {moduleFilter.slice(7)}
                  </option>
                )}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-600">
            Buscar permisos y módulo filtran el catálogo de permisos y la
            comparación; las tarjetas de roles conservan su propio filtro.
          </p>
          <button className={operationStyles.button} onClick={clearFilters}>
            Limpiar filtros
          </button>
        </div>
      </section>
      {state.roles && (
        <section
          className="space-y-4"
          aria-label="Roles de la consulta confirmada"
        >
          <SectionHeading
            icon={Shield}
            title="Roles registrados"
            description="Las cuentas asignadas incluyen activas e inactivas. Selecciona de dos a tres roles para compararlos."
          />
          <p className="text-xs text-slate-600">
            Roles confirmados: {catalogTime(state.roles.at)} · America/Caracas.
            Mostrando {visibleRoles.length} de {roles!.length} roles cargados.
          </p>
          {visibleRoles.length === 0 ? (
            <OperationEmpty>
              {roles!.length
                ? "No hay roles que coincidan con los filtros locales."
                : "La consulta confirmada no contiene roles."}
            </OperationEmpty>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleRoles.map((role) => (
                <article
                  key={role.id}
                  aria-label={`Rol ${role.id}`}
                  className={`${operationStyles.panel} space-y-4 border-l-4 border-l-violet-500 p-5`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="break-words text-lg font-bold">
                          {role.name}
                        </h3>
                        <OperationPill
                          tone={role.is_system ? "violet" : "slate"}
                        >
                          <LockKeyhole aria-hidden="true" className="h-3 w-3" />
                          {role.is_system ? "Sistema" : "Tipo no sistema"}
                        </OperationPill>
                      </div>
                      <p className="break-all font-mono text-xs text-slate-600">
                        ID: {role.id} · {role.slug}
                      </p>
                      <p className="break-words text-sm text-slate-600">
                        {role.description || "Descripción no informada"}
                      </p>
                    </div>
                    <div className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-right">
                      <p className="text-xl font-bold tabular-nums">
                        {role.users_count}
                      </p>
                      <p className="text-xs text-slate-600">
                        Cuentas asignadas
                      </p>
                    </div>
                  </div>
                  <label className="flex items-center gap-3 rounded-xl border border-violet-100 bg-violet-50/40 p-3 text-sm font-semibold">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-violet-700"
                      checked={selectedIds.includes(role.id)}
                      disabled={
                        !selectedIds.includes(role.id) &&
                        selectedIds.length >= 3
                      }
                      onChange={() => select(role.id)}
                    />
                    Comparar {role.name} [{role.slug}]
                  </label>
                  <details className="rounded-xl border border-slate-200 p-3">
                    <summary className="cursor-pointer rounded-lg text-sm font-semibold text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">
                      Ver {role.permissions.length}{" "}
                      {role.permissions.length === 1
                        ? "permiso declarado"
                        : "permisos declarados"}{" "}
                      de {role.name}
                    </summary>
                    {role.permissions.length === 0 ? (
                      <p className="mt-3 text-sm text-slate-600">
                        El rol informa una lista de permisos vacía.
                      </p>
                    ) : (
                      <ul className="mt-3 grid gap-2 text-sm">
                        {role.permissions.map((id) => (
                          <li
                            key={id}
                            className="min-w-0 rounded-lg bg-slate-50 p-2"
                          >
                            <p className="break-words font-medium">
                              {permissionMap.get(id)?.name ??
                                "Sin ficha disponible"}
                            </p>
                            <p className="break-all font-mono text-xs text-slate-600">
                              {id}
                            </p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </details>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      {state.roles && unresolvedIds.length > 0 && (
        <OperationNotice tone="warning">
          Hay {unresolvedIds.length}{" "}
          {unresolvedIds.length === 1
            ? "referencia declarada"
            : "referencias declaradas"}{" "}
          por roles sin ficha disponible en el catálogo cargado. Se conservan
          sus IDs.
        </OperationNotice>
      )}
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Comparación de roles"
      >
        <SectionHeading
          icon={GitCompareArrows}
          title="Comparar capacidades declaradas"
          tone="violet"
          description="Declarado indica que el permiso aparece en la lista del rol. No declarado indica que no aparece; esta tabla no modifica ni concede accesos."
        />
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-slate-600">
            {selectedIds.length} de 3 roles seleccionados
          </p>
          {selectedIds.map((id) => (
            <button
              key={id}
              className={operationStyles.button}
              onClick={() => select(id)}
              aria-label={`Quitar rol ${id}`}
            >
              Quitar {roleMap.get(id)?.name ?? id}
            </button>
          ))}
          {selectedIds.length > 0 && (
            <button
              className={operationStyles.button}
              onClick={() => {
                setSelectedIds([]);
                clearNotice();
              }}
            >
              Vaciar selección
            </button>
          )}
        </div>
        {missingSelected.length > 0 && (
          <OperationNotice tone="warning">
            Ya no figuran en los roles cargados: {missingSelected.join(", ")}.
            Retíralos de la selección para comparar los roles disponibles.
          </OperationNotice>
        )}
        {selected.length < 2 || missingSelected.length ? (
          <OperationNotice>
            Selecciona entre dos y tres roles disponibles para ver la
            comparación.
          </OperationNotice>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <label className="space-y-2 text-sm font-medium">
                Vista de comparación
                <select
                  className={operationStyles.field}
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as ComparisonMode);
                    clearNotice();
                  }}
                >
                  <option value="ALL">
                    Todos los permisos de la comparación
                  </option>
                  <option value="COMMON">Solo compartidos</option>
                  <option value="DIFFERENT">Solo diferencias</option>
                </select>
              </label>
              <button
                className={operationStyles.primaryButton}
                disabled={!canExport}
                onClick={exportComparison}
              >
                <Download aria-hidden="true" className="h-4 w-4" />
                Descargar comparación (CSV)
              </button>
            </div>
            <p className="text-xs text-slate-600">
              {comparison.length} de {selectedRows.length} permisos en la
              comparación visible. El CSV incluye estas filas y los{" "}
              {selected.length} roles seleccionados, con las fechas de ambas
              consultas cargadas.
            </p>
            <p className="text-xs text-slate-600 lg:hidden">
              Desliza la tabla horizontalmente para ver los roles seleccionados.
              Con teclado, selecciona la tabla y usa las flechas.
            </p>
            {comparison.length === 0 ? (
              <OperationEmpty>
                No hay permisos que coincidan con los filtros de la comparación.
              </OperationEmpty>
            ) : (
              <div
                role="region"
                aria-label="Matriz de comparación"
                aria-description="Desplázate horizontalmente para ver los roles seleccionados. Con teclado, usa las flechas."
                tabIndex={0}
                className="overflow-x-auto rounded-xl border border-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-600"
              >
                <table className="w-full min-w-[650px] text-left text-sm">
                  <thead className={operationStyles.tableHead}>
                    <tr>
                      <th scope="col" className="p-4">
                        Permiso y módulo
                      </th>
                      {selected.map((role) => (
                        <th scope="col" key={role.id} className="min-w-40 p-4">
                          <p className="break-words">{role.name}</p>
                          <p className="mt-1 break-all font-mono text-xs normal-case">
                            {role.id}
                          </p>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {comparison.map((row) => (
                      <tr
                        key={row.id}
                        className="align-top hover:bg-violet-50/30"
                      >
                        <th
                          scope="row"
                          className="max-w-sm space-y-1 p-4 font-normal"
                        >
                          <p className="break-words font-semibold">
                            {row.permission?.name ?? "Sin ficha disponible"}
                          </p>
                          <p className="break-all font-mono text-xs text-slate-600">
                            {row.id}
                          </p>
                          <p className="text-xs text-slate-600">
                            {row.permission
                              ? permissionModuleName(row.permission.module)
                              : "ID declarado sin ficha en el catálogo cargado"}
                          </p>
                        </th>
                        {row.declarations.map((declared, index) => (
                          <td key={selected[index].id} className="p-4">
                            <OperationPill
                              tone={declared ? "emerald" : "slate"}
                            >
                              {declared ? "Declarado" : "No declarado"}
                            </OperationPill>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        {downloadNotice && (
          <OperationNotice tone="success" role="status">
            {downloadNotice}
          </OperationNotice>
        )}
        {downloadError && (
          <OperationNotice tone="error" role="alert">
            {downloadError}
          </OperationNotice>
        )}
      </section>
      {state.permissions && (
        <section
          className="space-y-4"
          aria-label="Catálogo de permisos confirmado"
        >
          <SectionHeading
            icon={KeyRound}
            title="Catálogo de permisos"
            tone="violet"
            description="Fichas recibidas del sistema, agrupadas por módulo. Las referencias sin ficha se muestran por ID en la comparación."
          />
          <p className="text-xs text-slate-600">
            Permisos confirmados: {catalogTime(state.permissions.at)} ·
            America/Caracas. Mostrando {catalogRows.length} de{" "}
            {permissions!.length} fichas cargadas.
          </p>
          {catalogRows.length === 0 ? (
            <OperationEmpty>
              {permissions!.length
                ? "No hay fichas que coincidan con los filtros locales de permisos."
                : "El catálogo confirmado no contiene permisos."}
            </OperationEmpty>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {modules.map((module) => {
                const rows = catalogRows.filter(
                  (row) => row.permission?.module === module,
                );
                return rows.length ? (
                  <section
                    key={module}
                    className={`${operationStyles.panel} min-w-0 space-y-4 p-5`}
                    aria-label={`Módulo ${module}`}
                  >
                    <h3 className="break-words font-bold text-violet-800">
                      {permissionModuleName(module)}
                    </h3>
                    <ul className="space-y-3">
                      {rows.map((row) => (
                        <li
                          key={row.id}
                          className="space-y-1 rounded-xl border border-slate-100 bg-slate-50 p-3"
                        >
                          <p className="break-words text-sm font-semibold">
                            {row.permission!.name}
                          </p>
                          <p className="break-words text-xs text-slate-600">
                            {row.permission!.description ||
                              "Descripción no informada"}
                          </p>
                          <p className="break-all font-mono text-xs text-slate-500">
                            {row.id}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null;
              })}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
