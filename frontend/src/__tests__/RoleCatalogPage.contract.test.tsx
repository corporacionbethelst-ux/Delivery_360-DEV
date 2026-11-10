import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/admin/roles/page";
import {
  roleService,
  type Permission,
  type Role,
} from "@/services/role.service";
import { downloadCSV } from "@/lib/csv-export";
import { storeTokens } from "@/lib/auth-session";
const mockRouter = { replace: jest.fn() };
let mockUser: { id: string; role: string } | null = {
    id: "manager",
    role: "GERENTE",
  },
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/services/role.service", () => ({
  roleService: { getAll: jest.fn(), getPermissions: jest.fn() },
}));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn(() => true) }));
const service = jest.mocked(roleService),
  download = jest.mocked(downloadCSV);
const roles: Role[] = [
  {
    id: "GERENTE",
    slug: "GERENTE",
    name: "Gerente",
    description: "Gestión operativa",
    permissions: ["orders.read", "users.manage", "unknown.feature"],
    users_count: 0,
    is_system: true,
  },
  {
    id: "OPERADOR",
    slug: "OPERADOR",
    name: "Operador",
    permissions: ["orders.read"],
    users_count: 2,
    is_system: true,
  },
  {
    id: "AUDITOR",
    slug: "AUDITOR",
    name: "Auditor",
    permissions: ["orders.read", "financial.read"],
    users_count: 1,
    is_system: true,
  },
  {
    id: "FUTURE",
    slug: "FUTURE",
    name: "Futuro",
    permissions: [],
    users_count: 0,
    is_system: false,
  },
];
const permissions: Permission[] = [
  {
    id: "orders.read",
    name: "Ver órdenes",
    module: "orders",
    description: "Consultar órdenes",
  },
  { id: "users.manage", name: "Gestionar usuarios", module: "users" },
  { id: "financial.read", name: "Ver finanzas", module: "financial" },
  { id: "future.read", name: "Consulta futura", module: "__proto__" },
];
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  jest.clearAllMocks();
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getAll.mockReset().mockResolvedValue(roles);
  service.getPermissions.mockReset().mockResolvedValue(permissions);
  download.mockReset().mockReturnValue(true);
});
async function loaded() {
  await screen.findByRole("article", { name: "Rol GERENTE" });
  await screen.findByRole("region", {
    name: "Catálogo de permisos confirmado",
  });
}
function choose(...names: string[]) {
  for (const name of names)
    fireEvent.click(screen.getByRole("checkbox", { name: `Comparar ${name}` }));
}
const matrix = () =>
  screen.getByRole("region", { name: "Matriz de comparación" });
const comparison = () =>
  screen.getByRole("region", { name: "Comparación de roles" });

it.each(["OPERADOR", "REPARTIDOR", "CLIENTE", "AUDITOR"])(
  "denies %s before consulting the administrative catalogs",
  (role) => {
    mockUser = { id: "denied", role };
    render(<Page />);
    expect(service.getAll).not.toHaveBeenCalled();
    expect(service.getPermissions).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("does not query when authentication is not confirmed", () => {
  mockUser = null;
  mockAuthenticated = false;
  render(<Page />);
  expect(service.getAll).not.toHaveBeenCalled();
});
it.each(["GERENTE", "SUPERADMIN"])(
  "loads catalogs for %s and shows actual zero account counts without editing controls",
  async (role) => {
    mockUser = { id: "manager", role };
    render(<Page />);
    await loaded();
    expect(
      within(screen.getByRole("article", { name: "Rol GERENTE" })).getByText(
        "0",
        { exact: true },
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Gestionar cuentas" }),
    ).toHaveAttribute("href", "/manager/admin/users");
    expect(
      screen.queryByRole("button", { name: /Crear|Guardar|Eliminar/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/La autorización se comprueba en cada operación/),
    ).toBeInTheDocument();
  },
);
it("preserves false system flags, empty declared lists and unknown module names", async () => {
  render(<Page />);
  await loaded();
  const future = screen.getByRole("article", { name: "Rol FUTURE" });
  expect(future).toHaveTextContent("Tipo no sistema");
  expect(future).toHaveTextContent("lista de permisos vacía");
  expect(
    screen.getByRole("region", { name: "Módulo __proto__" }),
  ).toBeInTheDocument();
});
it("filters role names, IDs and granted permission names locally with accent normalization", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Buscar roles"), {
    target: { value: "gestion" },
  });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(
    screen.getByRole("article", { name: "Rol GERENTE" }),
  ).toBeInTheDocument();
  expect(service.getAll).toHaveBeenCalledTimes(1);
  expect(service.getPermissions).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("Rol a consultar"), {
    target: { value: "role:OPERADOR" },
  });
  expect(
    screen.getByText("No hay roles que coincidan con los filtros locales."),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
  expect(screen.getAllByRole("article")).toHaveLength(4);
});
it("does not turn a role read failure into a zero or an empty role list", async () => {
  service.getAll.mockRejectedValueOnce(new Error("roles"));
  render(<Page />);
  await screen.findByText(/No se pudieron actualizar los roles/);
  expect(
    screen.queryByRole("region", { name: "Roles de la consulta confirmada" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("La consulta confirmada no contiene roles."),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar roles" }));
  await loaded();
  expect(service.getPermissions).toHaveBeenCalledTimes(1);
});
it("does not replace a failed permission catalog with fallback capabilities", async () => {
  service.getPermissions.mockRejectedValueOnce(new Error("permissions"));
  render(<Page />);
  await screen.findByText(/No se pudo actualizar el catálogo/);
  expect(
    screen.queryByRole("region", { name: "Catálogo de permisos confirmado" }),
  ).not.toBeInTheDocument();
  const manager = await screen.findByRole("article", { name: "Rol GERENTE" });
  expect(manager).toHaveTextContent("orders.read");
  expect(manager).toHaveTextContent("Sin ficha disponible");
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  expect(matrix()).toHaveTextContent("orders.read");
  expect(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar permisos" }));
  await screen.findByRole("region", {
    name: "Catálogo de permisos confirmado",
  });
  expect(service.getAll).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  ).toBeEnabled();
});
it("retains confirmed role records and timestamps after refresh errors", async () => {
  render(<Page />);
  await loaded();
  const before = screen.getByText(/Roles confirmados:/).textContent;
  service.getAll.mockRejectedValueOnce(new Error("refresh"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar catálogo" }));
  await screen.findByText(/No se pudieron actualizar los roles/);
  expect(screen.getByText(/Roles confirmados:/).textContent).toBe(before);
  expect(screen.getAllByRole("article")).toHaveLength(4);
});
it("retains the last permission sheets and blocks downloads when that refresh failed", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  const before = screen.getByText(/Permisos confirmados:/).textContent;
  service.getPermissions.mockRejectedValueOnce(new Error("refresh"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar catálogo" }));
  await screen.findByText(/No se pudo actualizar el catálogo/);
  expect(screen.getByText(/Permisos confirmados:/).textContent).toBe(before);
  expect(
    screen.getByRole("region", { name: "Módulo orders" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  ).toBeDisabled();
});
it("compares two roles with explicit declared and undeclared labels including unlisted references", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  const shared = within(matrix()).getByText("orders.read").closest("tr")!;
  expect(
    within(shared).getAllByText("Declarado", { exact: true }),
  ).toHaveLength(2);
  const unknown = within(matrix()).getByText("unknown.feature").closest("tr")!;
  expect(unknown).toHaveTextContent("Sin ficha disponible");
  expect(
    within(unknown).getByText("No declarado", { exact: true }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/no modifica ni concede accesos/),
  ).toBeInTheDocument();
});
it("requires two selected roles and caps the comparison at three without replacing selections", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]");
  expect(
    screen.queryByRole("region", { name: "Matriz de comparación" }),
  ).not.toBeInTheDocument();
  choose("Operador [OPERADOR]", "Auditor [AUDITOR]");
  expect(
    screen.getByRole("checkbox", { name: "Comparar Futuro [FUTURE]" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Quitar rol GERENTE" }));
  expect(
    screen.getByRole("checkbox", { name: "Comparar Futuro [FUTURE]" }),
  ).toBeEnabled();
  expect(
    within(matrix()).getByRole("columnheader", { name: /Operador/ }),
  ).toBeInTheDocument();
});
it("selection survives local role filters and clear selection removes the comparison", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.change(screen.getByLabelText("Buscar roles"), {
    target: { value: "Auditor" },
  });
  expect(matrix()).toBeInTheDocument();
  expect(comparison()).toHaveTextContent("2 de 3");
  fireEvent.click(screen.getByRole("button", { name: "Vaciar selección" }));
  expect(
    screen.queryByRole("region", { name: "Matriz de comparación" }),
  ).not.toBeInTheDocument();
});
it("filters common grants and differences without another server request", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.change(screen.getByLabelText("Vista de comparación"), {
    target: { value: "COMMON" },
  });
  expect(within(matrix()).getAllByRole("row")).toHaveLength(2);
  expect(matrix()).toHaveTextContent("orders.read");
  fireEvent.change(screen.getByLabelText("Vista de comparación"), {
    target: { value: "DIFFERENT" },
  });
  expect(within(matrix()).getAllByRole("row")).toHaveLength(3);
  expect(within(matrix()).queryByText("orders.read")).not.toBeInTheDocument();
  expect(service.getAll).toHaveBeenCalledTimes(1);
});
it("permission text and module filters scope the catalog and comparison together", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.change(screen.getByLabelText("Buscar permisos"), {
    target: { value: "ordenes" },
  });
  expect(within(matrix()).getAllByRole("row")).toHaveLength(2);
  expect(screen.getAllByRole("article")).toHaveLength(4);
  fireEvent.change(screen.getByLabelText("Buscar permisos"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("Módulo de permisos"), {
    target: { value: "missing" },
  });
  expect(within(matrix()).getAllByRole("row")).toHaveLength(2);
  expect(matrix()).toHaveTextContent("unknown.feature");
  expect(
    screen.getByText(
      "No hay fichas que coincidan con los filtros locales de permisos.",
    ),
  ).toBeInTheDocument();
});
it("exports only visible comparison rows, role columns and real source timestamps", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.change(screen.getByLabelText("Módulo de permisos"), {
    target: { value: "module:users" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  );
  expect(download).toHaveBeenCalledWith(
    [
      expect.objectContaining({
        Permiso: "users.manage",
        "Rol 1: Gerente [GERENTE]": "Declarado",
        "Rol 2: Operador [OPERADOR]": "No declarado",
        "Consulta roles (Caracas)": expect.any(String),
        "Consulta permisos (Caracas)": expect.any(String),
      }),
    ],
    "roles_comparacion",
  );
  expect(await screen.findByText(/Se inició la descarga/)).toBeInTheDocument();
});
it("reports a local CSV failure and allows an explicit retry", async () => {
  download.mockImplementationOnce(() => {
    throw new Error("blob");
  });
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.click(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("No se pudo preparar");
  fireEvent.click(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  );
  expect(download).toHaveBeenCalledTimes(2);
});
it("empty filtered comparisons disable CSV rather than downloading an empty invented result", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  fireEvent.change(screen.getByLabelText("Buscar permisos"), {
    target: { value: "nothing-matches" },
  });
  expect(
    screen.getByText(
      "No hay permisos que coincidan con los filtros de la comparación.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Descargar comparación (CSV)" }),
  ).toBeDisabled();
  expect(download).not.toHaveBeenCalled();
});
it("explicit empty catalogs are displayed as confirmed empty, independently", async () => {
  service.getAll.mockResolvedValue([]);
  service.getPermissions.mockResolvedValue([]);
  render(<Page />);
  await screen.findByText("La consulta confirmada no contiene roles.");
  await screen.findByText("El catálogo confirmado no contiene permisos.");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("a removed selected role stays identified and cannot silently turn into another comparison column", async () => {
  render(<Page />);
  await loaded();
  choose("Gerente [GERENTE]", "Operador [OPERADOR]");
  service.getAll.mockResolvedValue(
    roles.filter((role) => role.id !== "OPERADOR"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Actualizar catálogo" }));
  await screen.findByText(/Ya no figuran en los roles cargados: OPERADOR/);
  expect(
    screen.queryByRole("region", { name: "Matriz de comparación" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Quitar rol OPERADOR" }),
  ).toBeInTheDocument();
});
it("preserves an unavailable module filter after catalog refresh instead of presenting it as all modules", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Módulo de permisos"), {
    target: { value: "module:financial" },
  });
  service.getPermissions.mockResolvedValue(
    permissions.filter((permission) => permission.module !== "financial"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Actualizar catálogo" }));
  await screen.findByRole("option", {
    name: "Módulo ya no disponible: financial",
  });
  expect(screen.getByLabelText("Módulo de permisos")).toHaveValue(
    "module:financial",
  );
});
it("StrictMode retires an older response even if it finishes last", async () => {
  const old = deferred<Role[]>();
  service.getAll
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce([{ ...roles[0], name: "Latest role" }]);
  render(
    <React.StrictMode>
      <Page />
    </React.StrictMode>,
  );
  await screen.findByRole("heading", { name: "Latest role" });
  await act(async () => old.resolve(roles));
  expect(
    screen.queryByRole("heading", { name: "Operador" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Latest role" }),
  ).toBeInTheDocument();
});
it.each(["account", "credentials"])(
  "retired %s data and local comparison state do not survive into a new session",
  async (kind) => {
    const view = render(<Page />);
    await loaded();
    choose("Gerente [GERENTE]", "Operador [OPERADOR]");
    if (kind === "account") {
      mockUser = { id: "other-manager", role: "GERENTE" };
      view.rerender(<Page />);
    } else
      act(() =>
        storeTokens({
          access_token: "roles84-new-account",
          refresh_token: "roles84-new-refresh",
        }),
      );
    await waitFor(() => expect(service.getAll).toHaveBeenCalledTimes(2));
    expect(
      screen.queryByRole("region", { name: "Matriz de comparación" }),
    ).not.toBeInTheDocument();
    expect(comparison()).toHaveTextContent("0 de 3");
  },
);
it("a pending role response cannot populate the next account", async () => {
  const pending = deferred<Role[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  const view = render(<Page />);
  service.getAll.mockResolvedValue([]);
  mockUser = { id: "other", role: "SUPERADMIN" };
  view.rerender(<Page />);
  await screen.findByText("La consulta confirmada no contiene roles.");
  await act(async () => pending.resolve(roles));
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
});
