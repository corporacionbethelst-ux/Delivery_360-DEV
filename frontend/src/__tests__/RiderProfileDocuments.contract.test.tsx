import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Profile from "@/app/(dashboard)/manager/fleet/riders/[id]/page";
import Documents from "@/app/(dashboard)/manager/fleet/riders/[id]/documents/page";
import { riderService } from "@/services/rider.service";
import type { Rider, RiderDocument } from "@/types/user";
import { riderCoordinates, riderDate, riderNumber } from "@/lib/rider-display";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

const mockRouter = { replace: jest.fn() };
let mockId = "rider-a",
  mockUser: { id: string; role: string } | null = {
    id: "manager",
    role: "GERENTE",
  },
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({
  useParams: () => ({ id: mockId }),
  useRouter: () => mockRouter,
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/services/rider.service", () => ({
  riderService: {
    getById: jest.fn(),
    updateStatus: jest.fn(),
    getDocuments: jest.fn(),
    approveDocument: jest.fn(),
    rejectDocument: jest.fn(),
    deleteDocument: jest.fn(),
    uploadDocumentForRider: jest.fn(),
  },
}));
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/components/DocumentDownloadButton", () => ({
  DocumentDownloadButton: ({ documentId, revision }: any) => (
    <button>
      Descargar {documentId}:{revision}
    </button>
  ),
}));
const service = jest.mocked(riderService);
const rider: Rider = {
  id: "rider-a",
  first_name: "José",
  last_name: "Pérez",
  email: "jose@example.test",
  status: "ACTIVO",
  is_online: true,
};
const doc: RiderDocument = {
  id: "document-a",
  rider_id: "rider-a",
  type: "LICENCIA",
  status: "PENDIENTE",
  revision: "a".repeat(64),
  created_at: "2026-11-08T12:00:00",
  file_url: "/private/file",
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
  mockId = rider.id;
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getById.mockResolvedValue({ ...rider });
  service.getDocuments.mockResolvedValue([{ ...doc }]);
  jest.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => jest.restoreAllMocks());
const identity = () =>
  screen.findByRole("region", { name: "Identidad del repartidor" });
const article = () =>
  screen.findByRole("article", { name: `Documento ${doc.id}` });
const openUpload = async () => {
  fireEvent.click(
    await screen.findByRole("button", { name: "Subir Documento" }),
  );
  return screen.getByRole("dialog");
};
const chooseFile = (
  file = new File(["synthetic"], "document.pdf", { type: "application/pdf" }),
) => {
  fireEvent.change(screen.getByLabelText("Tipo de Documento"), {
    target: { value: "LICENCIA" },
  });
  fireEvent.change(screen.getByLabelText("Archivo (PDF, JPG, PNG)"), {
    target: { files: [file] },
  });
  return file;
};

describe.each([
  ["perfil", Profile],
  ["documentos", Documents],
] as const)("acceso %s", (_name, Page) => {
  it.each(["GERENTE", "SUPERADMIN", "OPERADOR"])(
    "permite lectura a %s y restringe las acciones",
    async (role) => {
      mockUser = { id: "staff", role };
      render(<Page />);
      if (Page === Profile) {
        await identity();
        expect(
          screen.queryByRole("button", { name: "Suspender" }) !== null,
        ).toBe(role !== "OPERADOR");
      } else {
        await article();
        expect(
          screen.queryByRole("button", {
            name: "Subir Documento",
          }) !== null,
        ).toBe(role !== "OPERADOR");
        expect(screen.queryByRole("button", { name: "Aprobar" }) !== null).toBe(
          role !== "OPERADOR",
        );
      }
    },
  );
  it.each(["CLIENTE", "REPARTIDOR", "AUDITOR"])(
    "no consulta desde la ruta de gerencia para %s",
    (role) => {
      mockUser = { id: "other", role };
      render(<Page />);
      expect(service.getById).not.toHaveBeenCalled();
      expect(service.getDocuments).not.toHaveBeenCalled();
      expect(mockRouter.replace).toHaveBeenCalledWith("/login");
    },
  );
});
it("perfil conserva ausentes sin inventar saldos, moneda, fechas, nivel o conexión", async () => {
  service.getById.mockResolvedValue({ id: rider.id });
  render(<Profile />);
  const card = await identity();
  expect(within(card).getByText("Nombre no informado")).toBeVisible();
  expect(within(card).getByText("Estado no informado")).toBeVisible();
  expect(within(card).getByText("Disponibilidad no informada")).toBeVisible();
  expect(screen.getByText("Nivel no informado")).toBeVisible();
  expect(screen.getByText("Entregas: No informado")).toBeVisible();
  expect(screen.getByText("Registro: Fecha no informada")).toBeVisible();
  expect(
    screen.queryByText(/COP|BRONCE|Todas las zonas|Señal GPS Activa/),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Activar" }),
  ).not.toBeInTheDocument();
});
it("perfil conserva cero, coordenadas de cero y última señal aunque esté desconectado", async () => {
  service.getById.mockResolvedValue({
    ...rider,
    is_online: false,
    last_lat: 0,
    last_lng: 0,
    wallet_balance: 0,
    pending_balance: 1.23456789,
    total_deliveries: 0,
    rating: 0,
  } as Rider);
  render(<Profile />);
  await identity();
  expect(screen.getByText("0.000000, 0.000000")).toBeVisible();
  expect(screen.getByText("Entregas: 0")).toBeVisible();
  expect(screen.getByText("Calificación: 0")).toBeVisible();
  expect(screen.getByText("1,23456789")).toBeVisible();
});
it.each([
  [null, 0],
  [0, null],
  [91, 0],
  [0, 181],
  [NaN, 0],
  [0, Infinity],
])("rechaza un par de coordenadas incompleto o inválido %s %s", (lat, lng) => {
  expect(
    riderCoordinates({ ...rider, last_lat: lat, last_lng: lng }),
  ).toBeNull();
});
it("fechas ausentes o inválidas no se sustituyen por hoy y UTC sin sufijo se convierte a Caracas", () => {
  expect(riderDate(null)).toBe("Fecha no informada");
  expect(riderDate("invalid")).toBe("Fecha no informada");
  expect(riderDate("2026-11-08T12:00:00")).toBe(
    riderDate("2026-11-08T12:00:00Z"),
  );
  expect(riderDate("2026-11-08T12:00:00")).toContain("8:00");
  expect(riderNumber("0")).toBe("No informado");
  expect(riderNumber(NaN)).toBe("No informado");
});
it.each([true, false])(
  "perfil usa exclusivamente el vehículo asignado que coincide: %s",
  async (matches) => {
    service.getById.mockResolvedValue({
      ...rider,
      vehicle_ownership_type: "EMPRESA",
      vehicle_plate: "OLD-PLATE",
      assigned_vehicle_id: "v-a",
      assigned_vehicle: {
        id: matches ? "v-a" : "v-b",
        plate: "CURRENT-PLATE",
        type: "AUTO",
        model: "Model",
        color: "Blue",
        year: 2026,
      },
    });
    render(<Profile />);
    await identity();
    const card = screen.getByRole("region", { name: "Vehículo asignado" });
    expect(within(card).queryByText("CURRENT-PLATE") !== null).toBe(matches);
    expect(within(card).queryByText("OLD-PLATE")).not.toBeInTheDocument();
  },
);
it("perfil rechaza una respuesta para otro ID y ofrece recarga", async () => {
  service.getById.mockResolvedValueOnce({ ...rider, id: "other" });
  render(<Profile />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no corresponde");
  expect(
    screen.queryByRole("button", { name: "Suspender" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar perfil" }));
  await identity();
});
it("perfil conserva la ficha confirmada ante un error de recarga y bloquea el cambio", async () => {
  render(<Profile />);
  await identity();
  service.getById.mockRejectedValueOnce(new Error("Read failed"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar perfil" }));
  await screen.findByText("Read failed");
  expect(await identity()).toHaveTextContent("José Pérez");
  expect(screen.getByRole("button", { name: "Suspender" })).toBeDisabled();
});
it("perfil identifica la confirmación, impide doble envío y confirma conexión desde una lectura nueva", async () => {
  const write = deferred<Rider>();
  service.updateStatus.mockReturnValue(write.promise);
  render(<Profile />);
  await identity();
  fireEvent.click(screen.getByRole("button", { name: "Suspender" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("José Pérez");
  expect(screen.getByRole("dialog")).toHaveTextContent(rider.id);
  fireEvent.click(screen.getByRole("button", { name: "Confirmar estado" }));
  fireEvent.click(screen.getByRole("button", { name: "Guardando…" }));
  expect(service.updateStatus).toHaveBeenCalledTimes(1);
  service.getById.mockResolvedValue({
    ...rider,
    status: "SUSPENDIDO",
    is_online: false,
  });
  await act(async () =>
    write.resolve({
      rider_id: rider.id,
      status: "SUSPENDIDO",
    } as unknown as Rider),
  );
  await waitFor(() => expect(service.getById).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("Desconectado")).toBeVisible();
  expect(screen.getByRole("button", { name: "Activar" })).toBeEnabled();
});
it("perfil conserva la ficha y la confirmación si falla el cambio", async () => {
  service.updateStatus.mockRejectedValue(new Error("Write failed"));
  render(<Profile />);
  await identity();
  fireEvent.click(screen.getByRole("button", { name: "Suspender" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirmar estado" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("dialog")).getByRole("alert"),
    ).toHaveTextContent("Write failed"),
  );
  expect(
    screen.getByRole("button", { name: "Confirmar estado" }),
  ).toBeEnabled();
  expect(service.getById).toHaveBeenCalledTimes(1);
});
it("perfil distingue éxito del cambio de un fallo al recargar sin repetir la escritura", async () => {
  service.updateStatus.mockResolvedValue({} as Rider);
  render(<Profile />);
  await identity();
  service.getById.mockRejectedValue(new Error("Reload failed"));
  fireEvent.click(screen.getByRole("button", { name: "Suspender" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirmar estado" }));
  expect(await screen.findByText("Reload failed")).toBeVisible();
  expect(screen.getByText(/Estado actualizado\. La ficha/)).toBeVisible();
  expect(service.updateStatus).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Suspender" })).toBeDisabled();
});
it("perfil recarga después de un conflicto de activación sin inventar conexión", async () => {
  service.getById.mockResolvedValue({ ...rider, status: "PENDIENTE" });
  service.updateStatus.mockRejectedValue(
    Object.assign(new Error("Documentos pendientes"), { status: 409 }),
  );
  render(<Profile />);
  await identity();
  fireEvent.click(screen.getByRole("button", { name: "Aprobar Repartidor" }));
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "no lo conecta automáticamente",
  );
  service.getById.mockResolvedValue({
    ...rider,
    status: "PENDIENTE",
    is_online: false,
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirmar estado" }));
  await screen.findByText("Desconectado");
  expect(service.getById).toHaveBeenCalledTimes(2);
  expect(service.updateStatus).toHaveBeenCalledTimes(1);
});
it("perfil retira una lectura tardía al cambiar de ruta", async () => {
  const old = deferred<Rider>();
  service.getById.mockReturnValueOnce(old.promise);
  const view = render(<Profile />);
  mockId = "rider-b";
  service.getById.mockResolvedValue({
    ...rider,
    id: mockId,
    first_name: "Ana",
  });
  view.rerender(<Profile />);
  await screen.findByText("Ana Pérez");
  await act(async () => old.resolve(rider));
  expect(screen.queryByText("José Pérez")).not.toBeInTheDocument();
});
it("perfil no recarga otra ficha al finalizar una escritura retirada", async () => {
  const old = deferred<Rider>();
  service.updateStatus.mockReturnValue(old.promise);
  const view = render(<Profile />);
  await identity();
  fireEvent.click(screen.getByRole("button", { name: "Suspender" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirmar estado" }));
  mockId = "rider-b";
  service.getById.mockResolvedValue({
    ...rider,
    id: mockId,
    first_name: "Ana",
  });
  view.rerender(<Profile />);
  await screen.findByText("Ana Pérez");
  await act(async () => old.resolve(rider));
  expect(service.getById).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByText(/Estado actualizado\. La ficha/),
  ).not.toBeInTheDocument();
});
it("documentos distingue fallo inicial de un resultado vacío confirmado", async () => {
  service.getDocuments.mockRejectedValueOnce(new Error("Documents failed"));
  render(<Documents />);
  await screen.findByText("Documents failed");
  expect(
    screen.queryByText("Sin documentos registrados"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Subir Documento" }),
  ).toBeDisabled();
  service.getDocuments.mockResolvedValue([]);
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar documentos" }),
  );
  expect(await screen.findByText("Sin documentos registrados")).toBeVisible();
});
it("documentos conserva el catálogo si falla la recarga", async () => {
  render(<Documents />);
  await article();
  service.getDocuments.mockRejectedValueOnce(new Error("Refresh failed"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  await screen.findByText("Refresh failed");
  expect(await article()).toBeVisible();
  expect(screen.getByRole("button", { name: "Aprobar" })).toBeDisabled();
});
it.each(["foreign", "duplicate"])(
  "documentos rechaza respuesta %s sin acciones",
  async (mode) => {
    service.getDocuments.mockResolvedValue(
      mode === "foreign" ? [{ ...doc, rider_id: "other" }] : [doc, doc],
    );
    render(<Documents />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "no corresponde",
    );
    expect(
      screen.queryByRole("button", { name: "Aprobar" }),
    ).not.toBeInTheDocument();
  },
);
it("documentos no convierte un estado desconocido en pendiente y vincula la descarga a revisión", async () => {
  service.getDocuments.mockResolvedValue([
    {
      ...doc,
      status: undefined,
      created_at: "invalid",
    } as unknown as RiderDocument,
  ]);
  render(<Documents />);
  const card = await article();
  expect(within(card).getByText("Estado no informado")).toBeVisible();
  expect(within(card).getByText("Subido: Fecha no informada")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Aprobar" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: `Descargar ${doc.id}:${doc.revision}` }),
  ).toBeVisible();
});
it("documentos sin revisión no permite descargar ni emitir una aprobación", async () => {
  service.getDocuments.mockResolvedValue([{ ...doc, revision: undefined }]);
  render(<Documents />);
  await article();
  expect(
    screen.queryByRole("button", { name: /Descargar/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
  expect(service.approveDocument).not.toHaveBeenCalled();
  expect(await screen.findByRole("alert")).toHaveTextContent("Recarga");
});
it("documentos bloquea todas las acciones y duplicados durante una aprobación", async () => {
  const write = deferred<any>();
  service.approveDocument.mockReturnValue(write.promise);
  render(<Documents />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
  fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
  expect(service.approveDocument).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Rechazar" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Actualizar" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Subir Documento" }),
  ).toBeDisabled();
  await act(async () => write.resolve({}));
  await waitFor(() => expect(service.getDocuments).toHaveBeenCalledTimes(2));
});
it("documentos conserva el motivo al fallar un rechazo y permite corregirlo", async () => {
  service.rejectDocument.mockRejectedValue(new Error("Reject failed"));
  render(<Documents />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));
  fireEvent.change(screen.getByLabelText("Motivo del rechazo *"), {
    target: { value: "  Imagen borrosa  " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("dialog")).getByRole("alert"),
    ).toHaveTextContent("Reject failed"),
  );
  expect(screen.getByLabelText("Motivo del rechazo *")).toHaveValue(
    "  Imagen borrosa  ",
  );
  expect(service.rejectDocument).toHaveBeenCalledWith(
    doc.id,
    "Imagen borrosa",
    doc.revision,
  );
  expect(screen.getByLabelText("Motivo del rechazo *")).toHaveAttribute(
    "maxLength",
    "2000",
  );
});
it("documentos no envía rechazo vacío", async () => {
  render(<Documents />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));
  fireEvent.change(screen.getByLabelText("Motivo del rechazo *"), {
    target: { value: "   " },
  });
  expect(screen.getByRole("button", { name: "Confirmar" })).toBeDisabled();
  expect(service.rejectDocument).not.toHaveBeenCalled();
});
it("carga documental ofrece solo los cuatro tipos realmente soportados y etiquetas asociadas", async () => {
  render(<Documents />);
  await article();
  await openUpload();
  expect(screen.getByLabelText("Tipo de Documento")).toBeVisible();
  expect(screen.getAllByRole("option")).toHaveLength(5);
  expect(
    screen.queryByRole("option", { name: /Antecedentes/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Archivo (PDF, JPG, PNG)")).toHaveAttribute(
    "accept",
    ".pdf,.png,.jpg,.jpeg",
  );
});
it.each(["empty", "size", "extension", "mime"])(
  "carga documental rechaza archivo %s antes del servicio",
  async (mode) => {
    render(<Documents />);
    await article();
    await openUpload();
    const candidate = new File(
      mode === "empty" ? [] : ["synthetic"],
      mode === "extension" ? "doc.exe" : "doc.pdf",
      { type: mode === "mime" ? "image/png" : "application/pdf" },
    );
    if (mode === "size")
      Object.defineProperty(candidate, "size", { value: 10 * 1024 * 1024 + 1 });
    chooseFile(candidate);
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Subir" })).toBeDisabled();
    expect(service.uploadDocumentForRider).not.toHaveBeenCalled();
  },
);
it("carga documental bloquea campos, cierre y doble envío mientras guarda", async () => {
  const write = deferred<RiderDocument>();
  service.uploadDocumentForRider.mockReturnValue(write.promise);
  render(<Documents />);
  await article();
  await openUpload();
  const file = chooseFile();
  fireEvent.click(screen.getByRole("button", { name: "Subir" }));
  fireEvent.click(screen.getByRole("button", { name: "Subiendo…" }));
  expect(service.uploadDocumentForRider).toHaveBeenCalledTimes(1);
  expect(service.uploadDocumentForRider).toHaveBeenCalledWith(rider.id, {
    type: "LICENCIA",
    file,
  });
  expect(screen.getByLabelText("Tipo de Documento")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  await act(async () => write.resolve(doc));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});
it("carga documental conserva archivo y tipo tras un fallo y usa ese borrador al reintentar", async () => {
  service.uploadDocumentForRider
    .mockRejectedValueOnce(new Error("Upload failed"))
    .mockResolvedValueOnce(doc);
  render(<Documents />);
  await article();
  await openUpload();
  const file = chooseFile();
  fireEvent.click(screen.getByRole("button", { name: "Subir" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("dialog")).getByRole("alert"),
    ).toHaveTextContent("Upload failed"),
  );
  expect(screen.getByLabelText("Tipo de Documento")).toHaveValue("LICENCIA");
  fireEvent.click(screen.getByRole("button", { name: "Subir" }));
  await waitFor(() =>
    expect(service.uploadDocumentForRider).toHaveBeenCalledTimes(2),
  );
  expect(service.uploadDocumentForRider).toHaveBeenLastCalledWith(rider.id, {
    type: "LICENCIA",
    file,
  });
});
it("carga documental no convierte un fallo posterior de lectura en fallo de subida", async () => {
  service.uploadDocumentForRider.mockResolvedValue(doc);
  render(<Documents />);
  await article();
  await openUpload();
  chooseFile();
  service.getDocuments.mockRejectedValueOnce(new Error("Reload failed"));
  fireEvent.click(screen.getByRole("button", { name: "Subir" }));
  await screen.findByText("Reload failed");
  expect(screen.getByText("Documento subido exitosamente")).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(service.uploadDocumentForRider).toHaveBeenCalledTimes(1);
});
it("documentos retira una lectura de otra ruta", async () => {
  const old = deferred<RiderDocument[]>();
  service.getDocuments.mockReturnValueOnce(old.promise);
  const view = render(<Documents />);
  mockId = "rider-b";
  service.getDocuments.mockResolvedValue([]);
  view.rerender(<Documents />);
  await screen.findByText("Sin documentos registrados");
  await act(async () => old.resolve([doc]));
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
});
it("documentos no recarga ni notifica una escritura terminada en otra ruta", async () => {
  const old = deferred<any>();
  service.approveDocument.mockReturnValueOnce(old.promise);
  const view = render(<Documents />);
  await article();
  fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));
  mockId = "rider-b";
  service.getDocuments.mockResolvedValue([]);
  view.rerender(<Documents />);
  await screen.findByText("Sin documentos registrados");
  await act(async () => old.resolve({}));
  expect(service.getDocuments).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByText("Documento aprobado correctamente"),
  ).not.toBeInTheDocument();
});
it.each([
  ["perfil", Profile],
  ["documentos", Documents],
] as const)(
  "%s remonta al cambiar credenciales y retira el resultado anterior",
  async (_name, Page) => {
    const old = deferred<any>();
    if (Page === Profile) service.getById.mockReturnValueOnce(old.promise);
    else service.getDocuments.mockReturnValueOnce(old.promise);
    render(<Page />);
    await act(async () =>
      storeTokens({ access_token: "new-token", refresh_token: "new-refresh" }),
    );
    if (Page === Profile) await identity();
    else await article();
    await act(async () =>
      old.resolve(
        Page === Profile
          ? { ...rider, first_name: "Retired" }
          : [{ ...doc, id: "retired" }],
      ),
    );
    expect(screen.queryByText("Retired Pérez")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("article", { name: "Documento retired" }),
    ).not.toBeInTheDocument();
    await act(async () => clearStoredTokens());
  },
);
