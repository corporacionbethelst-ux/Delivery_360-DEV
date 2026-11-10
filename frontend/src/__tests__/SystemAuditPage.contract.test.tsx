import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/admin/audit/page";
import { auditService, type AuditLog } from "@/services/audit.service";
import { AUDIT_CSV_HEADER } from "@/lib/system-audit";
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
jest.mock("@/services/audit.service", () => ({
  auditService: {
    getLogs: jest.fn(),
    getSummary: jest.fn(),
    getById: jest.fn(),
    exportCsv: jest.fn(),
  },
}));
const service = jest.mocked(auditService),
  row: AuditLog = {
    id: "event-83",
    action: "UPDATE",
    status: "SUCCESS",
    success: true,
    user_id: "actor",
    user_role: "GERENTE",
    description: "Evento de prueba",
    resource_type: "User",
    resource_id: "account",
    created_at: "2026-11-09T12:00:00Z",
    old_values: { is_active: true },
    new_values: { is_active: false },
    status_code: 0,
  };
const result = { items: [row], total: 1, limit: 50, offset: 0 },
  summary = {
    total: 3,
    period_days: 7,
    period_start: "2026-11-02T12:00:00Z",
    by_action: { UPDATE: 3 },
    by_success: { True: 0, False: 3 },
  };
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  jest.resetAllMocks();
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getLogs.mockResolvedValue(result);
  service.getSummary.mockResolvedValue(summary);
  service.getById.mockResolvedValue(row);
  service.exportCsv.mockResolvedValue(AUDIT_CSV_HEADER + "\r\n");
  URL.createObjectURL = jest.fn(() => "blob:audit-83");
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  jest.restoreAllMocks();
});
const table = () => screen.getByRole("region", { name: "Tabla de auditoría" });
async function loaded() {
  await screen.findByRole("button", {
    name: `Ver detalle del evento ${row.id}`,
  });
}
const apply = () =>
  fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
async function exportDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Exportar CSV" }));
  return screen.findByRole("dialog", { name: "Exportar auditoría" });
}

it.each(["OPERADOR", "REPARTIDOR", "CLIENTE", "AUDITOR"])(
  "blocks %s before any administrative read",
  (role) => {
    mockUser = { id: "denied", role };
    render(<Page />);
    expect(service.getLogs).not.toHaveBeenCalled();
    expect(service.getSummary).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("does not query while authentication is unconfirmed", () => {
  mockAuthenticated = false;
  mockUser = null;
  render(<Page />);
  expect(service.getLogs).not.toHaveBeenCalled();
});
it.each(["GERENTE", "SUPERADMIN"])(
  "loads %s with independent summary scope and real zero values",
  async (role) => {
    mockUser = { id: "manager", role };
    render(<Page />);
    await loaded();
    expect(service.getLogs).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(service.getSummary).toHaveBeenCalledWith(7);
    expect(within(table()).getByText("HTTP 0")).toBeInTheDocument();
    const global = screen.getByRole("region", {
      name: "Resumen global de auditoría",
    });
    expect(within(global).getByText("0")).toBeInTheDocument();
    expect(global).toHaveTextContent("independiente");
  },
);
it("keeps edits local until explicit apply and blocks export of an unapplied draft", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Buscar en la auditoría"), {
    target: { value: "José" },
  });
  expect(service.getLogs).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Hay cambios sin aplicar/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Exportar CSV" })).toBeDisabled();
  apply();
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith({
      limit: 50,
      offset: 0,
      search: "José",
    }),
  );
  expect(service.getSummary).toHaveBeenCalledTimes(1);
});
it("applies server result, action, resource, user and complete Caracas date filters", async () => {
  render(<Page />);
  await loaded();
  for (const [label, value] of [
    ["Acción registrada", "UPDATE"],
    ["Resultado del evento", "FAILURE"],
    ["Tipo de recurso", "User"],
    ["ID de recurso", "one"],
    ["ID de usuario (UUID)", "123e4567-e89b-42d3-a456-000000000083"],
    ["Desde (Caracas)", "2026-11-09"],
    ["Hasta (Caracas)", "2026-11-09"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  apply();
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({
        limit: 50,
        offset: 0,
        action: "UPDATE",
        status: "FAILURE",
        resource_type: "User",
        resource_id: "one",
        user_id: "123e4567-e89b-42d3-a456-000000000083",
        date_from: "2026-11-09T04:00:00.000Z",
        date_to: "2026-11-10T03:59:59.999999Z",
      }),
    ),
  );
});
it.each(["dates", "user"])(
  "rejects an invalid %s draft without HTTP",
  async (kind) => {
    render(<Page />);
    await loaded();
    if (kind === "dates") {
      fireEvent.change(screen.getByLabelText("Desde (Caracas)"), {
        target: { value: "2026-11-10" },
      });
      fireEvent.change(screen.getByLabelText("Hasta (Caracas)"), {
        target: { value: "2026-11-09" },
      });
    } else
      fireEvent.change(screen.getByLabelText("ID de usuario (UUID)"), {
        target: { value: "invalid" },
      });
    apply();
    expect(screen.getByRole("alert")).toHaveTextContent(
      kind === "dates" ? "posterior" : "UUID",
    );
    expect(service.getLogs).toHaveBeenCalledTimes(1);
  },
);
it("clears all filters and starts over at offset zero", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Buscar en la auditoría"), {
    target: { value: "x" },
  });
  apply();
  await waitFor(() => expect(service.getLogs).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith({ limit: 50, offset: 0 }),
  );
  expect(screen.getByLabelText("Buscar en la auditoría")).toHaveValue("");
});
it("does not confuse an initial read error with an empty table or zero total", async () => {
  service.getLogs.mockRejectedValueOnce(new Error("network"));
  render(<Page />);
  expect(
    await screen.findByText(/No se pudo confirmar la consulta/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Eventos de la consulta confirmada" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(/No se encontraron eventos/),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Exportar CSV" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar eventos" }));
  await loaded();
});
it("preserves the last query and records when a newly applied filter fails and retries that exact filter", async () => {
  render(<Page />);
  await loaded();
  const before = screen.getByText(/Consulta confirmada:/).textContent;
  service.getLogs.mockRejectedValueOnce(new Error("network"));
  fireEvent.change(screen.getByLabelText("Buscar en la auditoría"), {
    target: { value: "new" },
  });
  apply();
  await screen.findByText(/No se pudo confirmar la consulta/);
  expect(screen.getByText(/Consulta confirmada:/).textContent).toBe(before);
  expect(table()).toHaveTextContent("Evento de prueba");
  expect(screen.getByRole("button", { name: "Exportar CSV" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar eventos" }));
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith({
      limit: 50,
      offset: 0,
      search: "new",
    }),
  );
  await screen.findByText(/búsqueda «new»/);
});
it("an old query finishing late cannot replace the latest result", async () => {
  const old = deferred<typeof result>();
  service.getLogs.mockReturnValueOnce(old.promise);
  render(<Page />);
  service.getLogs.mockResolvedValue({
    ...result,
    items: [{ ...row, id: "new-event", description: "Latest" }],
  });
  fireEvent.change(screen.getByLabelText("Buscar en la auditoría"), {
    target: { value: "latest" },
  });
  apply();
  await screen.findByText("Latest");
  await act(async () => old.resolve(result));
  expect(screen.queryByText("Evento de prueba")).not.toBeInTheDocument();
  expect(table()).toHaveTextContent("Latest");
});
it("summary errors do not hide confirmed events and summary retry is independent", async () => {
  service.getSummary.mockRejectedValueOnce(new Error("summary"));
  render(<Page />);
  await loaded();
  await screen.findByText(/No se pudo actualizar el resumen/);
  expect(table()).toHaveTextContent("Evento de prueba");
  fireEvent.click(screen.getByRole("button", { name: "Reintentar resumen" }));
  await waitFor(() => expect(service.getSummary).toHaveBeenCalledTimes(2));
  expect(service.getLogs).toHaveBeenCalledTimes(1);
});
it("retains the last summary snapshot on refresh failure", async () => {
  render(<Page />);
  await loaded();
  await screen.findByText("Eventos del período global");
  const before = screen.getByText(/Resumen confirmado:/).textContent;
  service.getSummary.mockRejectedValueOnce(new Error("summary"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar auditoría" }));
  await screen.findByText(/No se pudo actualizar el resumen/);
  expect(screen.getByText(/Resumen confirmado:/).textContent).toBe(before);
});
it("paginates with confirmed total and preserves filters", async () => {
  service.getLogs.mockResolvedValueOnce({ ...result, total: 51 });
  render(<Page />);
  await loaded();
  service.getLogs.mockResolvedValueOnce({ ...result, total: 51, offset: 50 });
  fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith({ limit: 50, offset: 50 }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Página siguiente" }),
    ).toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
  await waitFor(() =>
    expect(service.getLogs).toHaveBeenLastCalledWith({ limit: 50, offset: 0 }),
  );
});
it("explains a page that became empty without presenting the entire query as empty", async () => {
  service.getLogs.mockResolvedValueOnce({ ...result, total: 51 });
  render(<Page />);
  await loaded();
  service.getLogs.mockResolvedValueOnce({
    items: [],
    total: 10,
    limit: 50,
    offset: 50,
  });
  fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
  await screen.findByText(/Esta página ya no contiene eventos/);
  expect(screen.getByRole("button", { name: "Página anterior" })).toBeEnabled();
});
it("unknown statuses and missing dates stay explicit and are safe React text", async () => {
  service.getLogs.mockResolvedValue({
    ...result,
    items: [
      { ...row, status: "__proto__", action: "FUTURE", created_at: "invalid" },
    ],
  });
  render(<Page />);
  await loaded();
  expect(table()).toHaveTextContent("__proto__");
  expect(table()).toHaveTextContent("Fecha no disponible");
});
it("loads the exact original event on demand with values, source and literal markup", async () => {
  service.getById.mockResolvedValue({
    ...row,
    description: "<script>alert('x')</script>",
    contains_personal_data: true,
  });
  render(<Page />);
  await loaded();
  expect(service.getById).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: `Ver detalle del evento ${row.id}` }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Detalle del evento",
  });
  await within(dialog).findByText("<script>alert('x')</script>");
  expect(dialog.querySelector("script")).toBeNull();
  expect(service.getById).toHaveBeenCalledWith(row.id);
  expect(within(dialog).getByLabelText("Valores anteriores")).toHaveTextContent(
    '"is_active": true',
  );
  expect(within(dialog).getByLabelText("Valores nuevos")).toHaveTextContent(
    '"is_active": false',
  );
});
it("detail failure offers an exact retry and does not substitute list values for an unconfirmed detail", async () => {
  service.getById.mockRejectedValueOnce(new Error("detail"));
  render(<Page />);
  await loaded();
  fireEvent.click(
    screen.getByRole("button", { name: `Ver detalle del evento ${row.id}` }),
  );
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText(/No se pudo confirmar el detalle/);
  expect(
    within(dialog).queryByLabelText("Valores anteriores"),
  ).not.toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Reintentar detalle" }),
  );
  await within(dialog).findByLabelText("Valores anteriores");
  expect(service.getById).toHaveBeenNthCalledWith(2, row.id);
});
it("closing a pending detail retires its late result", async () => {
  const pending = deferred<AuditLog>();
  service.getById.mockReturnValueOnce(pending.promise);
  render(<Page />);
  await loaded();
  fireEvent.click(
    screen.getByRole("button", { name: `Ver detalle del evento ${row.id}` }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Cerrar detalle" }),
  );
  await act(async () => pending.resolve(row));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("export requires confirmation with full-query scope and can be cancelled", async () => {
  service.getLogs.mockResolvedValue({ ...result, total: 6000 });
  render(<Page />);
  await loaded();
  const dialog = await exportDialog();
  expect(dialog).toHaveTextContent("5000");
  expect(dialog).toHaveTextContent("otras páginas");
  expect(dialog).toHaveTextContent("supera el límite");
  expect(service.exportCsv).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(service.exportCsv).not.toHaveBeenCalled();
});
it("export uses the captured filters, locks duplicate requests and closing, and releases its Blob on unmount", async () => {
  const pending = deferred<string>();
  service.exportCsv.mockReturnValueOnce(pending.promise);
  const view = render(<Page />);
  await loaded();
  const dialog = await exportDialog(),
    confirm = within(dialog).getByRole("button", { name: "Descargar CSV" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  expect(service.exportCsv).toHaveBeenCalledTimes(1);
  expect(service.exportCsv).toHaveBeenCalledWith({ limit: 5000, offset: 0 });
  expect(
    within(dialog).getByRole("button", { name: "Cancelar" }),
  ).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByLabelText("Buscar en la auditoría")).toBeDisabled();
  await act(async () => pending.resolve(AUDIT_CSV_HEADER + "\r\n"));
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  expect(document.querySelector("a[download]")).toBeNull();
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:audit-83");
});
it("a failed CSV stays in the confirmation for an explicit retry", async () => {
  service.exportCsv.mockRejectedValueOnce(new Error("CSV"));
  render(<Page />);
  await loaded();
  const dialog = await exportDialog();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Descargar CSV" }),
  );
  await within(dialog).findByText(/No se pudo descargar el CSV/);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(
    within(dialog).getByRole("button", { name: "Descargar CSV" }),
  ).toBeEnabled();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Descargar CSV" }),
  );
  await screen.findByText(/Se inició la descarga/);
  expect(service.exportCsv).toHaveBeenCalledTimes(2);
});
it.each(["account", "credentials"])(
  "an export response from a retired %s cannot download a file",
  async (kind) => {
    const pending = deferred<string>();
    service.exportCsv.mockReturnValueOnce(pending.promise);
    const view = render(<Page />);
    await loaded();
    const dialog = await exportDialog();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Descargar CSV" }),
    );
    if (kind === "account") {
      mockUser = { id: "another-manager", role: "GERENTE" };
      view.rerender(<Page />);
    } else
      act(() =>
        storeTokens({
          access_token: "audit83-credentials",
          refresh_token: "audit83-refresh",
        }),
      );
    await act(async () => pending.resolve(AUDIT_CSV_HEADER + "\r\n"));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);
it("a pending list from the previous account cannot populate the next account", async () => {
  const pending = deferred<typeof result>();
  service.getLogs.mockReturnValueOnce(pending.promise);
  const view = render(<Page />);
  mockUser = { id: "other", role: "GERENTE" };
  service.getLogs.mockResolvedValue({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
  view.rerender(<Page />);
  await screen.findByText(
    /No se encontraron eventos en la consulta confirmada/,
  );
  await act(async () => pending.resolve(result));
  expect(
    screen.queryByRole("region", { name: "Tabla de auditoría" }),
  ).not.toBeInTheDocument();
});
