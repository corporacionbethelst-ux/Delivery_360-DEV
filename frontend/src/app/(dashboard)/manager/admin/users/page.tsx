"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { RefreshCw, Search, Shield, UserPlus, Users } from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationEmpty,
  OperationMetric,
  OperationNotice,
  OperationPill,
  SectionHeading,
  operationStyles,
  type OperationTone,
} from "@/components/operations/OperationsUI";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthStore } from "@/stores/authStore";
import { userService, type UserFilters } from "@/services/user.service";
import type { User, UserRole } from "@/types/user";
import { requireUserRevision, isUserConflict } from "@/lib/user-revision";
import { alertDate } from "@/lib/alert-date";
import {
  USER_PAGE_SIZE,
  USER_ROLE_LABELS,
  canManageAccount,
  userDisplayName,
} from "@/lib/user-administration";

type Query = { role: string; active: string; skip: number };
const sameQuery = (a: Query, b: Query) =>
  a.role === b.role && a.active === b.active && a.skip === b.skip;
const normalize = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
export default function ManagerUsersPage() {
  return (
    <ManagerPageBoundary scope="user-administration">
      <Catalog />
    </ManagerPageBoundary>
  );
}
function Catalog() {
  const { user: actor } = useAuthStore();
  const [query, setQuery] = useState<Query>({
      role: "ALL",
      active: "ALL",
      skip: 0,
    }),
    queryRef = useRef(query);
  const [snapshot, setSnapshot] = useState<{
    rows: User[];
    query: Query;
    more: boolean;
    at: Date;
  } | null>(null);
  const [loading, setLoading] = useState(false),
    [pending, setPending] = useState(false),
    [needsRefresh, setNeedsRefresh] = useState(false);
  const [readError, setReadError] = useState<string | null>(null),
    [error, setError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null);
  const [search, setSearch] = useState(""),
    [selected, setSelected] = useState<User | null>(null),
    [conflicted, setConflicted] = useState(false);
  const alive = useRef(false),
    sequence = useRef(0),
    reading = useRef<number | null>(null),
    writing = useRef(false);
  const load = useCallback(async (target: Query) => {
    if (!alive.current) return;
    const ticket = ++sequence.current;
    reading.current = ticket;
    setLoading(true);
    setReadError(null);
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      sameQuery(target, queryRef.current);
    try {
      const params: UserFilters = {
        limit: USER_PAGE_SIZE + 1,
        skip: target.skip,
        ...(target.role !== "ALL" ? { role: target.role as UserRole } : {}),
        ...(target.active !== "ALL"
          ? { is_active: target.active === "true" }
          : {}),
      };
      const rows = await userService.getAll(params);
      if (
        !Array.isArray(rows) ||
        rows.length > USER_PAGE_SIZE + 1 ||
        rows.some(
          (row) => !row || typeof row.id !== "string" || !row.id.trim(),
        ) ||
        new Set(rows.map((row) => row.id)).size !== rows.length ||
        rows.some(
          (row) =>
            (target.role !== "ALL" && row.role !== target.role) ||
            (target.active !== "ALL" &&
              row.is_active !== (target.active === "true")),
        )
      )
        throw new Error(
          "La respuesta no corresponde a la consulta de usuarios.",
        );
      if (current()) {
        setSnapshot({
          rows: rows.slice(0, USER_PAGE_SIZE),
          query: { ...target },
          more: rows.length > USER_PAGE_SIZE,
          at: new Date(),
        });
        setNeedsRefresh(false);
      }
    } catch {
      if (current())
        setReadError(
          "No se pudo confirmar la consulta de usuarios. Se conservan los últimos datos cargados, si existen.",
        );
    } finally {
      if (reading.current === ticket) reading.current = null;
      if (current()) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const requests = sequence,
      reads = reading;
    alive.current = true;
    return () => {
      alive.current = false;
      requests.current++;
      reads.current = null;
    };
  }, []);
  useEffect(() => {
    void load(query);
  }, [load, query]);
  const chooseQuery = (target: Query) => {
    if (writing.current) return;
    queryRef.current = target;
    sequence.current++;
    setQuery(target);
  };
  const matching = !!snapshot && sameQuery(snapshot.query, query),
    disabled = pending || loading || !matching || !!readError || needsRefresh;
  const visible = useMemo(
    () =>
      snapshot?.rows.filter((row) =>
        normalize(
          [userDisplayName(row), row.email, row.id, row.phone]
            .filter(Boolean)
            .join(" "),
        ).includes(normalize(search)),
      ) ?? [],
    [snapshot, search],
  );
  const openConfirmation = (row: User) => {
    if (
      disabled ||
      writing.current ||
      row.id === actor?.id ||
      row.is_active !== true ||
      !canManageAccount(actor?.role, row.role)
    )
      return;
    try {
      requireUserRevision(row.user_revision);
      setSelected({ ...row });
      setConflicted(false);
      setError(null);
    } catch {
      setError("Recarga y revisa el usuario antes de desactivarlo.");
    }
  };
  const deactivate = async () => {
    const observed = selected;
    if (
      !observed ||
      disabled ||
      conflicted ||
      writing.current ||
      reading.current !== null ||
      observed.id === actor?.id ||
      !canManageAccount(actor?.role, observed.role)
    )
      return;
    writing.current = true;
    setPending(true);
    setError(null);
    setSuccess(null);
    try {
      await userService.deactivate(
        observed.id,
        requireUserRevision(observed.user_revision),
      );
      if (!alive.current) return;
      setSelected(null);
      setNeedsRefresh(true);
      setSuccess(
        `Desactivación confirmada para ${observed.email || userDisplayName(observed)}.`,
      );
      if (queryRef.current.skip !== 0) {
        const target = { ...queryRef.current, skip: 0 };
        queryRef.current = target;
        sequence.current++;
        setQuery(target);
      } else await load(queryRef.current);
    } catch (error) {
      if (alive.current) {
        if (isUserConflict(error)) setConflicted(true);
        setError(
          isUserConflict(error)
            ? "La cuenta cambió. Cierra la confirmación y actualiza antes de revisarla de nuevo."
            : "No se pudo confirmar la desactivación. Revisa la cuenta antes de repetir.",
        );
      }
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const closeAndRefresh = () => {
    setSelected(null);
    setConflicted(false);
    void load(queryRef.current);
  };
  return (
    <main className={operationStyles.page}>
      <OperationsHeader
        icon={Users}
        eyebrow="Administración · Accesos"
        title="Gestión de Usuarios"
        description="Consulta las cuentas y administra sus datos, roles y acceso al sistema."
        actions={
          <>
            <button
              className={operationStyles.button}
              disabled={loading || pending}
              onClick={() => void load(queryRef.current)}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Actualizar
            </button>
            <Link
              className={operationStyles.primaryButton}
              href="/manager/admin/users/new"
            >
              <UserPlus aria-hidden="true" className="h-4 w-4" />
              Nuevo Usuario
            </Link>
          </>
        }
      />
      <section
        className={`${operationStyles.panel} space-y-4 p-5`}
        aria-label="Filtros de usuarios"
      >
        <SectionHeading
          icon={Search}
          title="Explorar las cuentas"
          description="Rol y estado consultan el servidor. La búsqueda filtra la página cargada."
        />
        <div className="grid gap-4 md:grid-cols-3">
          <label className="space-y-2 text-sm font-medium">
            Buscar en esta página
            <input
              className={operationStyles.field}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Nombre, email, teléfono o ID"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            Rol registrado
            <select
              className={operationStyles.field}
              value={query.role}
              disabled={pending}
              onChange={(event) =>
                chooseQuery({ ...query, role: event.target.value, skip: 0 })
              }
            >
              <option value="ALL">Todos los roles</option>
              {Object.entries(USER_ROLE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            Estado de cuenta
            <select
              className={operationStyles.field}
              value={query.active}
              disabled={pending}
              onChange={(event) =>
                chooseQuery({ ...query, active: event.target.value, skip: 0 })
              }
            >
              <option value="ALL">Todos los estados</option>
              <option value="true">Activos</option>
              <option value="false">Inactivos</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-slate-600">
          Hasta 50 registros por página. El servidor no informa un total global.
        </p>
      </section>
      {loading && (
        <OperationNotice role="status">Consultando usuarios…</OperationNotice>
      )}
      {readError && (
        <OperationNotice role="alert" tone="warning">
          <p>{readError}</p>
          <button
            className={operationStyles.button}
            disabled={loading || pending}
            onClick={() => void load(queryRef.current)}
          >
            Reintentar usuarios
          </button>
        </OperationNotice>
      )}
      {error && (
        <OperationNotice role="alert" tone="error">
          {error}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice role="status" tone="success">
          {success}
        </OperationNotice>
      )}
      {snapshot && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <OperationMetric
              icon={Users}
              label="Cuentas en la página confirmada"
              value={snapshot.rows.length}
            />
            <OperationMetric
              icon={Shield}
              label="Activas entre las cargadas"
              value={
                snapshot.rows.filter((row) => row.is_active === true).length
              }
              tone="emerald"
            />
            <OperationMetric
              icon={Search}
              label="Coincidencias locales"
              value={visible.length}
              tone="violet"
            />
          </div>
          <p className="text-sm text-slate-600">
            Consulta confirmada: rol{" "}
            {snapshot.query.role === "ALL"
              ? "Todos"
              : USER_ROLE_LABELS[snapshot.query.role as UserRole]}
            , estado{" "}
            {snapshot.query.active === "ALL"
              ? "Todos"
              : snapshot.query.active === "true"
                ? "Activo"
                : "Inactivo"}
            , página {snapshot.query.skip / USER_PAGE_SIZE + 1}.{" "}
            {alertDate(snapshot.at)?.toLocaleString("es-VE", {
              timeZone: "America/Caracas",
            })}{" "}
            · America/Caracas.
          </p>
          {!matching && (
            <OperationNotice>
              Se conserva la consulta confirmada indicada arriba hasta confirmar
              la nueva selección.
            </OperationNotice>
          )}
          {!visible.length ? (
            <OperationEmpty>
              {snapshot.rows.length
                ? "No hay coincidencias en esta página. Ajusta la búsqueda local."
                : "La página consultada no contiene usuarios."}
            </OperationEmpty>
          ) : (
            <div
              role="region"
              aria-label="Tabla de usuarios"
              tabIndex={0}
              className={`${operationStyles.panel} overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600`}
            >
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className={operationStyles.tableHead}>
                  <tr>
                    <th scope="col" className="p-4">
                      Usuario
                    </th>
                    <th scope="col" className="p-4">
                      Rol
                    </th>
                    <th scope="col" className="p-4">
                      Estado
                    </th>
                    <th scope="col" className="p-4">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visible.map((row) => {
                    const known = Object.hasOwn(USER_ROLE_LABELS, row.role),
                      tone: OperationTone =
                        row.role === "SUPERADMIN"
                          ? "violet"
                          : row.role === "GERENTE"
                            ? "blue"
                            : "slate";
                    let revision = false;
                    try {
                      requireUserRevision(row.user_revision);
                      revision = true;
                    } catch {
                      /* No speculative write without the displayed revision. */
                    }
                    const mayManage = canManageAccount(actor?.role, row.role),
                      mayDeactivate =
                        mayManage &&
                        row.id !== actor?.id &&
                        row.is_active === true &&
                        revision;
                    return (
                      <tr
                        key={row.id}
                        className="align-top hover:bg-blue-50/40"
                      >
                        <td className="max-w-sm space-y-1 p-4">
                          <p className="break-words font-bold">
                            {userDisplayName(row)}
                          </p>
                          <p className="break-all text-slate-600">
                            {row.email || "Email no informado"}
                          </p>
                          <p className="break-all font-mono text-xs text-slate-500">
                            ID: {row.id}
                          </p>
                        </td>
                        <td className="p-4">
                          <OperationPill tone={tone}>
                            {known
                              ? USER_ROLE_LABELS[row.role]
                              : row.role || "Rol no informado"}
                          </OperationPill>
                        </td>
                        <td className="p-4">
                          <OperationPill
                            tone={row.is_active === true ? "emerald" : "slate"}
                          >
                            {row.is_active === true
                              ? "Activo"
                              : row.is_active === false
                                ? "Inactivo"
                                : "Estado no informado"}
                          </OperationPill>
                        </td>
                        <td className="p-4">
                          <div className="flex flex-wrap gap-3">
                            <Link
                              className={operationStyles.link}
                              href={`/manager/admin/users/${encodeURIComponent(row.id)}`}
                              aria-label={`Ver ficha de ${row.id}`}
                            >
                              {mayManage ? "Editar usuario" : "Ver ficha"}
                            </Link>
                            <button
                              className={operationStyles.button}
                              title={
                                row.id === actor?.id
                                  ? "No puedes desactivarte a ti mismo"
                                  : "Desactivar usuario"
                              }
                              aria-label={`Desactivar usuario ${row.id}`}
                              disabled={disabled || !mayDeactivate}
                              onClick={() => openConfirmation(row)}
                            >
                              Desactivar
                            </button>
                          </div>
                          {!mayManage && (
                            <p className="mt-2 text-xs text-slate-600">
                              Modificación reservada a superadministración.
                            </p>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <nav
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"
            aria-label="Paginación de usuarios"
          >
            <button
              className={operationStyles.button}
              disabled={
                loading ||
                pending ||
                !matching ||
                !!readError ||
                snapshot.query.skip === 0
              }
              onClick={() =>
                chooseQuery({
                  ...snapshot.query,
                  skip: Math.max(0, snapshot.query.skip - USER_PAGE_SIZE),
                })
              }
            >
              Página anterior
            </button>
            <span className="text-sm text-slate-600">
              Página {snapshot.query.skip / USER_PAGE_SIZE + 1} de la consulta
              confirmada
            </span>
            <button
              className={operationStyles.button}
              disabled={
                loading || pending || !matching || !!readError || !snapshot.more
              }
              onClick={() =>
                chooseQuery({
                  ...snapshot.query,
                  skip: snapshot.query.skip + USER_PAGE_SIZE,
                })
              }
            >
              Página siguiente
            </button>
          </nav>
        </>
      )}
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open && !writing.current) setSelected(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl border-rose-200">
          <DialogHeader>
            <DialogTitle>Desactivar Usuario</DialogTitle>
            <DialogDescription>
              ¿Desactivar a {selected ? userDisplayName(selected) : ""}? Email:{" "}
              {selected?.email}. ID:{" "}
              <span className="break-all">{selected?.id}</span>. Se revocan las
              sesiones de la cuenta; sus datos históricos se mantienen.
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p role="alert" className="text-sm text-rose-700">
              {error}
            </p>
          )}
          <DialogFooter>
            {conflicted && (
              <button
                className={operationStyles.button}
                onClick={closeAndRefresh}
              >
                Cerrar y actualizar
              </button>
            )}
            <button
              className={operationStyles.button}
              disabled={pending}
              onClick={() => setSelected(null)}
            >
              Cancelar
            </button>
            <button
              className={operationStyles.primaryButton}
              disabled={disabled || conflicted}
              onClick={() => void deactivate()}
            >
              {pending ? "Procesando…" : "Sí, desactivar"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
