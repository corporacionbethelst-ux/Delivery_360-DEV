import { api } from "@/lib/api";
import { authService as auth } from "@/services/auth.service";
import { AxiosError } from "axios";
import {
  clearStoredTokens,
  storeTokens,
  SessionChangedError,
} from "@/lib/auth-session";
jest.mock("@/lib/api", () => ({
  api: { post: jest.fn(), get: jest.fn(), put: jest.fn() },
  getStoredTokens: () => ({ accessToken: "captured-token" }),
}));
const post = jest.mocked(api.post),
  get = jest.mocked(api.get),
  put = jest.mocked(api.put);
const originalFetch = globalThis.fetch;
const data = {
  first_name: "Ana",
  last_name: "Local",
  email: "local@example.test",
  password: "local-test-password",
  phone: "123",
  vehicle_type: "MOTO",
  vehicle_plate: "ABC123",
};
const files = () =>
  Object.fromEntries(
    [
      "license_file",
      "id_card_file",
      "vehicle_registration_file",
      "insurance_file",
    ].map((field) => [
      field,
      new File(["%PDF-1.4"], field + ".pdf", { type: "application/pdf" }),
    ]),
  );
const failure = (status: number, body: unknown) => {
  const error = new AxiosError("failure");
  error.response = {
    status,
    statusText: "Failure",
    data: body,
    headers: {},
    config: {} as never,
  };
  return error;
};
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  storeTokens({ access_token: "a", refresh_token: "ra" });
  post.mockResolvedValue({ access_token: "test" });
  globalThis.fetch = jest.fn(async () => ({ ok: true }) as Response);
});
afterEach(() => {
  clearStoredTokens();
  jest.restoreAllMocks();
  globalThis.fetch = originalFetch;
});
it("uses an encoded OAuth form and does not log a request containing credentials", async () => {
  await auth.login("a+b@example.test", "p&=test");
  const args = post.mock.calls[0];
  expect(args[0]).toBe("/auth/login");
  expect((args[1] as URLSearchParams).get("password")).toBe("p&=test");
  expect(args[2]).toMatchObject({
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  expect(console.error).not.toHaveBeenCalled();
});
it.each([
  { detail: "Rejected" },
  { message: "Rejected" },
  { detail: [{ loc: ["body", "email"], msg: "Rejected" }] },
])("reads supported login failure shapes %#", async (body) => {
  post.mockRejectedValueOnce(failure(400, body));
  await expect(auth.login("a", "b")).rejects.toThrow("Rejected");
});
it("preserves retired-session errors and rejects null failures safely", async () => {
  const changed = new SessionChangedError();
  post.mockRejectedValueOnce(changed);
  await expect(auth.login("a", "b")).rejects.toBe(changed);
  post.mockRejectedValueOnce(null);
  await expect(auth.login("a", "b")).rejects.toThrow("Credenciales");
});
it("constructs multipart metadata with all real files and supports prebuilt FormData", async () => {
  await auth.register({ ...data, ...files() } as never);
  const form = post.mock.calls[0][1] as FormData;
  expect(form.get("email")).toBe(data.email);
  expect(form.get("vehicle_type")).toBe("MOTO");
  expect(form.get("insurance_file")).toBeInstanceOf(File);
  post.mockClear();
  await auth.register(form);
  expect(post.mock.calls[0][1]).toBe(form);
});
it("requires all four selected documents before network activity", async () => {
  await expect(auth.register(data)).rejects.toThrow("cuatro");
  expect(post).not.toHaveBeenCalled();
  const form = new FormData();
  for (const [name, file] of Object.entries(files())) form.set(name, file);
  form.set(
    "insurance_file",
    new File([], "empty.pdf", { type: "application/pdf" }),
  );
  await expect(auth.register(form)).rejects.toThrow("vacío");
  expect(post).not.toHaveBeenCalled();
});
it("handles registration errors without logging submitted fields or resetting another session", async () => {
  post.mockRejectedValueOnce(
    failure(422, { detail: [{ loc: ["body", "email"], msg: "Invalid" }] }),
  );
  await expect(auth.register({ ...data, ...files() } as never)).rejects.toThrow(
    "Invalid",
  );
  expect(console.error).toHaveBeenCalledWith("Error en registro de usuario");
  post.mockRejectedValueOnce(new SessionChangedError());
  await expect(
    auth.register({ ...data, ...files() } as never),
  ).rejects.toBeInstanceOf(SessionChangedError);
  post.mockRejectedValueOnce(null);
  await expect(auth.register({ ...data, ...files() } as never)).rejects.toThrow(
    "Error al registrar",
  );
});
it("falls back to users/me only for an actual 404 compatibility response", async () => {
  get
    .mockRejectedValueOnce(failure(404, {}))
    .mockResolvedValueOnce({ id: "u" });
  expect(await auth.getProfile()).toEqual({ id: "u" });
  expect(get.mock.calls).toEqual([["/auth/me"], ["/users/me"]]);
  get.mockRejectedValueOnce(failure(503, {}));
  await expect(auth.getProfile()).rejects.toBeInstanceOf(AxiosError);
});
it("uses a captured bearer for best-effort logout and clears its timeout", async () => {
  jest.useFakeTimers();
  await auth.logout("captured");
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/auth/logout"),
    expect.objectContaining({
      headers: { Authorization: "Bearer captured" },
      keepalive: true,
    }),
  );
  expect(jest.getTimerCount()).toBe(0);
  (fetch as jest.Mock).mockRejectedValueOnce(new Error("offline"));
  await expect(auth.logout()).resolves.toBeUndefined();
  (fetch as jest.Mock).mockClear();
  await auth.logout(null);
  expect(fetch).not.toHaveBeenCalled();
  jest.useRealTimers();
});
it("passes optimistic profile revisions and password changes to real endpoints", async () => {
  const revision = "a".repeat(64);
  await auth.updateProfile({ expected_user_revision: revision, phone: "123" });
  expect(put).toHaveBeenCalledWith("/users/me", {
    expected_user_revision: revision,
    phone: "123",
  });
  await expect(auth.updateProfile({ phone: "123" })).rejects.toThrow();
  await auth.changePassword("current", "new-local-password");
  expect(post).toHaveBeenLastCalledWith("/auth/change-password", {
    current_password: "current",
    new_password: "new-local-password",
  });
  await auth.resetPassword("reset-token", "new-local-password");
  expect(post).toHaveBeenLastCalledWith("/auth/reset-password", {
    token: "reset-token",
    new_password: "new-local-password",
  });
});
it.each([400, 404])(
  "does not enumerate accounts through recovery response %s",
  async (status) => {
    post.mockRejectedValueOnce(failure(status, {}));
    expect(await auth.forgotPassword("local@example.test")).toEqual({
      message: "Si el correo existe, recibirás instrucciones.",
    });
  },
);
it("preserves recovery outages rather than reporting a sent email", async () => {
  post.mockRejectedValueOnce(new Error("offline"));
  await expect(auth.forgotPassword("a")).rejects.toThrow("offline");
});
