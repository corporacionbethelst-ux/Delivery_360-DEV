import { api } from "@/lib/api";
import { userService } from "@/services/user.service";
import { shiftService } from "@/services/shift.service";
import { notificationService } from "@/services/notification.service";
jest.mock("@/lib/api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
  },
}));
const get = jest.mocked(api.get),
  post = jest.mocked(api.post),
  patch = jest.mocked(api.patch),
  remove = jest.mocked(api.delete);
const revision = "a".repeat(64),
  user = {
    id: "u",
    full_name: "José Ana Pérez",
    role: "GERENTE",
    email: "user@example.test",
  },
  input = {
    email: "user@example.test",
    password: "local-only-test-password",
    first_name: "José",
    last_name: "Pérez",
    role: "GERENTE" as const,
  };
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  get.mockResolvedValue([]);
  post.mockResolvedValue(user);
  patch.mockResolvedValue(user);
});
afterEach(() => jest.restoreAllMocks());
it("preserves explicit inactive filtering and normalizes actual user names", async () => {
  get.mockResolvedValueOnce([
    user,
    { ...user, id: "b", full_name: null, first_name: "Ana", last_name: "B" },
    { ...user, id: "c", full_name: null, first_name: "", last_name: "" },
  ]);
  const rows = await userService.getAll({
    role: "GERENTE",
    is_active: false,
    search: "a b",
    limit: 20,
    skip: 0,
    page: 2,
  });
  expect(get).toHaveBeenLastCalledWith(
    "/users?role=GERENTE&is_active=false&search=a+b&limit=20&skip=0&page=2",
  );
  expect(rows[0]).toMatchObject({ first_name: "José", last_name: "Ana Pérez" });
  expect(rows[1].full_name).toBe("Ana B");
  get.mockResolvedValueOnce([]);
  await userService.getAll();
  expect(get).toHaveBeenLastCalledWith("/users");
});
it("uses encoded user paths and revision-guarded edits", async () => {
  get.mockResolvedValueOnce(user);
  expect(await userService.getById("u/a")).toMatchObject({ id: "u" });
  expect(get).toHaveBeenLastCalledWith("/users/u%2Fa");
  await userService.create(input);
  expect(post).toHaveBeenLastCalledWith("/users", input);
  await userService.update("u", {
    first_name: "Name",
    expected_user_revision: revision,
  });
  expect(patch).toHaveBeenLastCalledWith("/users/u", {
    first_name: "Name",
    expected_user_revision: revision,
  });
  await userService.deactivate("u", revision);
  expect(patch).toHaveBeenLastCalledWith("/users/u", {
    is_active: false,
    expected_user_revision: revision,
  });
  await userService.delete("u", revision);
  expect(remove).toHaveBeenLastCalledWith("/users/u", {
    headers: { "If-Match": `"${revision}"` },
  });
  patch.mockResolvedValueOnce({ user });
  expect(await userService.updatePassword("u", "password123")).toMatchObject({
    id: "u",
  });
  expect(patch).toHaveBeenLastCalledWith("/users/u/password", {
    password: "password123",
  });
});
it.each([
  () => userService.getById(""),
  () => userService.getById(1 as never),
  () => userService.create({ ...input, email: "" }),
  () => userService.update("", {}),
  () => userService.update("u", {}),
  () => userService.deactivate(""),
  () => userService.deactivate("u"),
  () => userService.delete(""),
  () => userService.delete("u"),
  () => userService.updatePassword("", "password123"),
  () => userService.updatePassword("u", "short"),
])("rejects unsafe user input before mutation %#", async (call) => {
  await expect(call()).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});
it.each([
  () => userService.getAll(),
  () => userService.getById("u"),
  () => userService.create(input),
  () => userService.update("u", { expected_user_revision: revision }),
  () => userService.deactivate("u", revision),
  () => userService.delete("u", revision),
  () => userService.updatePassword("u", "password123"),
])("preserves user request failure without a fake user %#", async (call) => {
  for (const method of [get, post, patch, remove])
    method.mockRejectedValue(new Error("offline"));
  await expect(call()).rejects.toThrow("offline");
});
it("sends real shift filters and resource verbs", async () => {
  await shiftService.getAll({
    status: "PROGRAMADO",
    rider_id: "r & 1",
    limit: 20,
    date_from: "2026-11-01",
    date_to: "2026-11-08",
  });
  expect(get).toHaveBeenLastCalledWith(
    "/shifts?status=PROGRAMADO&rider_id=r+%26+1&limit=20&date_from=2026-11-01&date_to=2026-11-08",
  );
  await shiftService.getAll();
  expect(get).toHaveBeenLastCalledWith("/shifts");
  await shiftService.getById("s/a");
  expect(get).toHaveBeenLastCalledWith("/shifts/s%2Fa");
  const data = { rider_id: "r", start_time: "2026-11-08T12:00:00Z" };
  await shiftService.create(data);
  expect(post).toHaveBeenLastCalledWith("/shifts", data);
  for (const operation of ["start", "end", "cancel"] as const) {
    await shiftService[operation]("s");
    expect(patch).toHaveBeenLastCalledWith(`/shifts/s/${operation}`);
  }
});
it.each([
  () => shiftService.getById(""),
  () => shiftService.getById(1 as never),
  () => shiftService.create({ rider_id: "r" } as never),
  () => shiftService.start(""),
  () => shiftService.end(""),
  () => shiftService.cancel(""),
])("rejects incomplete shift input %#", async (call) => {
  await expect(call()).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
  expect(patch).not.toHaveBeenCalled();
});
it.each([
  () => shiftService.getAll(),
  () => shiftService.getById("s"),
  () => shiftService.create({ rider_id: "r", start_time: "date" }),
  () => shiftService.start("s"),
  () => shiftService.end("s"),
  () => shiftService.cancel("s"),
])("keeps shift failures distinguishable from empty lists %#", async (call) => {
  for (const method of [get, post, patch])
    method.mockRejectedValue(new Error("offline"));
  await expect(call()).rejects.toThrow("offline");
});
it("maps operational alert identity and unknown read times without fabricating an inbox event", async () => {
  get.mockResolvedValueOnce([
    {
      id: "a",
      type: "",
      status: "READ",
      isRead: false,
      title: "Actual alert",
      description: "Alert description",
      createdAt: "2026-11-01T12:00Z",
      orderId: "o",
      riderId: "r",
    },
    {
      id: "b",
      type: "WARNING",
      status: "UNREAD",
      isRead: true,
      title: "Actual alert",
      description: "Alert description",
      createdAt: "2026-11-01T12:00Z",
      riderId: "r",
    },
    { id: "c", type: "INFO", status: "UNREAD", isRead: false },
  ]);
  const rows = await notificationService.getAll({ limit: 10, status: "LEIDO" });
  expect(get).toHaveBeenLastCalledWith("/alerts?limit=10&status=READ");
  expect(rows[0]).toMatchObject({
    type: "OPERATIONAL",
    status: "LEIDO",
    related_entity_id: "o",
    read_at: null,
  });
  expect(rows[1]).toMatchObject({
    status: "LEIDO",
    related_entity_id: "r",
    read_at: null,
  });
  expect(rows[2]).toMatchObject({
    status: "NO_LEIDO",
    related_entity_id: null,
  });
  await notificationService.getAll({ status: "NO_LEIDO" });
  expect(get).toHaveBeenLastCalledWith("/alerts?status=UNREAD");
  await notificationService.getAll();
  expect(get).toHaveBeenLastCalledWith("/alerts");
});
it("marks only the addressed alert and exposes a bounded unread count", async () => {
  const result = await notificationService.markAsRead("a/b");
  expect(patch).toHaveBeenLastCalledWith("/alerts/a%2Fb/read");
  expect(result.status).toBe("LEIDO");
  await notificationService.markAllAsRead();
  expect(post).toHaveBeenLastCalledWith("/alerts/read-all");
  get.mockResolvedValueOnce([{ id: "a" }]);
  expect(await notificationService.getUnreadCount()).toEqual({ count: 1 });
  expect(get).toHaveBeenLastCalledWith("/alerts?status=UNREAD&limit=200");
  await expect(notificationService.markAsRead("")).rejects.toThrow();
});
it.each([
  () => notificationService.getAll(),
  () => notificationService.markAsRead("a"),
  () => notificationService.markAllAsRead(),
  () => notificationService.getUnreadCount(),
])("does not turn alert outages into a successful zero %#", async (call) => {
  for (const method of [get, post, patch])
    method.mockRejectedValue(new Error("offline"));
  await expect(call()).rejects.toThrow("offline");
});
