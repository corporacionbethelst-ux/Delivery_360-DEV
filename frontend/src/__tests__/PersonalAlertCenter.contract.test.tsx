import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import ManagerPage from "@/app/(dashboard)/manager/operations/alerts/page";
import OperatorPage from "@/app/(dashboard)/operator/alerts/page";
import { alertService, type Alert } from "@/services/alert.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

let mockUser: { id: string; role: string } | null = {
    id: "manager",
    role: "GERENTE",
  },
  mockAuthenticated = true;
const mockRouter = { replace: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/services/alert.service", () => ({
  alertService: {
    getAll: jest.fn(),
    markAsRead: jest.fn(),
    markAllAsRead: jest.fn(),
    dismiss: jest.fn(),
  },
}));
const service = jest.mocked(alertService);
const row: Alert = {
  id: "alert-a",
  type: "SLA_WARNING",
  severity: "HIGH",
  title: "José requiere atención",
  description: "Entrega retrasada",
  createdAt: "2026-11-08T12:00:00",
  isRead: false,
  isDismissed: false,
  status: "UNREAD",
  orderId: "order/a",
  riderId: "rider/a",
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
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getAll.mockResolvedValue([row]);
  service.markAllAsRead.mockResolvedValue({ count: 57 });
});
afterEach(() => {
  jest.restoreAllMocks();
});
const article = () => screen.findByRole("article", { name: "Alerta alert-a" });
const refresh = () => screen.getByRole("button", { name: "Actualizar" });
const confirm = () => screen.getByRole("button", { name: "Confirmar" });

it.each(["GERENTE", "SUPERADMIN", "OPERADOR"])(
  "consulta personal permitida para %s",
  async (role) => {
    mockUser = { id: "staff", role };
    render(<ManagerPage />);
    await article();
    expect(service.getAll).toHaveBeenCalledWith({
      status: "ALL",
      limit: 51,
      offset: 0,
    });
  },
);
it.each(["CLIENTE", "REPARTIDOR", "AUDITOR"])(
  "deniega %s sin montar lecturas",
  (role) => {
    mockUser = { id: "other", role };
    render(<ManagerPage />);
    expect(service.getAll).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("sin sesión no consulta alertas privadas", () => {
  mockUser = null;
  mockAuthenticated = false;
  render(<ManagerPage />);
  expect(service.getAll).not.toHaveBeenCalled();
});
it.each([
  [ManagerPage, "/manager", "/manager/operations/orders/order%2Fa"],
  [OperatorPage, "/operator", "/operator/orders/order%2Fa"],
] as const)("conserva navegación por modo", async (Page, home, order) => {
  render(<Page />);
  const card = await article();
  expect(screen.getByRole("link", { name: "Volver al panel" })).toHaveAttribute(
    "href",
    home,
  );
  expect(
    within(card).getByRole("link", { name: "Orden: order/a" }),
  ).toHaveAttribute("href", order);
  expect(
    within(card).getByRole("link", { name: "Repartidor: rider/a" }),
  ).toHaveAttribute("href", "/manager/fleet/riders/rider%2Fa");
});
it("búsqueda con tildes y severidad son locales y no ocultan su alcance", async () => {
  service.getAll.mockResolvedValue([
    row,
    { ...row, id: "other", title: "Otro aviso", severity: "LOW" },
  ]);
  render(<ManagerPage />);
  await article();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Buscar en esta página" }),
    { target: { value: "JOSE" } },
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Severidad en esta página" }),
    { target: { value: "LOW" } },
  );
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  expect(screen.getByText(/No hay coincidencias en esta página/)).toBeVisible();
  expect(service.getAll).toHaveBeenCalledTimes(1);
  expect(
    screen.getByText(/El servidor no informa un total global/),
  ).toBeVisible();
});
it("tipos, severidades y fechas desconocidas no se convierten en valores favorables", async () => {
  service.getAll.mockResolvedValue([
    {
      ...row,
      type: "CUSTOM",
      severity: "UNKNOWN",
      createdAt: "invalid",
      title: "",
      description: "",
    } as unknown as Alert,
  ]);
  render(<ManagerPage />);
  const card = await article();
  expect(within(card).getByText("UNKNOWN")).toBeVisible();
  expect(within(card).getByText("CUSTOM")).toBeVisible();
  expect(within(card).getByText("Título no informado")).toBeVisible();
  expect(within(card).getByText("Creada: Fecha no disponible")).toBeVisible();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Severidad en esta página" }),
    { target: { value: "UNKNOWN" } },
  );
  expect(card).toBeVisible();
});
it("fechas futuras se muestran con su fecha real, sin Justo ahora", async () => {
  service.getAll.mockResolvedValue([
    { ...row, createdAt: "2099-11-08T12:00:00" },
  ]);
  render(<ManagerPage />);
  await article();
  expect(screen.getByText(/Creada:.*2099/)).toBeVisible();
  expect(screen.queryByText(/Justo ahora/)).not.toBeInTheDocument();
});
it("un fallo inicial no se presenta como vacío o consulta confirmada", async () => {
  service.getAll.mockRejectedValueOnce(new Error("network"));
  render(<ManagerPage />);
  await screen.findByRole("alert");
  expect(
    screen.queryByText(/La página consultada no contiene/),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/Consulta confirmada:/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Leer todas mis alertas" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await article();
});
it("vacío confirmado se limita a la página, no declara el sistema sin incidencias", async () => {
  service.getAll.mockResolvedValue([]);
  render(<ManagerPage />);
  await screen.findByText("La página consultada no contiene alertas visibles.");
  expect(
    screen.queryByText(/Todo limpio|sistema no ha generado/),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Página siguiente" }),
  ).toBeDisabled();
});
it("un fallo de refresco conserva tarjetas y fecha confirmadas", async () => {
  render(<ManagerPage />);
  await article();
  const before = screen.getByText(/Consulta confirmada:/).textContent;
  service.getAll.mockRejectedValueOnce(new Error("refresh"));
  fireEvent.click(refresh());
  await screen.findByRole("alert");
  expect(await article()).toBeVisible();
  expect(screen.getByText(/Consulta confirmada:/).textContent).toBe(before);
  expect(
    screen.getByRole("button", { name: "Marcar como leída" }),
  ).toBeDisabled();
});
it("lookahead muestra 50 y permite consultar la página siguiente desde offset 50", async () => {
  service.getAll
    .mockResolvedValueOnce(
      Array.from({ length: 51 }, (_, index) => ({
        ...row,
        id: `alert-${index}`,
      })),
    )
    .mockResolvedValueOnce([{ ...row, id: "last" }]);
  render(<ManagerPage />);
  await screen.findByRole("article", { name: "Alerta alert-0" });
  expect(screen.getAllByRole("article")).toHaveLength(50);
  expect(
    screen.queryByRole("article", { name: "Alerta alert-50" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
  await screen.findByRole("article", { name: "Alerta last" });
  expect(service.getAll).toHaveBeenLastCalledWith({
    status: "ALL",
    limit: 51,
    offset: 50,
  });
  expect(
    screen.getByRole("button", { name: "Página siguiente" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
  await waitFor(() =>
    expect(service.getAll).toHaveBeenLastCalledWith({
      status: "ALL",
      limit: 51,
      offset: 0,
    }),
  );
});
it("respuestas de filtros anteriores no reemplazan la consulta más nueva", async () => {
  const old = deferred<Alert[]>();
  service.getAll.mockReturnValueOnce(old.promise);
  render(<ManagerPage />);
  service.getAll.mockResolvedValueOnce([
    { ...row, id: "read", status: "READ", isRead: true },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Leídas" }));
  await screen.findByRole("article", { name: "Alerta read" });
  await act(async () => old.resolve([row]));
  expect(
    screen.queryByRole("article", { name: "Alerta alert-a" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/Consulta confirmada: Leídas/)).toBeVisible();
});
it("un filtro fallido conserva y etiqueta la consulta anterior sin habilitar acciones", async () => {
  render(<ManagerPage />);
  await article();
  service.getAll.mockRejectedValueOnce(new Error("filter"));
  fireEvent.click(screen.getByRole("button", { name: "No leídas" }));
  await screen.findByRole("alert");
  expect(
    screen.getByText(/Consulta confirmada: Todas las alertas/),
  ).toBeVisible();
  expect(screen.getByText(/todavía no está confirmada/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Descartar alerta" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await waitFor(() =>
    expect(service.getAll).toHaveBeenLastCalledWith({
      status: "UNREAD",
      limit: 51,
      offset: 0,
    }),
  );
});
it("marcar leída bloquea duplicados y espera el estado confirmado del servidor", async () => {
  const pending = deferred<void>();
  service.markAsRead.mockReturnValue(pending.promise);
  render(<ManagerPage />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
  fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
  expect(service.markAsRead).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Todas las alertas" }),
  ).toBeDisabled();
  expect(refresh()).toBeDisabled();
  service.getAll.mockResolvedValue([{ ...row, status: "READ", isRead: true }]);
  await act(async () => pending.resolve());
  await waitFor(() => expect(service.getAll).toHaveBeenCalledTimes(2));
  expect(
    screen.queryByRole("button", { name: "Marcar como leída" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Leída")).toBeVisible();
});
it("un fallo de escritura conserva el registro y exige lectura antes de repetir", async () => {
  service.markAsRead.mockRejectedValueOnce(new Error("write"));
  render(<ManagerPage />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
  await screen.findByRole("alert");
  expect(await article()).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Marcar como leída" }),
  ).toBeDisabled();
  expect(service.getAll).toHaveBeenCalledTimes(1);
  fireEvent.click(refresh());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Marcar como leída" }),
    ).toBeEnabled(),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("un guardado correcto seguido de fallo de lectura no se presenta como fallo de escritura", async () => {
  render(<ManagerPage />);
  await article();
  service.getAll.mockRejectedValueOnce(new Error("reload"));
  fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
  await screen.findByRole("alert");
  expect(
    screen.getByText("Alerta marcada como leída en tu bandeja."),
  ).toBeVisible();
  expect(service.markAsRead).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Marcar como leída" }),
  ).toBeDisabled();
});
it("descartar confirma título e ID y cancelar no emite una operación", async () => {
  render(<ManagerPage />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Descartar alerta" }));
  expect(screen.getByRole("dialog")).toHaveTextContent(row.id);
  expect(screen.getByRole("dialog")).toHaveTextContent(row.title);
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "No resuelve la incidencia",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
  expect(service.dismiss).not.toHaveBeenCalled();
});
it("descartar usa DELETE del registro mostrado y bloquea cierre durante el envío", async () => {
  const pending = deferred<void>();
  service.dismiss.mockReturnValue(pending.promise);
  render(<ManagerPage />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Descartar alerta" }));
  fireEvent.click(confirm());
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(service.dismiss).toHaveBeenCalledWith(row.id);
  service.getAll.mockResolvedValue([]);
  await act(async () => pending.resolve());
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(
    await screen.findByText(
      "La página consultada no contiene alertas visibles.",
    ),
  ).toBeVisible();
});
it.each([0, 57])(
  "leer todas explica su alcance y anuncia el contador real %s",
  async (count) => {
    service.markAllAsRead.mockResolvedValue({ count });
    render(<ManagerPage />);
    await article();
    fireEvent.click(
      screen.getByRole("button", { name: "Leer todas mis alertas" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "incluidas otras páginas",
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("filtros locales");
    fireEvent.click(confirm());
    await screen.findByText(
      `${count} alertas personales marcadas como leídas por el servidor.`,
    );
    expect(service.markAllAsRead).toHaveBeenCalledTimes(1);
  },
);
it("cancelar lectura global no marca nada", async () => {
  render(<ManagerPage />);
  await article();
  fireEvent.click(
    screen.getByRole("button", { name: "Leer todas mis alertas" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
  expect(service.markAllAsRead).not.toHaveBeenCalled();
});
it("una acción desde otra página vuelve a confirmar la primera sin duplicar la lectura", async () => {
  service.getAll
    .mockResolvedValueOnce(
      Array.from({ length: 51 }, (_, i) => ({ ...row, id: `page-${i}` })),
    )
    .mockResolvedValueOnce([row])
    .mockResolvedValueOnce([{ ...row, isRead: true, status: "READ" }]);
  render(<ManagerPage />);
  await screen.findByRole("article", { name: "Alerta page-0" });
  fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
  await waitFor(() => expect(service.getAll).toHaveBeenCalledTimes(3));
  expect(service.getAll).toHaveBeenLastCalledWith({
    status: "ALL",
    limit: 51,
    offset: 0,
  });
  await screen.findByText(/Consulta confirmada: Todas las alertas, página 1/);
});
it("una lectura anterior a otra cuenta no sustituye su bandeja", async () => {
  const old = deferred<Alert[]>();
  service.getAll.mockReturnValueOnce(old.promise);
  const view = render(<ManagerPage />);
  mockUser = { id: "other-manager", role: "GERENTE" };
  service.getAll.mockResolvedValue([{ ...row, id: "new-account" }]);
  view.rerender(<ManagerPage />);
  await screen.findByRole("article", { name: "Alerta new-account" });
  await act(async () => old.resolve([row]));
  expect(
    screen.queryByRole("article", { name: "Alerta alert-a" }),
  ).not.toBeInTheDocument();
});
it("credenciales nuevas retiran lecturas pendientes", async () => {
  const old = deferred<Alert[]>();
  service.getAll.mockReturnValueOnce(old.promise);
  render(<ManagerPage />);
  service.getAll.mockResolvedValue([]);
  await act(async () =>
    storeTokens({ access_token: "new-token", refresh_token: "new-refresh" }),
  );
  await screen.findByText("La página consultada no contiene alertas visibles.");
  await act(async () => old.resolve([row]));
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  await act(async () => clearStoredTokens());
});
it("una escritura retirada no notifica ni consulta para otra cuenta", async () => {
  const old = deferred<void>();
  service.dismiss.mockReturnValue(old.promise);
  const view = render(<ManagerPage />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Descartar alerta" }));
  fireEvent.click(confirm());
  mockUser = { id: "other", role: "GERENTE" };
  service.getAll.mockResolvedValue([]);
  view.rerender(<ManagerPage />);
  await screen.findByText("La página consultada no contiene alertas visibles.");
  await act(async () => old.resolve());
  expect(service.getAll).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByText("Alerta descartada de tu bandeja."),
  ).not.toBeInTheDocument();
});
it("StrictMode retira la primera lectura y confirma la segunda", async () => {
  const old = deferred<Alert[]>();
  service.getAll.mockReturnValueOnce(old.promise).mockResolvedValueOnce([]);
  render(
    <React.StrictMode>
      <ManagerPage />
    </React.StrictMode>,
  );
  await screen.findByText("La página consultada no contiene alertas visibles.");
  await act(async () => old.resolve([row]));
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
});
