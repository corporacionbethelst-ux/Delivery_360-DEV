import { api } from "@/lib/api";
import {
  roleService,
  type Permission,
  type Role,
} from "@/services/role.service";
import {
  catalogTime,
  comparisonCSV,
  filterRoleComparison,
  normalizeRoleSearch,
  permissionModuleName,
  roleComparisonRows,
  sumRoleAccounts,
  validatePermissions,
  validateRoles,
} from "@/lib/role-catalog";
import { serializeCSV } from "@/lib/csv-export";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
}));
const get = jest.mocked(api.get);
const role: Role = {
  id: "GERENTE",
  slug: "GERENTE",
  name: "Gerente",
  description: "Gestión",
  permissions: ["orders.read", "unknown.feature"],
  users_count: 0,
  is_system: true,
  created_at: null,
};
const permissions: Permission[] = [
  {
    id: "orders.read",
    name: "Ver órdenes",
    module: "orders",
    description: "Consultar",
  },
  { id: "users.manage", name: "Gestionar usuarios", module: "users" },
];
const other = {
  ...role,
  id: "OPERADOR",
  slug: "OPERADOR",
  name: "Operador",
  permissions: ["orders.read", "users.manage"],
};
beforeEach(() => {
  jest.resetAllMocks();
});
afterEach(() => {
  clearStoredTokens();
});
it("loads the actual readonly endpoints and preserves zero and a false system flag", async () => {
  get
    .mockResolvedValueOnce([
      Object.freeze({
        ...role,
        permissions: Object.freeze([...role.permissions]),
        is_system: false,
      }),
    ])
    .mockResolvedValueOnce(permissions);
  const roles = await roleService.getAll();
  expect(roles[0]).toMatchObject({ users_count: 0, is_system: false });
  expect(await roleService.getPermissions()).toEqual(permissions);
  expect(get.mock.calls.map((call) => call[0])).toEqual([
    "/roles",
    "/roles/permissions",
  ]);
});
it("copies permission arrays rather than mutating cached readonly API rows", () => {
  const input = Object.freeze([
    Object.freeze({
      ...role,
      permissions: Object.freeze([...role.permissions]),
    }),
  ]);
  const rows = validateRoles(input);
  rows[0].permissions.push("another");
  expect(input[0].permissions).toEqual(role.permissions);
});
it.each([
  null,
  {},
  [null],
  [{ ...role, id: "" }],
  [{ ...role, name: " " }],
  [{ ...role, slug: null }],
  [{ ...role, permissions: null }],
  [{ ...role, permissions: ["orders.read", "orders.read"] }],
  [{ ...role, permissions: [null] }],
  [{ ...role, users_count: undefined }],
  [{ ...role, users_count: "0" }],
  [{ ...role, users_count: -1 }],
  [{ ...role, users_count: 1.5 }],
  [{ ...role, users_count: Infinity }],
  [{ ...role, is_system: undefined }],
  [{ ...role, is_system: "false" }],
  [{ ...role, description: {} }],
  [role, role],
  [role, { ...other, slug: role.slug }],
])(
  "rejects malformed roles %j without inventing count or grants",
  async (value) => {
    get.mockResolvedValue(value);
    await expect(roleService.getAll()).rejects.toThrow();
  },
);
it.each([
  null,
  {},
  [null],
  [{ ...permissions[0], id: "" }],
  [{ ...permissions[0], name: null }],
  [{ ...permissions[0], module: " " }],
  [{ ...permissions[0], description: {} }],
  [permissions[0], permissions[0]],
])(
  "rejects malformed permission catalogs %j without a fallback list",
  async (value) => {
    get.mockResolvedValue(value);
    await expect(roleService.getPermissions()).rejects.toThrow();
  },
);
it("accepts confirmed empty catalogs and forward-compatible literal IDs and modules", () => {
  expect(validateRoles([])).toEqual([]);
  expect(validatePermissions([])).toEqual([]);
  expect(
    validatePermissions([
      { id: "__proto__", name: "constructor", module: "__proto__" },
    ])[0].module,
  ).toBe("__proto__");
  expect(permissionModuleName("__proto__")).toBe("__proto__");
});
it.each(["roles", "permissions"])(
  "retires a %s response when credentials change",
  async (source) => {
    let resolve!: (value: unknown) => void;
    get.mockReturnValueOnce(
      new Promise((yes) => {
        resolve = yes;
      }),
    );
    const pending =
      source === "roles" ? roleService.getAll() : roleService.getPermissions();
    storeTokens({
      access_token: "role84-changed",
      refresh_token: "role84-refresh",
    });
    resolve(source === "roles" ? [role] : permissions);
    await expect(pending).rejects.toThrow("sesión cambió");
  },
);
it.each(["create", "update", "delete"])(
  "rejects %s locally because the API only supports system-role reads",
  async (operation) => {
    const input = { name: "Nuevo", slug: "NEW", permissions: [] };
    const request =
      operation === "create"
        ? roleService.create(input)
        : operation === "update"
          ? roleService.update("GERENTE", input)
          : roleService.delete("GERENTE");
    await expect(request).rejects.toThrow("solo se pueden consultar");
    expect(api.post).not.toHaveBeenCalled();
    expect(api.patch).not.toHaveBeenCalled();
    expect(api.delete).not.toHaveBeenCalled();
  },
);
it("compares the union of catalog and declared references without dropping unlisted permissions", () => {
  const rows = roleComparisonRows([role, other], permissions);
  expect(
    rows.map((row) => ({
      id: row.id,
      declarations: row.declarations,
      known: !!row.permission,
    })),
  ).toEqual([
    { id: "orders.read", declarations: [true, true], known: true },
    { id: "users.manage", declarations: [false, true], known: true },
    { id: "unknown.feature", declarations: [true, false], known: false },
  ]);
});
it.each(["ALL", "COMMON", "DIFFERENT"] as const)(
  "filters comparison mode %s with actual declarations",
  (mode) => {
    const rows = filterRoleComparison(
      roleComparisonRows([role, other], permissions),
      "",
      "all",
      mode,
    );
    expect(rows.map((row) => row.id)).toEqual(
      mode === "ALL"
        ? ["orders.read", "users.manage", "unknown.feature"]
        : mode === "COMMON"
          ? ["orders.read"]
          : ["users.manage", "unknown.feature"],
    );
  },
);
it("search normalizes accents and filters known and unavailable module sheets explicitly", () => {
  const rows = roleComparisonRows([role, other], permissions);
  expect(normalizeRoleSearch(" ÓRDENES ")).toBe("ordenes");
  expect(
    filterRoleComparison(rows, "ordenes", "module:orders", "ALL").map(
      (row) => row.id,
    ),
  ).toEqual(["orders.read"]);
  expect(
    filterRoleComparison(rows, "", "missing", "ALL").map((row) => row.id),
  ).toEqual(["unknown.feature"]);
  expect(filterRoleComparison(rows, "", "module:unknown", "ALL")).toEqual([]);
  expect(
    filterRoleComparison(
      roleComparisonRows([], permissions),
      "",
      "all",
      "COMMON",
    ),
  ).toEqual([]);
});
it("totals only loaded account counts and does not overflow safe numeric precision", () => {
  expect(sumRoleAccounts([role, other])).toBe(0);
  expect(
    sumRoleAccounts([
      { ...role, users_count: Number.MAX_SAFE_INTEGER },
      { ...other, users_count: 1 },
    ]),
  ).toBeNull();
});
it("exports exactly visible declarations with both reading times and neutralizes formula cells", () => {
  const selected = [{ ...role, name: "=Admin" }, other],
    rows = filterRoleComparison(
      roleComparisonRows(selected, permissions),
      "",
      "missing",
      "ALL",
    );
  const at = new Date("2026-11-10T12:00:00Z"),
    data = comparisonCSV(rows, selected, at, at);
  expect(data).toHaveLength(1);
  expect(data[0]).toMatchObject({
    Permiso: "unknown.feature",
    Nombre: "Sin ficha en catálogo",
    "Rol 1: =Admin [GERENTE]": "Declarado",
    "Rol 2: Operador [OPERADOR]": "No declarado",
    "Consulta roles (Caracas)": catalogTime(at),
    "Consulta permisos (Caracas)": catalogTime(at),
  });
  const formula = {
    ...permissions[0],
    name: "=HYPERLINK(1)",
    description: "línea",
  };
  expect(
    serializeCSV(
      comparisonCSV(
        roleComparisonRows([role, other], [formula]),
        [role, other],
        at,
        at,
      ),
    ),
  ).toContain("'=HYPERLINK(1)");
});
