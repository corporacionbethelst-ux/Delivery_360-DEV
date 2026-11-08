import * as auth from "@/lib/auth";
import type { User } from "@/types/user";
const token = (payload: unknown) =>
  `eyJhbGciOiJIUzI1NiJ9.${btoa(
    unescape(encodeURIComponent(JSON.stringify(payload))),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")}.synthetic-signature`;
const valid = () =>
  token({
    sub: "user-1",
    userId: "legacy-user",
    email: "user@example.test",
    role: "GERENTE",
    exp: Date.now() / 1000 + 3600,
  });
beforeEach(() => {
  localStorage.clear();
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-11-07T12:00:00Z"));
  jest.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});
it("roundtrips only structured token pairs in optional local storage", () => {
  const pair = {
    access_token: valid(),
    refresh_token: "synthetic-refresh",
    token_type: "bearer",
  };
  auth.saveTokens(pair);
  expect(auth.getTokens()).toEqual(pair);
  auth.clearTokens();
  expect(auth.getTokens()).toBeNull();
});
it.each([
  "not-json",
  "null",
  "true",
  "[]",
  "{}",
  '{"access_token":1,"refresh_token":"r"}',
  '{"access_token":"a"}',
])("rejects corrupted storage %s", (value) => {
  localStorage.setItem("delivery360_auth_tokens", value);
  expect(auth.getTokens()).toBeNull();
});
it("storage denial fails closed without making a session active", () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  jest.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() =>
    auth.saveTokens({
      access_token: "a",
      refresh_token: "r",
      token_type: "bearer",
    }),
  ).not.toThrow();
  expect(auth.isSessionActive()).toBe(false);
  expect(() => auth.clearTokens()).not.toThrow();
});
it.each([null, [], true, "string"])(
  "rejects non-object decoded JWT data %#",
  (payload) => expect(auth.decodeToken(token(payload))).toBeNull(),
);
it.each(["bad", "a.bad.c", "a..c"])("rejects malformed JWT %s", (value) =>
  expect(auth.decodeToken(value)).toBeNull(),
);
it("decodes Unicode display claims without claiming signature verification", () =>
  expect(
    auth.decodeToken(token({ name: "José 🚲", exp: Date.now() / 1000 + 1 })),
  ).toMatchObject({ name: "José 🚲" }));
it.each([undefined, null, "4102444800", true, 0])(
  "does not let invalid expiry %s create a session hint",
  (exp) => {
    const t = token({ exp });
    expect(auth.isTokenExpired(t)).toBe(true);
    expect(auth.validateToken(t)).toBe(false);
    if (typeof exp !== "number") expect(auth.needsRefresh(t)).toBe(true);
  },
);
it("treats exact expiry as expired and tests the refresh threshold", () => {
  const now = Date.now() / 1000;
  expect(auth.isTokenExpired(token({ exp: now }))).toBe(true);
  expect(auth.needsRefresh(token({ exp: now + 299 }))).toBe(true);
  expect(auth.needsRefresh(token({ exp: now + 300 }))).toBe(false);
  expect(auth.needsRefresh(valid())).toBe(false);
  expect(auth.validateToken("bad")).toBe(false);
});
it("requires both tokens and exposes only a local session hint", () => {
  expect(auth.validateAuthState(null)).toBe(false);
  expect(
    auth.validateAuthState({
      access_token: valid(),
      refresh_token: "",
      token_type: "bearer",
    }),
  ).toBe(false);
  expect(
    auth.validateAuthState({
      access_token: "bad",
      refresh_token: "r",
      token_type: "bearer",
    }),
  ).toBe(false);
  expect(
    auth.validateAuthState({
      access_token: valid(),
      refresh_token: "r",
      token_type: "bearer",
    }),
  ).toBe(true);
  auth.saveTokens({
    access_token: valid(),
    refresh_token: "r",
    token_type: "bearer",
  });
  expect(auth.isSessionActive()).toBe(true);
  expect(auth.getCurrentUser()).toMatchObject({ id: "user-1" });
});
it("supports the canonical sub and legacy userId without inventing a verified profile", () => {
  expect(auth.getUserFromToken(valid())).toMatchObject({ id: "user-1" });
  expect(
    auth.getUserFromToken(
      token({ userId: "old", exp: Date.now() / 1000 + 100 }),
    ),
  ).toMatchObject({ id: "old" });
  expect(auth.getUserFromToken("bad")).toBeNull();
  expect(auth.getCurrentUser()).toBeNull();
});
it.each([
  ["REPARTIDOR", "OPERADOR", false],
  ["OPERADOR", "REPARTIDOR", true],
  ["GERENTE", "OPERADOR", true],
  ["SUPERADMIN", "GERENTE", true],
  ["GERENTE", "UNKNOWN", false],
  ["UNKNOWN", "UNKNOWN", false],
  ["CLIENTE", "REPARTIDOR", false],
  ["AUDITOR", "OPERADOR", false],
  ["AUDITOR", "AUDITOR", true],
  ["CLIENTE", "CLIENTE", true],
])("bounds local role hints %s/%s", (role, required, expected) =>
  expect(auth.hasRole({ role } as User, required)).toBe(expected),
);
it("requires a user and checks any role without granting unknown scopes", () => {
  expect(auth.hasRole(null, "REPARTIDOR")).toBe(false);
  expect(
    auth.hasAnyRole({ role: "GERENTE" } as User, ["UNKNOWN", "SUPERADMIN"]),
  ).toBe(false);
  expect(
    auth.hasAnyRole({ role: "GERENTE" } as User, ["SUPERADMIN", "OPERADOR"]),
  ).toBe(true);
});
it("calculates remaining expiry without accepting unbounded dates", () => {
  expect(auth.getTokenExpiration(valid())?.getTime()).toBe(
    Date.now() + 3600000,
  );
  expect(auth.getTimeUntilExpiration(valid())).toBe(3600000);
  expect(auth.getTimeUntilExpiration("bad")).toBe(0);
  expect(auth.getTokenExpiration(token({ exp: 1e20 }))).toBeNull();
  expect(auth.createAuthHeader("synthetic")).toEqual({
    Authorization: "Bearer synthetic",
    "Content-Type": "application/json",
  });
});
it.each([
  ["", false],
  ["Abcdef1!", true],
  ["abcdef1!", false],
  ["ABCDEF1!", false],
  ["Abcdefg!", false],
  ["Abcdef12", false],
])("validates the advertised password rules for %s", (value, expected) =>
  expect(auth.validatePassword(value).isValid).toBe(expected),
);
it("generates cryptographic bytes of exactly the requested length", () => {
  jest.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
    (array as Uint8Array).fill(15);
    return array;
  });
  expect(auth.generateSecureToken(3)).toBe("0f0f0f");
  expect(auth.generateSecureToken()).toHaveLength(64);
});
it.each([0, -1, 0.5, 65537])("rejects invalid secure byte length %s", (value) =>
  expect(() => auth.generateSecureToken(value)).toThrow(),
);
it("does not fall back to predictable random values when secure crypto is unavailable", () => {
  const original = globalThis.crypto;
  Object.defineProperty(globalThis, "crypto", {
    value: {},
    configurable: true,
  });
  try {
    expect(() => auth.generateSecureToken()).toThrow("Crypto API");
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      value: original,
      configurable: true,
    });
  }
});
it("clears session state and retires listeners on logout", () => {
  const onLogout = jest.fn(),
    cleanup = auth.setupAuthListeners({ onLogout });
  sessionStorage.setItem("private", "local");
  auth.saveTokens({
    access_token: valid(),
    refresh_token: "r",
    token_type: "bearer",
  });
  auth.logout();
  expect(auth.getTokens()).toBeNull();
  expect(sessionStorage.length).toBe(0);
  expect(onLogout).toHaveBeenCalledTimes(1);
  cleanup();
  window.dispatchEvent(new CustomEvent("auth-logout"));
  expect(onLogout).toHaveBeenCalledTimes(1);
  const other = auth.setupAuthListeners({});
  window.dispatchEvent(new CustomEvent("auth-logout"));
  other();
});
it.each([
  ["user@example.test", true],
  ["bad", false],
  ["x y@a.com", false],
])("checks email shape %s", (value, expected) =>
  expect(auth.isValidEmail(value)).toBe(expected),
);
it("sanitizes display input without treating it as an HTML sanitizer", () => {
  expect(auth.sanitizeInput(" <b>José</b> ")).toBe("bJosé/b");
  expect(auth.sanitizeInput("")).toBe("");
});
it("hashes local display input through the actual Web Crypto API and rejects absent capabilities", async () => {
  const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto"),
    originalEncoder = Object.getOwnPropertyDescriptor(
      globalThis,
      "TextEncoder",
    );
  try {
    Object.defineProperty(globalThis, "crypto", {
      value: {},
      configurable: true,
    });
    await expect(auth.hashPassword("abc")).rejects.toThrow("Crypto API");
    Object.defineProperty(globalThis, "crypto", {
      value: require("crypto").webcrypto,
      configurable: true,
    });
    Object.defineProperty(globalThis, "TextEncoder", {
      value: require("util").TextEncoder,
      configurable: true,
    });
    expect(await auth.hashPassword("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  } finally {
    if (originalCrypto)
      Object.defineProperty(globalThis, "crypto", originalCrypto);
    if (originalEncoder)
      Object.defineProperty(globalThis, "TextEncoder", originalEncoder);
    else delete (globalThis as unknown as Record<string, unknown>).TextEncoder;
  }
});
