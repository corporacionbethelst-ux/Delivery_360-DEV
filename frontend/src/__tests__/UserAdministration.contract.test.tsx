import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Catalog from "@/app/(dashboard)/manager/admin/users/page";
import Create from "@/app/(dashboard)/manager/admin/users/new/page";
import Edit from "@/app/(dashboard)/manager/admin/users/[id]/page";
import { userService } from "@/services/user.service";
import type { User } from "@/types/user";
import {
  canManageAccount,
  cleanUserDraft,
  validateUserPassword,
} from "@/lib/user-administration";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
let mockId = "target",
  mockUser: { id: string; role: string } | null = {
    id: "manager",
    role: "GERENTE",
  },
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useParams: () => ({ id: mockId }),
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/services/user.service", () => ({
  userService: {
    getAll: jest.fn(),
    getById: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    updatePassword: jest.fn(),
    deactivate: jest.fn(),
  },
}));
const service = jest.mocked(userService),
  revision = "a".repeat(64),
  next = "b".repeat(64);
const row = {
  id: "target",
  user_revision: revision,
  first_name: "José",
  last_name: "Pérez",
  email: "jose@example.test",
  phone: "04121234567",
  role: "OPERADOR",
  is_active: true,
  created_at: "2026-11-08T12:00:00",
} as User;
const valid = {
  first_name: " Ana ",
  last_name: " Pérez ",
  email: " ana@example.test ",
  phone: " 04121234567 ",
  role: "OPERADOR" as const,
  is_active: true,
};
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  jest.resetAllMocks();
  mockId = row.id;
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getAll.mockResolvedValue([row]);
  service.getById.mockResolvedValue(row);
  service.create.mockResolvedValue({ ...row, id: "created" });
  service.update.mockResolvedValue({ ...row, user_revision: next });
  service.updatePassword.mockResolvedValue({ ...row, user_revision: next });
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});
function fillCreate() {
  for (const [label, value] of [
    ["Nombre *", valid.first_name],
    ["Apellido *", valid.last_name],
    ["Email *", valid.email],
    ["Teléfono", valid.phone],
    ["Contraseña *", "ValidPassword123!"],
    ["Confirmar Contraseña", "ValidPassword123!"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
const editReady = () => screen.findByDisplayValue("José");

describe.each([
  ["catálogo", Catalog],
  ["alta", Create],
  ["edición", Edit],
] as const)("permisos de %s", (_name, Page) => {
  it.each(["OPERADOR", "REPARTIDOR", "CLIENTE", "AUDITOR"])(
    "deniega %s antes de leer o guardar",
    (role) => {
      mockUser = { id: "other", role };
      render(<Page />);
      expect(service.getAll).not.toHaveBeenCalled();
      expect(service.getById).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: /Guardar|Crear Usuario/ }),
      ).not.toBeInTheDocument();
      expect(mockRouter.replace).toHaveBeenCalledWith("/login");
    },
  );
});
it.each(["GERENTE", "SUPERADMIN"])(
  "permite catálogo a %s con consulta paginada real",
  async (role) => {
    mockUser = { id: "actor", role };
    render(<Catalog />);
    await screen.findByText("José Pérez");
    expect(service.getAll).toHaveBeenCalledWith({ limit: 51, skip: 0 });
  },
);
it("gerencia no ofrece alta Superadmin y sí permite Auditor", () => {
  render(<Create />);
  expect(
    screen.queryByRole("option", { name: "Superadministrador" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Auditor" })).toBeInTheDocument();
});
it("superadministración puede seleccionar todos los roles del backend", () => {
  mockUser = { id: "root", role: "SUPERADMIN" };
  render(<Create />);
  expect(
    screen.getByRole("option", { name: "Superadministrador" }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("option")).toHaveLength(6);
});
it.each([
  ["GERENTE", "SUPERADMIN", false],
  ["GERENTE", "AUDITOR", true],
  ["SUPERADMIN", "SUPERADMIN", true],
  ["OPERADOR", "OPERADOR", false],
])("aplica permiso %s sobre %s", (actor, target, allowed) => {
  expect(canManageAccount(actor, target)).toBe(allowed);
});
it.each([
  { first_name: "   " },
  { last_name: "   " },
  { first_name: "x".repeat(101) },
  { last_name: "x".repeat(101) },
  { email: "not-an-email" },
  { phone: "1".repeat(21) },
])("valida campos antes del servicio %p", (patch) => {
  expect(() => cleanUserDraft({ ...valid, ...patch })).toThrow();
});
it("recorta datos de contacto y conserva estado falso", () => {
  expect(cleanUserDraft({ ...valid, is_active: false })).toMatchObject({
    first_name: "Ana",
    last_name: "Pérez",
    email: "ana@example.test",
    phone: "04121234567",
    is_active: false,
  });
});
it.each([
  ["short", "short"],
  [" ".repeat(8), " ".repeat(8)],
  ["x".repeat(129), "x".repeat(129)],
  ["ValidPass1", "Different1"],
])("valida contraseña y confirmación", (password, confirm) => {
  expect(() => validateUserPassword(password, confirm)).toThrow();
});
it("conserva bytes significativos de contraseña y admite los límites del backend", () => {
  expect(() =>
    validateUserPassword(" spaced password ", " spaced password "),
  ).not.toThrow();
  expect(() =>
    validateUserPassword("x".repeat(128), "x".repeat(128)),
  ).not.toThrow();
});

it("el alta no inventa ni sobrescribe el correo al salir de nombre y apellido", () => {
  render(<Create />);
  fireEvent.change(screen.getByLabelText("Email *"), {
    target: { value: "manual@example.test" },
  });
  fireEvent.change(screen.getByLabelText("Nombre *"), {
    target: { value: "José" },
  });
  fireEvent.blur(screen.getByLabelText("Nombre *"));
  fireEvent.blur(screen.getByLabelText("Apellido *"));
  expect(screen.getByLabelText("Email *")).toHaveValue("manual@example.test");
  expect(
    screen.queryByText(/Notas Internas|Biografía/),
  ).not.toBeInTheDocument();
});
it("el alta envía teléfono, apellidos y datos limpios realmente persistibles", async () => {
  render(<Create />);
  fillCreate();
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  await waitFor(() =>
    expect(service.create).toHaveBeenCalledWith({
      ...valid,
      first_name: "Ana",
      last_name: "Pérez",
      email: "ana@example.test",
      phone: "04121234567",
      password: "ValidPassword123!",
    }),
  );
  expect(
    await screen.findByText("Usuario creado correctamente.", { exact: false }),
  ).toBeVisible();
});
it("el alta inválida no emite escritura", async () => {
  render(<Create />);
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  await screen.findByRole("alert");
  expect(service.create).not.toHaveBeenCalled();
});
it("el alta bloquea campos, duplicados y reenvíos tras éxito", async () => {
  const pending = deferred<User>();
  service.create.mockReturnValue(pending.promise);
  render(<Create />);
  fillCreate();
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  fireEvent.click(screen.getByRole("button", { name: "Guardando…" }));
  expect(service.create).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Nombre *")).toBeDisabled();
  await act(async () => pending.resolve({ ...row, id: "created" }));
  expect(screen.getByRole("button", { name: "Crear Usuario" })).toBeDisabled();
});
it("el alta conserva el borrador para corregir email duplicado", async () => {
  service.create.mockRejectedValueOnce({
    code: "USER_EMAIL_CONFLICT",
    message: "El correo ya está registrado. Use otro correo",
  });
  render(<Create />);
  fillCreate();
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  await screen.findByText("El correo ya está registrado. Use otro correo");
  expect(screen.getByLabelText("Nombre *")).toHaveValue(" Ana ");
  fireEvent.change(screen.getByLabelText("Email *"), {
    target: { value: "free@example.test" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  await waitFor(() => expect(service.create).toHaveBeenCalledTimes(2));
  expect(service.create).toHaveBeenLastCalledWith(
    expect.objectContaining({ email: "free@example.test" }),
  );
});
it("un alta retirada no notifica ni redirige desde otra cuenta", async () => {
  const pending = deferred<User>();
  service.create.mockReturnValue(pending.promise);
  const view = render(<Create />);
  fillCreate();
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  mockUser = { id: "another", role: "GERENTE" };
  view.rerender(<Create />);
  await act(async () => pending.resolve({ ...row, id: "created" }));
  expect(
    screen.queryByText("Usuario creado correctamente.", { exact: false }),
  ).not.toBeInTheDocument();
  expect(mockRouter.push).not.toHaveBeenCalled();
});
it("desmontar tras el alta cancela el temporizador de navegación", async () => {
  jest.useFakeTimers();
  const view = render(<Create />);
  fillCreate();
  fireEvent.click(screen.getByRole("button", { name: "Crear Usuario" }));
  await screen.findByText("Usuario creado correctamente.", { exact: false });
  view.unmount();
  await act(async () => jest.advanceTimersByTime(2000));
  expect(mockRouter.push).not.toHaveBeenCalled();
});

it("un fallo de lectura no muestra un formulario inventado y el reintento recupera la ficha", async () => {
  service.getById.mockRejectedValueOnce(new Error("Read failed"));
  render(<Edit />);
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("Nombre *")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Recargar usuario" }));
  await editReady();
});
it("una respuesta de otro ID no permite editar", async () => {
  service.getById.mockResolvedValue({ ...row, id: "other" });
  render(<Edit />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no corresponde");
  expect(
    screen.queryByRole("button", { name: "Guardar Cambios" }),
  ).not.toBeInTheDocument();
});
it("la ficha de superadmin es solo lectura para gerencia", async () => {
  service.getById.mockResolvedValue({ ...row, role: "SUPERADMIN" });
  render(<Edit />);
  await editReady();
  expect(screen.getByLabelText("Nombre *")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Guardar Cambios" }),
  ).toBeDisabled();
  expect(
    screen.getByText("Solo un superadministrador puede modificar esta cuenta."),
  ).toBeVisible();
});
it("la cuenta propia conserva rol y estado pero permite editar datos personales", async () => {
  mockUser = { id: row.id, role: "GERENTE" };
  service.getById.mockResolvedValue({ ...row, role: "GERENTE" });
  render(<Edit />);
  await editReady();
  expect(screen.getByLabelText("Rol asignado")).toBeDisabled();
  expect(screen.getByRole("switch", { name: "Cuenta activa" })).toBeDisabled();
  expect(screen.getByLabelText("Nombre *")).toBeEnabled();
});
it("un guardado pendiente bloquea borrador, recarga y doble envío", async () => {
  const pending = deferred<User>();
  service.update.mockReturnValue(pending.promise);
  render(<Edit />);
  await editReady();
  fireEvent.click(screen.getByRole("button", { name: "Guardar Cambios" }));
  fireEvent.click(screen.getByRole("button", { name: "Guardando…" }));
  expect(service.update).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Teléfono")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Recargar usuario" }),
  ).toBeDisabled();
  await act(async () => pending.resolve({ ...row, user_revision: next }));
});
it("un acuse de otra ficha impide la segunda operación de contraseña", async () => {
  service.update.mockResolvedValue({
    ...row,
    id: "wrong",
    user_revision: next,
  });
  render(<Edit />);
  await editReady();
  fireEvent.click(screen.getByRole("switch", { name: "Cambiar contraseña" }));
  fireEvent.change(screen.getByLabelText("Nueva Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.change(screen.getByLabelText("Confirmar Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Guardar Cambios" }));
  await screen.findByRole("alert");
  expect(service.updatePassword).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Guardar Cambios" }),
  ).toBeDisabled();
});
it("cambiar de ruta durante los datos retira el cambio de contraseña pendiente", async () => {
  const pending = deferred<User>();
  service.update.mockReturnValue(pending.promise);
  const view = render(<Edit />);
  await editReady();
  fireEvent.click(screen.getByRole("switch", { name: "Cambiar contraseña" }));
  fireEvent.change(screen.getByLabelText("Nueva Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.change(screen.getByLabelText("Confirmar Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Guardar Cambios" }));
  mockId = "second";
  service.getById.mockResolvedValue({
    ...row,
    id: mockId,
    first_name: "Segunda",
  });
  view.rerender(<Edit />);
  await screen.findByDisplayValue("Segunda");
  await act(async () => pending.resolve({ ...row, user_revision: next }));
  expect(service.updatePassword).not.toHaveBeenCalled();
  expect(mockRouter.push).not.toHaveBeenCalled();
});
it("la revisión nueva y contraseña se vinculan al ID cargado", async () => {
  render(<Edit />);
  await editReady();
  fireEvent.click(screen.getByRole("switch", { name: "Cambiar contraseña" }));
  fireEvent.change(screen.getByLabelText("Nueva Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.change(screen.getByLabelText("Confirmar Contraseña"), {
    target: { value: "NewPassword123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Guardar Cambios" }));
  await screen.findByText("Usuario actualizado correctamente.", {
    exact: false,
  });
  expect(service.updatePassword).toHaveBeenCalledWith(
    row.id,
    "NewPassword123!",
  );
  expect(service.update).toHaveBeenCalledWith(
    row.id,
    expect.objectContaining({ expected_user_revision: revision }),
  );
});
it("credenciales nuevas retiran una lectura de edición anterior", async () => {
  const old = deferred<User>();
  service.getById.mockReturnValueOnce(old.promise);
  render(<Edit />);
  service.getById.mockResolvedValue({ ...row, first_name: "Confirmada" });
  await act(async () =>
    storeTokens({ access_token: "new", refresh_token: "new-refresh" }),
  );
  await screen.findByDisplayValue("Confirmada");
  await act(async () => old.resolve(row));
  expect(screen.queryByDisplayValue("José")).not.toBeInTheDocument();
  await act(async () => clearStoredTokens());
});

it("el catálogo no trata estado ausente como inactivo", async () => {
  service.getAll.mockResolvedValue([
    { ...row, is_active: undefined, role: undefined } as unknown as User,
  ]);
  render(<Catalog />);
  expect(await screen.findByText("Estado no informado")).toBeVisible();
  expect(screen.getByText("Rol no informado")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Desactivar usuario target" }),
  ).toBeDisabled();
});
it("el catálogo protege cuenta propia y cuentas superadmin", async () => {
  service.getAll.mockResolvedValue([
    { ...row, id: "manager", role: "GERENTE" },
    { ...row, id: "root", role: "SUPERADMIN" },
  ]);
  render(<Catalog />);
  await screen.findByRole("region", { name: "Tabla de usuarios" });
  expect(
    screen.getByRole("button", { name: "Desactivar usuario manager" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Desactivar usuario root" }),
  ).toBeDisabled();
});
it("un fallo inicial de catálogo no se convierte en vacío", async () => {
  service.getAll.mockRejectedValueOnce(new Error("offline"));
  render(<Catalog />);
  await screen.findByRole("alert");
  expect(
    screen.queryByText("La página consultada no contiene usuarios."),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar usuarios" }));
  await screen.findByText("José Pérez");
});
it("un fallo posterior conserva la consulta confirmada y bloquea mutaciones", async () => {
  render(<Catalog />);
  await screen.findByText("José Pérez");
  const before = screen.getByText(/Consulta confirmada:/).textContent;
  service.getAll.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  await screen.findByRole("alert");
  expect(screen.getByText("José Pérez")).toBeVisible();
  expect(screen.getByText(/Consulta confirmada:/).textContent).toBe(before);
  expect(
    screen.getByRole("button", { name: "Desactivar usuario target" }),
  ).toBeDisabled();
});
it("la búsqueda con tildes y contactos es local y el enlace conserva IDs", async () => {
  render(<Catalog />);
  await screen.findByText("José Pérez");
  fireEvent.change(
    screen.getByRole("textbox", { name: "Buscar en esta página" }),
    { target: { value: "jose" } },
  );
  expect(screen.getByText("José Pérez")).toBeVisible();
  expect(service.getAll).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("link", { name: "Ver ficha de target" }),
  ).toHaveAttribute("href", "/manager/admin/users/target");
});
it("lookahead permite páginas reales de 50 sin truncar el catálogo en 500", async () => {
  service.getAll
    .mockResolvedValueOnce(
      Array.from({ length: 51 }, (_, i) => ({ ...row, id: `user-${i}` })),
    )
    .mockResolvedValueOnce([row]);
  render(<Catalog />);
  await screen.findByRole("link", { name: "Ver ficha de user-0" });
  expect(screen.getAllByRole("row")).toHaveLength(51);
  expect(
    screen.queryByRole("link", { name: "Ver ficha de user-50" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
  await screen.findByRole("link", { name: "Ver ficha de target" });
  expect(service.getAll).toHaveBeenLastCalledWith({ limit: 51, skip: 50 });
  expect(
    screen.getByRole("button", { name: "Página siguiente" }),
  ).toBeDisabled();
});
it("los filtros de estado falso y Auditor consultan el servidor", async () => {
  render(<Catalog />);
  await screen.findByText("José Pérez");
  service.getAll.mockResolvedValue([
    { ...row, role: "AUDITOR", is_active: false },
  ]);
  fireEvent.change(screen.getByRole("combobox", { name: "Rol registrado" }), {
    target: { value: "AUDITOR" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Estado de cuenta" }), {
    target: { value: "false" },
  });
  await waitFor(() =>
    expect(service.getAll).toHaveBeenLastCalledWith({
      limit: 51,
      skip: 0,
      role: "AUDITOR",
      is_active: false,
    }),
  );
  await screen.findByText("Inactivo");
});
it("una respuesta duplicada no habilita desactivaciones", async () => {
  service.getAll.mockResolvedValue([row, row]);
  render(<Catalog />);
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("button", { name: "Desactivar usuario target" }),
  ).not.toBeInTheDocument();
});
it("desactivar bloquea todas las acciones y el cierre mientras espera", async () => {
  const pending = deferred<void>();
  service.deactivate.mockReturnValue(pending.promise);
  render(<Catalog />);
  await screen.findByText("José Pérez");
  fireEvent.click(
    screen.getByRole("button", { name: "Desactivar usuario target" }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Sí, desactivar",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Actualizar", hidden: true }),
  ).toBeDisabled();
  expect(service.deactivate).toHaveBeenCalledWith(row.id, revision);
  service.getAll.mockResolvedValue([{ ...row, is_active: false }]);
  await act(async () => pending.resolve());
  await screen.findByText("Inactivo");
});
it("una desactivación retirada no recarga ni anuncia en otra cuenta", async () => {
  const pending = deferred<void>();
  service.deactivate.mockReturnValue(pending.promise);
  const view = render(<Catalog />);
  await screen.findByText("José Pérez");
  fireEvent.click(
    screen.getByRole("button", { name: "Desactivar usuario target" }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Sí, desactivar",
    }),
  );
  mockUser = { id: "another", role: "GERENTE" };
  service.getAll.mockResolvedValue([]);
  view.rerender(<Catalog />);
  await screen.findByText("La página consultada no contiene usuarios.");
  await act(async () => pending.resolve());
  expect(service.getAll).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByText(/Desactivación confirmada/),
  ).not.toBeInTheDocument();
});
