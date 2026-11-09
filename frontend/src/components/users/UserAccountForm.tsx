"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  KeyRound,
  RefreshCw,
  Shield,
  UserRound,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationNotice,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { Switch } from "@/components/ui/switch";
import { useAuthStore } from "@/stores/authStore";
import { userService } from "@/services/user.service";
import type { User } from "@/types/user";
import { requireUserRevision, isUserConflict } from "@/lib/user-revision";
import { emailConflictMessage } from "@/lib/email-conflict";
import {
  USER_ROLE_LABELS,
  canManageAccount,
  cleanUserDraft,
  userDisplayName,
  validateUserPassword,
  type UserDraft,
} from "@/lib/user-administration";

export default function UserAccountForm({ id }: { id?: string }) {
  return (
    <ManagerPageBoundary
      scope={`user-account:${id === undefined ? "new" : id}`}
    >
      <AccountForm id={id} />
    </ManagerPageBoundary>
  );
}
function AccountForm({ id }: { id?: string }) {
  const creating = id === undefined,
    router = useRouter(),
    { user: actor } = useAuthStore();
  const [snapshot, setSnapshot] = useState<User | null>(null),
    [draft, setDraft] = useState<UserDraft>({
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      role: "OPERADOR",
      is_active: true,
    });
  const [loading, setLoading] = useState(!creating),
    [saving, setSaving] = useState(false),
    [completed, setCompleted] = useState(false),
    [conflicted, setConflicted] = useState(false);
  const [readError, setReadError] = useState<string | null>(null),
    [error, setError] = useState<string | null>(null);
  const [changePassword, setChangePassword] = useState(false),
    [password, setPassword] = useState(""),
    [confirmation, setConfirmation] = useState("");
  const alive = useRef(false),
    sequence = useRef(0),
    writing = useRef(false),
    snapshotRef = useRef<User | null>(null),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);
  const load = useCallback(async () => {
    if (creating || writing.current) return;
    const ticket = ++sequence.current;
    clearTimer();
    snapshotRef.current = null;
    setSnapshot(null);
    setLoading(true);
    setReadError(null);
    setError(null);
    setConflicted(false);
    setCompleted(false);
    setPassword("");
    setConfirmation("");
    setChangePassword(false);
    try {
      if (!id) throw new Error("ID de usuario no válido.");
      const row = await userService.getById(id);
      if (!alive.current || ticket !== sequence.current) return;
      if (!row || row.id !== id)
        throw new Error("La respuesta no corresponde al usuario solicitado.");
      if (
        typeof row.is_active !== "boolean" ||
        !Object.hasOwn(USER_ROLE_LABELS, row.role)
      )
        throw new Error(
          "La ficha no informa un rol y estado válidos. Recarga el usuario.",
        );
      const loaded = { ...row };
      snapshotRef.current = loaded;
      setSnapshot(loaded);
      setDraft({
        first_name: row.first_name || "",
        last_name: row.last_name || "",
        email: row.email || "",
        phone: row.phone || "",
        role: row.role,
        is_active: row.is_active,
      });
    } catch (error) {
      if (alive.current && ticket === sequence.current)
        setReadError(
          error instanceof Error && error.name !== "AxiosError"
            ? error.message
            : "No se pudo cargar el usuario. Reintenta la consulta.",
        );
    } finally {
      if (alive.current && ticket === sequence.current) setLoading(false);
    }
  }, [creating, id, clearTimer]);
  useEffect(() => {
    const requests = sequence,
      record = snapshotRef;
    alive.current = true;
    if (!creating) void load();
    return () => {
      alive.current = false;
      requests.current++;
      record.current = null;
      clearTimer();
    };
  }, [load, creating, clearTimer]);
  const self = !!snapshot && snapshot.id === actor?.id;
  const allowed =
    creating || (!!snapshot && canManageAccount(actor?.role, snapshot.role));
  let hasRevision = creating;
  try {
    if (snapshot) requireUserRevision(snapshot.user_revision);
    if (snapshot) hasRevision = true;
  } catch {
    /* A legacy read can be shown, but cannot authorize an edit. */
  }
  const editable =
    (creating || !!snapshot) &&
    allowed &&
    hasRevision &&
    !loading &&
    !saving &&
    !completed &&
    !conflicted;
  const change = <K extends keyof UserDraft>(key: K, value: UserDraft[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    if (!conflicted) setError(null);
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editable || writing.current || !alive.current) return;
    let observed = snapshotRef.current;
    let values: UserDraft;
    try {
      values = cleanUserDraft(draft);
      if (!canManageAccount(actor?.role, values.role))
        throw new Error(
          "Solo un superadministrador puede asignar el rol Superadministrador.",
        );
      if (
        self &&
        observed &&
        (values.role !== observed.role || !values.is_active)
      )
        throw new Error(
          "No puedes cambiar tu propio rol ni desactivar tu cuenta.",
        );
      if (creating || changePassword)
        validateUserPassword(password, confirmation);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Revisa los datos del formulario.",
      );
      return;
    }
    writing.current = true;
    setSaving(true);
    setError(null);
    let metadataSaved = false;
    try {
      if (creating) {
        const created = await userService.create({
          ...values,
          phone: values.phone || undefined,
          password,
        });
        if (!alive.current) return;
        if (!created || typeof created.id !== "string" || !created.id) {
          setConflicted(true);
          throw new Error(
            "No se pudo confirmar el usuario creado. Revisa el listado antes de repetir el alta.",
          );
        }
      } else {
        if (!observed || observed.id !== id) return;
        const updated = await userService.update(observed.id, {
          ...values,
          expected_user_revision: requireUserRevision(observed.user_revision),
        });
        if (!alive.current || snapshotRef.current !== observed) return;
        if (!updated || updated.id !== observed.id) {
          setConflicted(true);
          throw new Error(
            "El guardado no devolvió la ficha solicitada. Recarga y revisa la cuenta antes de repetir.",
          );
        }
        metadataSaved = true;
        const revised = {
          ...updated,
          user_revision: requireUserRevision(updated.user_revision),
        };
        snapshotRef.current = revised;
        observed = revised;
        if (changePassword) {
          const changed = await userService.updatePassword(
            revised.id,
            password,
          );
          if (!alive.current || snapshotRef.current !== revised) return;
          if (!changed || changed.id !== revised.id)
            throw new Error(
              "No se confirmó la cuenta del cambio de contraseña.",
            );
        }
      }
      if (!alive.current) return;
      setCompleted(true);
      setPassword("");
      setConfirmation("");
      timer.current = setTimeout(() => {
        if (alive.current) router.push("/manager/admin/users");
      }, 1500);
    } catch (error) {
      if (!alive.current) return;
      if (metadataSaved || isUserConflict(error)) setConflicted(true);
      setError(
        metadataSaved
          ? "Los datos se guardaron, pero no se confirmó el cambio de contraseña o la nueva revisión. Recarga y revisa la cuenta antes de volver a intentarlo."
          : emailConflictMessage(error) ||
              (error instanceof Error && error.name !== "AxiosError"
                ? error.message
                : "No se pudo confirmar el guardado. Revisa el estado de la cuenta antes de repetir."),
      );
    } finally {
      writing.current = false;
      if (alive.current) setSaving(false);
    }
  };
  return (
    <main className={`${operationStyles.page} max-w-4xl`}>
      <OperationsHeader
        icon={UserRound}
        eyebrow="Administración · Usuarios"
        title={creating ? "Crear Nuevo Usuario" : "Editar Usuario"}
        description={
          creating ? (
            "Registra una cuenta con sus datos y acceso inicial."
          ) : (
            <span className="break-all">
              Ficha cargada:{" "}
              {snapshot ? userDisplayName(snapshot) : "Pendiente de confirmar"}.
              ID: {id || "No informado"}
            </span>
          )
        }
        actions={
          <>
            <Link
              className={operationStyles.button}
              href="/manager/admin/users"
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Volver al listado
            </Link>
            {!creating && (
              <button
                className={operationStyles.button}
                disabled={loading || saving}
                onClick={() => void load()}
              >
                <RefreshCw aria-hidden="true" className="h-4 w-4" />
                Recargar usuario
              </button>
            )}
          </>
        }
      />
      {loading && (
        <OperationNotice role="status">
          Consultando la ficha del usuario…
        </OperationNotice>
      )}
      {readError && (
        <OperationNotice role="alert" tone="warning">
          {readError}
        </OperationNotice>
      )}
      {error && (
        <OperationNotice role="alert" tone="error">
          {error}
        </OperationNotice>
      )}
      {completed && (
        <OperationNotice role="status" tone="success">
          {creating
            ? "Usuario creado correctamente."
            : "Usuario actualizado correctamente."}{" "}
          <Link className={operationStyles.link} href="/manager/admin/users">
            Volver a la lista
          </Link>
        </OperationNotice>
      )}
      {snapshot && !allowed && (
        <OperationNotice>
          Solo un superadministrador puede modificar esta cuenta.
        </OperationNotice>
      )}
      {snapshot && !hasRevision && (
        <OperationNotice tone="warning">
          Recarga y revisa el usuario antes de guardar: la ficha no informa una
          revisión válida.
        </OperationNotice>
      )}
      {(creating || snapshot) && (
        <form onSubmit={save} className="space-y-5" noValidate>
          <fieldset disabled={!editable} className="min-w-0 space-y-5">
            <section
              className={`${operationStyles.panel} space-y-5 border-blue-100 bg-blue-50/30 p-5`}
            >
              <SectionHeading
                icon={UserRound}
                title={creating ? "Datos Personales" : "Información Personal"}
              />
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2 text-sm font-medium">
                  Nombre *
                  <input
                    id="fname"
                    className={operationStyles.field}
                    value={draft.first_name}
                    onChange={(event) =>
                      change("first_name", event.target.value)
                    }
                    autoComplete="given-name"
                    maxLength={100}
                  />
                </label>
                <label className="space-y-2 text-sm font-medium">
                  Apellido *
                  <input
                    id="lname"
                    className={operationStyles.field}
                    value={draft.last_name}
                    onChange={(event) =>
                      change("last_name", event.target.value)
                    }
                    autoComplete="family-name"
                    maxLength={100}
                  />
                </label>
                <label className="space-y-2 text-sm font-medium">
                  Email *
                  <input
                    id="email"
                    type="email"
                    className={operationStyles.field}
                    value={draft.email}
                    onChange={(event) => change("email", event.target.value)}
                    autoComplete="email"
                    maxLength={255}
                  />
                </label>
                <label className="space-y-2 text-sm font-medium">
                  Teléfono
                  <input
                    id="phone"
                    className={operationStyles.field}
                    value={draft.phone}
                    onChange={(event) => change("phone", event.target.value)}
                    autoComplete="tel"
                    maxLength={20}
                  />
                </label>
              </div>
            </section>
            <section
              className={`${operationStyles.panel} space-y-5 border-violet-200 bg-violet-50/30 p-5`}
            >
              <SectionHeading
                icon={Shield}
                title="Seguridad y Permisos"
                tone="violet"
              />
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2 text-sm font-medium">
                  Rol asignado
                  <select
                    className={operationStyles.field}
                    value={draft.role}
                    disabled={self}
                    onChange={(event) =>
                      change("role", event.target.value as UserDraft["role"])
                    }
                  >
                    {Object.entries(USER_ROLE_LABELS)
                      .filter(
                        ([role]) =>
                          actor?.role === "SUPERADMIN" ||
                          role !== "SUPERADMIN" ||
                          snapshot?.role === "SUPERADMIN",
                      )
                      .map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                  </select>
                </label>
                <div className="flex items-center justify-between gap-4 rounded-xl border border-violet-100 bg-white p-4">
                  <label
                    htmlFor="account-active"
                    className="text-sm font-medium"
                  >
                    Cuenta activa
                  </label>
                  <Switch
                    id="account-active"
                    checked={draft.is_active}
                    onCheckedChange={(value) => change("is_active", value)}
                    disabled={self}
                  />
                </div>
              </div>
              {self && (
                <p className="text-sm text-slate-600">
                  Tu propio rol y estado se conservan. El servidor aplica estas
                  restricciones.
                </p>
              )}
            </section>
            <section
              className={`${operationStyles.panel} space-y-5 border-amber-200 bg-amber-50/30 p-5`}
            >
              <SectionHeading
                icon={KeyRound}
                title={creating ? "Contraseña inicial" : "Cambiar Contraseña"}
                tone="amber"
              />
              {!creating && (
                <div className="flex items-center justify-between gap-4">
                  <label
                    htmlFor="change-password"
                    className="text-sm font-medium"
                  >
                    Cambiar contraseña
                  </label>
                  <Switch
                    id="change-password"
                    checked={changePassword}
                    onCheckedChange={(value) => {
                      setChangePassword(value);
                      if (!value) {
                        setPassword("");
                        setConfirmation("");
                      }
                    }}
                  />
                </div>
              )}
              {(creating || changePassword) && (
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2 text-sm font-medium">
                    {creating ? "Contraseña *" : "Nueva Contraseña"}
                    <input
                      type="password"
                      className={operationStyles.field}
                      placeholder="••••••"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="new-password"
                    />
                  </label>
                  <label className="space-y-2 text-sm font-medium">
                    Confirmar Contraseña
                    <input
                      type="password"
                      className={operationStyles.field}
                      placeholder="••••••"
                      value={confirmation}
                      onChange={(event) => setConfirmation(event.target.value)}
                      autoComplete="new-password"
                    />
                  </label>
                </div>
              )}
              <p className="text-sm text-slate-600">
                Entre 8 y 128 caracteres.
                {!creating &&
                  " Un cambio de contraseña invalida las sesiones de la cuenta. Datos y contraseña se guardan en operaciones separadas."}
              </p>
            </section>
          </fieldset>
          <div
            className={`${operationStyles.panel} flex flex-wrap justify-between gap-3 p-4`}
          >
            <Link
              className={operationStyles.button}
              href="/manager/admin/users"
            >
              Cancelar
            </Link>
            <button
              type="submit"
              className={operationStyles.primaryButton}
              disabled={!editable}
            >
              {saving
                ? "Guardando…"
                : creating
                  ? "Crear Usuario"
                  : "Guardar Cambios"}
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
