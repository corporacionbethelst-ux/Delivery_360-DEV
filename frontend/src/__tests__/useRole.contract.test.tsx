import { renderHook } from "@testing-library/react";
import { useRole } from "@/hooks/useRole";
let mockUser: { role: string } | null = { role: "GERENTE" },
  mockAuthenticated = true,
  mockLoading = false;
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    user: mockUser,
    isAuthenticated: mockAuthenticated,
    isLoading: mockLoading,
  }),
}));
beforeEach(() => {
  mockUser = { role: "GERENTE" };
  mockAuthenticated = true;
  mockLoading = false;
});
it.each(["GERENTE", "OPERADOR", "REPARTIDOR", "CLIENTE", "SUPERADMIN"])(
  "exposes exact local role helpers for %s",
  (role) => {
    mockUser = { role };
    const { result } = renderHook(() => useRole());
    const r = result.current;
    expect(r.currentRole).toBe(role);
    expect(r.hasRole(role as never)).toBe(true);
    expect(r.hasRole("UNKNOWN" as never)).toBe(false);
    expect(r.roleName).not.toBe("");
    expect(r.roleDescription).not.toBe("");
    for (const [name, value] of [
      ["SUPERADMIN", r.isSuperadmin()],
      ["GERENTE", r.isGerente()],
      ["OPERADOR", r.isOperador()],
      ["REPARTIDOR", r.isRepartidor()],
      ["CLIENTE", r.isCliente()],
    ])
      expect(value).toBe(name === role);
  },
);
it("retires all permission and role hints during logout and verification", () => {
  const { result, rerender } = renderHook(() => useRole());
  expect(result.current.hasPermission("financial", "read")).toBe(true);
  mockAuthenticated = false;
  rerender();
  expect(result.current.currentRole).toBeNull();
  expect(result.current.isGerente()).toBe(false);
  expect(result.current.hasPermission("orders", "read")).toBe(false);
  expect(result.current.hasAnyPermission("orders", ["read"])).toBe(false);
  expect(result.current.canAccessModule("orders")).toBe(false);
  mockAuthenticated = true;
  mockLoading = true;
  rerender();
  expect(result.current.currentRole).toBeNull();
});
it.each([null, { role: "" }, { role: "UNKNOWN" }, { role: "AUDITOR" }])(
  "fails closed for absent/unconfigured roles %#",
  (user) => {
    mockUser = user;
    const { result } = renderHook(() => useRole());
    expect(result.current.currentRole).toBeNull();
    expect(result.current.roleName).toBe("");
    expect(result.current.roleDescription).toBe("");
    expect(result.current.permissions).toEqual([]);
    expect(result.current.hasPermission("orders", "read")).toBe(false);
  },
);
it("keeps operator capabilities distinct from administration", () => {
  mockUser = { role: "operador" };
  const { result } = renderHook(() => useRole());
  expect(result.current.currentRole).toBe("OPERADOR");
  expect(result.current.hasPermission("orders", "read")).toBe(true);
  expect(result.current.hasPermission("orders", "delete")).toBe(false);
  expect(result.current.hasPermission("unknown", "read")).toBe(false);
  expect(result.current.hasAnyPermission("orders", ["delete", "read"])).toBe(
    true,
  );
  expect(result.current.hasAnyPermission("orders", ["delete"])).toBe(false);
  expect(result.current.hasAnyPermission("unknown", ["read"])).toBe(false);
  expect(result.current.canAccessModule("orders")).toBe(true);
  expect(result.current.canAccessModule("financial")).toBe(false);
});
it("applies the documented superadmin wildcard consistently without accepting an empty request", () => {
  mockUser = { role: "SUPERADMIN" };
  const { result } = renderHook(() => useRole());
  expect(result.current.hasPermission("unknown", "any")).toBe(true);
  expect(result.current.canAccessModule("unknown")).toBe(true);
  expect(result.current.hasAnyPermission("unknown", ["read"])).toBe(true);
  expect(result.current.hasAnyPermission("orders", [])).toBe(false);
});
