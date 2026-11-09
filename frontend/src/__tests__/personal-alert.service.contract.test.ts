import { alertService, validatePersonalAlert } from "@/services/alert.service";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn(), delete: jest.fn() },
}));
const http = jest.mocked(api);
const row = {
  id: "alert-1",
  type: "SLA_WARNING",
  severity: "HIGH",
  title: "Aviso",
  description: "Revisar entrega",
  createdAt: "",
  isRead: false,
  isDismissed: false,
  status: "UNREAD",
  orderId: null,
  riderId: null,
};
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  http.get.mockResolvedValue([row]);
});
it("serializa estado, lookahead y offset cero sin falsificar el total", async () => {
  await expect(
    alertService.getAll({ status: "UNREAD", limit: 51, offset: 0 }),
  ).resolves.toEqual([row]);
  expect(http.get).toHaveBeenCalledWith(
    "/alerts?status=UNREAD&limit=51&offset=0",
  );
});
it("conserva las llamadas de consumidores anteriores sin offset", async () => {
  await alertService.getAll({ status: "ALL", limit: 100 });
  expect(http.get).toHaveBeenCalledWith("/alerts?limit=100");
  await alertService.getAll();
  expect(http.get).toHaveBeenLastCalledWith("/alerts");
});
it.each([
  { limit: 0 },
  { limit: 201 },
  { limit: 1.5 },
  { limit: NaN },
  { offset: -1 },
  { offset: 0.5 },
  { offset: Number.MAX_SAFE_INTEGER + 1 },
  { status: "WRONG" },
])("rechaza filtros inválidos %p antes del transporte", async (filters) => {
  await expect(alertService.getAll(filters as any)).rejects.toThrow(/filtros/);
  expect(http.get).not.toHaveBeenCalled();
});
it.each([null, {}, { data: [] }, "invalid"])(
  "un cuerpo %p no se convierte en bandeja vacía",
  async (body) => {
    http.get.mockResolvedValue(body as any);
    await expect(alertService.getAll()).rejects.toThrow(/Respuesta/);
  },
);
it("una respuesta vacía real se conserva como resultado confirmado", async () => {
  http.get.mockResolvedValue([]);
  await expect(alertService.getAll()).resolves.toEqual([]);
});
it.each([
  { id: "" },
  { isRead: null },
  { isDismissed: undefined },
  { status: "READ" },
  { title: null },
  { description: 7 },
  { createdAt: null },
  { orderId: {} },
  { riderId: "" },
])("rechaza una alerta incoherente %p", (patch) => {
  expect(() => validatePersonalAlert({ ...row, ...patch })).toThrow(
    /incoherentes/,
  );
});
it("preserva tipos y severidades desconocidos y fechas no informadas sin valores por defecto", () => {
  expect(
    validatePersonalAlert({
      ...row,
      type: "CUSTOM",
      severity: "CUSTOM",
      createdAt: "",
    }),
  ).toMatchObject({ type: "CUSTOM", severity: "CUSTOM", createdAt: "" });
});
it("rechaza identidades duplicadas y páginas que exceden el límite", async () => {
  http.get.mockResolvedValue([row, row]);
  await expect(alertService.getAll()).rejects.toThrow(/consulta/);
  http.get.mockResolvedValue([row, { ...row, id: "second" }]);
  await expect(alertService.getAll({ limit: 1 })).rejects.toThrow(/Respuesta/);
});
it("rechaza un estado que no coincide con la consulta filtrada", async () => {
  await expect(alertService.getAll({ status: "READ" })).rejects.toThrow(
    /consulta/,
  );
});
it("el resultado es un snapshot propio y no modifica objetos del cliente HTTP", async () => {
  const result = await alertService.getAll();
  expect(result[0]).not.toBe(row);
  result[0].title = "Changed";
  expect(row.title).toBe("Aviso");
});
it("codifica IDs completos en lectura individual y descarte", async () => {
  http.patch.mockResolvedValue({ id: "id/with spaces" });
  http.delete.mockResolvedValue({ id: "id/with spaces" });
  await alertService.markAsRead("id/with spaces");
  expect(http.patch).toHaveBeenCalledWith("/alerts/id%2Fwith%20spaces/read");
  await alertService.dismiss("id/with spaces");
  expect(http.delete).toHaveBeenCalledWith("/alerts/id%2Fwith%20spaces");
});
it.each(["read", "dismiss"])(
  "el acuse de %s debe identificar la alerta solicitada",
  async (kind) => {
    http.patch.mockResolvedValue({ id: "other" });
    http.delete.mockResolvedValue({ id: "other" });
    await expect(
      kind === "read"
        ? alertService.markAsRead("requested")
        : alertService.dismiss("requested"),
    ).rejects.toThrow(/confirmar/);
  },
);
it.each(["", "   "])("no emite acciones para un ID vacío %p", async (id) => {
  await expect(alertService.markAsRead(id)).rejects.toThrow(/ID/);
  await expect(alertService.dismiss(id)).rejects.toThrow(/ID/);
  expect(http.patch).not.toHaveBeenCalled();
  expect(http.delete).not.toHaveBeenCalled();
});
it.each([0, 57])(
  "lectura global conserva el contador real %s",
  async (count) => {
    http.post.mockResolvedValue({ count, message: "OK" });
    await expect(alertService.markAllAsRead()).resolves.toEqual({ count });
    expect(http.post).toHaveBeenCalledWith("/alerts/read-all");
  },
);
it.each([undefined, -1, 1.5, "50", NaN])(
  "no fabrica un resultado global para el contador %p",
  async (count) => {
    http.post.mockResolvedValue({ count });
    await expect(alertService.markAllAsRead()).rejects.toThrow(/confirmar/);
  },
);
it.each(["get", "read", "dismiss", "all"])(
  "una respuesta %s retirada no se publica en otra sesión",
  async (kind) => {
    let resolve!: (value: any) => void;
    const pending = new Promise<any>((done) => {
      resolve = done;
    });
    http.get.mockReturnValue(pending);
    http.patch.mockReturnValue(pending);
    http.delete.mockReturnValue(pending);
    http.post.mockReturnValue(pending);
    const request =
      kind === "get"
        ? alertService.getAll()
        : kind === "read"
          ? alertService.markAsRead("id")
          : kind === "dismiss"
            ? alertService.dismiss("id")
            : alertService.markAllAsRead();
    storeTokens({
      access_token: "other-token",
      refresh_token: "other-refresh",
    });
    resolve(kind === "get" ? [row] : { count: 1 });
    await expect(request).rejects.toThrow(/sesión cambió/);
  },
);
