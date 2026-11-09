import type { User, UserRole } from "@/types/user";

export const USER_PAGE_SIZE = 50;
export const USER_ROLE_LABELS: Record<UserRole, string> = {
  SUPERADMIN: "Superadministrador",
  GERENTE: "Gerente",
  OPERADOR: "Operador",
  REPARTIDOR: "Repartidor",
  CLIENTE: "Cliente",
  AUDITOR: "Auditor",
};
export type UserDraft = {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  role: UserRole;
  is_active: boolean;
};
export const userDisplayName = (user: Partial<User>) =>
  [user.first_name, user.last_name].filter(Boolean).join(" ").trim() ||
  user.full_name?.trim() ||
  "Nombre no informado";
export const canManageAccount = (
  actor: string | undefined,
  role: string | undefined,
) =>
  actor === "SUPERADMIN" ||
  (actor === "GERENTE" &&
    !!role &&
    Object.hasOwn(USER_ROLE_LABELS, role) &&
    role !== "SUPERADMIN");
export function cleanUserDraft(draft: UserDraft): UserDraft {
  const first_name = draft.first_name.trim(),
    last_name = draft.last_name.trim(),
    email = draft.email.trim(),
    phone = draft.phone.trim();
  if (
    !first_name ||
    !last_name ||
    first_name.length > 100 ||
    last_name.length > 100
  )
    throw new Error(
      "Nombre y apellido son obligatorios y admiten hasta 100 caracteres cada uno.",
    );
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 255)
    throw new Error("Introduce un email válido.");
  if (phone.length > 20)
    throw new Error("El teléfono admite hasta 20 caracteres.");
  if (
    !Object.hasOwn(USER_ROLE_LABELS, draft.role) ||
    typeof draft.is_active !== "boolean"
  )
    throw new Error("Selecciona un rol y estado válidos.");
  return { ...draft, first_name, last_name, email, phone };
}
export function validateUserPassword(
  password: string,
  confirmation: string,
): void {
  const length = Array.from(password).length;
  if (length < 8 || length > 128 || !password.trim())
    throw new Error(
      "La contraseña debe tener entre 8 y 128 caracteres y no puede contener solo espacios.",
    );
  if (password !== confirmation)
    throw new Error("Las contraseñas no coinciden.");
}
