import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/fleet/riders/map/page";
import { riderService } from "@/services/rider.service";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import {
  RIDER_MAP_POLL_MS,
  riderMapMatches,
  riderMapPosition,
  riderMapTelephone,
} from "@/lib/rider-map";
import type { Rider } from "@/types/user";

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
jest.mock("@/services/rider.service", () => ({
  riderService: { getAll: jest.fn() },
}));
jest.mock(
  "next/dynamic",
  () => (loader: any) =>
    loader.toString().includes("MapPageContent")
      ? require("@/app/(dashboard)/manager/fleet/riders/map/MapPageContent")
          .default
      : function Canvas(props: any) {
          return (
            <div data-testid="map-data">
              {JSON.stringify({
                points: props.points.map((point: any) => ({
                  id: point.rider.id,
                  position: point.position,
                })),
                focus: props.focus,
                fitSequence: props.fitSequence,
              })}
            </div>
          );
        },
);
const service = jest.mocked(riderService);
const rows: Rider[] = [
  {
    id: "rider-zero",
    first_name: "José",
    last_name: "Pérez",
    phone: "04121234567",
    email: "jose@example.test",
    status: "ACTIVO",
    is_online: true,
    last_lat: 0,
    last_lng: 0,
    last_location_at: "2026-11-08T12:00:00",
    vehicle_ownership_type: "PROPIO",
    vehicle_type: "MOTO",
    vehicle_plate: "OWN-80",
  },
  {
    id: "rider-offline",
    first_name: "Ana",
    last_name: "López",
    status: "SUSPENDIDO",
    is_online: false,
    last_lat: 10.5,
    last_lng: -66.9,
    vehicle_ownership_type: "EMPRESA",
    vehicle_plate: "OLD-80",
    assigned_vehicle_id: "v-80",
    assigned_vehicle: {
      id: "v-80",
      plate: "ASSIGNED-80",
      type: "AUTO",
      color: "Azul",
      model: "Modelo",
      year: 2026,
    },
  },
  { id: "rider-unknown", last_lat: null, last_lng: 9 },
];
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
let hidden = false;
beforeEach(() => {
  jest.resetAllMocks();
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-11-08T13:00:00Z"));
  hidden = false;
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  service.getAll.mockResolvedValue(rows);
});
afterEach(() => {
  cleanup();
  clearStoredTokens();
  jest.clearAllTimers();
  jest.useRealTimers();
  delete (document as any).hidden;
});
const ready = () =>
  screen.findByRole("article", { name: "Repartidor rider-zero" });
const mapData = () => JSON.parse(screen.getByTestId("map-data").textContent!);
const refresh = () =>
  screen.getByRole("button", { name: "Actualizar ubicaciones" });
const search = () =>
  screen.getByRole("textbox", {
    name: "Buscar por nombre, contacto, placa o ID",
  });

it.each(["GERENTE", "SUPERADMIN", "OPERADOR"])(
  "permite el mapa de lectura para %s",
  async (role) => {
    mockUser = { id: "staff", role };
    render(<Page />);
    await ready();
    expect(service.getAll).toHaveBeenCalledTimes(1);
  },
);
it.each(["CLIENTE", "REPARTIDOR", "AUDITOR"])(
  "deniega %s antes de consultar o programar lecturas",
  (role) => {
    mockUser = { id: "other", role };
    render(<Page />);
    expect(service.getAll).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
    expect(jest.getTimerCount()).toBe(0);
  },
);
it("sin sesión no monta el mapa privado", () => {
  mockUser = null;
  mockAuthenticated = false;
  render(<Page />);
  expect(service.getAll).not.toHaveBeenCalled();
});
it("muestra cero y la posición histórica desconectada sin fabricar estado, fecha o vehículo", async () => {
  render(<Page />);
  await ready();
  expect(mapData().points).toEqual([
    { id: rows[0].id, position: [0, 0] },
    { id: rows[1].id, position: [10.5, -66.9] },
  ]);
  const unknown = screen.getByRole("article", {
    name: "Repartidor rider-unknown",
  });
  expect(within(unknown).getByText("Estado no informado")).toBeVisible();
  expect(
    within(unknown).getByText("Disponibilidad no informada"),
  ).toBeVisible();
  expect(
    within(unknown).getByText("Reportada: Fecha no informada"),
  ).toBeVisible();
  expect(
    within(unknown).getByRole("button", { name: /Centrar/ }),
  ).toBeDisabled();
  expect(
    within(unknown).getByRole("link", { name: "Ver perfil de rider-unknown" }),
  ).toHaveAttribute("href", "/manager/fleet/riders/rider-unknown");
  expect(screen.getByText("AUTO · ASSIGNED-80")).toBeVisible();
  expect(screen.queryByText(/OLD-80/)).not.toBeInTheDocument();
  expect(screen.getByText(/no representa seguimiento continuo/)).toBeVisible();
});
it.each([
  [null, 0],
  [0, null],
  [undefined, 0],
  [0, undefined],
  [91, 0],
  [0, -181],
  [NaN, 0],
  [0, Infinity],
  ["0", 0],
  [true, 0],
])("excluye coordenadas inválidas %s %s", (lat, lng) => {
  expect(
    riderMapPosition({ id: "r", last_lat: lat, last_lng: lng } as Rider),
  ).toBeNull();
});
it.each([
  [0, 0],
  [-90, -180],
  [90, 180],
])("conserva coordenadas de borde %s %s", (lat, lng) => {
  expect(riderMapPosition({ id: "r", last_lat: lat, last_lng: lng })).toEqual([
    lat,
    lng,
  ]);
});
it.each([
  "jose",
  "PÉREZ",
  "04121234567",
  "jose@example.test",
  "rider-zero",
  "OWN-80",
])("busca localmente %s y ajusta los puntos visibles", async (value) => {
  render(<Page />);
  await ready();
  fireEvent.change(search(), { target: { value } });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(mapData().points).toHaveLength(1);
  expect(mapData().fitSequence).toBe(1);
  expect(service.getAll).toHaveBeenCalledTimes(1);
});
it("combina filtros de estado, conexión y coordenadas sin clasificar ausentes como desconectados", async () => {
  render(<Page />);
  await ready();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Conexión informada" }),
    { target: { value: "OFFLINE" } },
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(mapData().points[0].id).toBe("rider-offline");
  fireEvent.change(
    screen.getByRole("combobox", { name: "Conexión informada" }),
    { target: { value: "UNKNOWN" } },
  );
  fireEvent.change(
    screen.getByRole("combobox", { name: "Estado registrado" }),
    { target: { value: "UNKNOWN" } },
  );
  fireEvent.change(
    screen.getByRole("combobox", { name: "Ubicación registrada" }),
    { target: { value: "MISSING" } },
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(mapData().points).toHaveLength(0);
  expect(screen.getByText(/vista mundial de referencia/)).toBeVisible();
  expect(service.getAll).toHaveBeenCalledTimes(1);
});
it("centrar incluye cero y ajustar retira el foco anterior", async () => {
  render(<Page />);
  await ready();
  fireEvent.click(
    screen.getByRole("button", { name: "Centrar en mapa a José Pérez" }),
  );
  expect(mapData().focus.position).toEqual([0, 0]);
  fireEvent.click(
    screen.getByRole("button", { name: "Ajustar a los puntos visibles" }),
  );
  expect(mapData().focus).toBeNull();
  expect(mapData().fitSequence).toBe(1);
});
it("un fallo inicial no se convierte en consulta vacía ni fecha confirmada", async () => {
  service.getAll.mockRejectedValueOnce(new Error("Initial failed"));
  render(<Page />);
  await screen.findByText("Initial failed");
  expect(
    screen.queryByText("La consulta no devolvió repartidores."),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/Sin consulta confirmada/)).toBeVisible();
  expect(screen.queryByTestId("map-data")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar ubicaciones" }),
  );
  await ready();
});
it("un error de transporte muestra un mensaje claro sin exponer detalles técnicos", async () => {
  service.getAll.mockRejectedValueOnce(
    Object.assign(new Error("Request failed with status code 503"), {
      name: "AxiosError",
    }),
  );
  render(<Page />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "No se pudo consultar la ubicación de los repartidores.",
  );
  expect(screen.queryByText(/Request failed/)).not.toBeInTheDocument();
});
it("el resultado vacío confirmado tiene cero real y mapa sin posiciones inventadas", async () => {
  service.getAll.mockResolvedValue([]);
  render(<Page />);
  await screen.findByText("La consulta no devolvió repartidores.");
  expect(mapData().points).toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "Ajustar a los puntos visibles" }),
  ).toBeDisabled();
});
it("un fallo conserva datos y fecha de la última consulta confirmada", async () => {
  render(<Page />);
  await ready();
  const before = screen.getByText(/Consulta confirmada:/).textContent;
  jest.setSystemTime(new Date("2026-11-08T14:00:00Z"));
  service.getAll.mockRejectedValueOnce(new Error("Refresh failed"));
  fireEvent.click(refresh());
  await screen.findByText("Refresh failed");
  expect(await ready()).toBeVisible();
  expect(screen.getByText(/Consulta confirmada:/).textContent).toBe(before);
});
it("las recargas manuales no se solapan ni alteran los filtros", async () => {
  render(<Page />);
  await ready();
  fireEvent.change(search(), { target: { value: "jose" } });
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  fireEvent.click(refresh());
  fireEvent.click(refresh());
  expect(service.getAll).toHaveBeenCalledTimes(2);
  expect(refresh()).toBeDisabled();
  await act(async () => pending.resolve(rows));
  expect(search()).toHaveValue("jose");
  expect(mapData().points).toHaveLength(1);
});
it("la consulta automática empieza 20 segundos después de terminar la anterior", async () => {
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  render(<Page />);
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS * 3));
  expect(service.getAll).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(rows));
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS - 1));
  expect(service.getAll).toHaveBeenCalledTimes(1);
  await act(async () => jest.advanceTimersByTime(1));
  expect(service.getAll).toHaveBeenCalledTimes(2);
});
it("pausar cancela el timer y reanudar realiza una sola lectura", async () => {
  render(<Page />);
  await ready();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Actualización automática (20 s)" }),
  );
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS * 3));
  expect(service.getAll).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Actualización automática (20 s)" }),
  );
  await waitFor(() => expect(service.getAll).toHaveBeenCalledTimes(2));
});
it("una pausa durante una lectura impide reprogramar otra al completarse", async () => {
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  render(<Page />);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Actualización automática (20 s)" }),
  );
  await act(async () => pending.resolve(rows));
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS * 3));
  expect(service.getAll).toHaveBeenCalledTimes(1);
});
it("ocultar la pestaña pausa la consulta y mostrarla no solapa una lectura pendiente", async () => {
  render(<Page />);
  await ready();
  hidden = true;
  fireEvent(document, new Event("visibilitychange"));
  expect(screen.getByText(/pestaña oculta/)).toBeVisible();
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS * 3));
  expect(service.getAll).toHaveBeenCalledTimes(1);
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  hidden = false;
  fireEvent(document, new Event("visibilitychange"));
  hidden = true;
  fireEvent(document, new Event("visibilitychange"));
  hidden = false;
  fireEvent(document, new Event("visibilitychange"));
  expect(service.getAll).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve(rows));
});
it("un error de consulta automática permite la siguiente consulta sin perder la ficha", async () => {
  render(<Page />);
  await ready();
  service.getAll.mockRejectedValueOnce(new Error("Auto failed"));
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS));
  await screen.findByText("Auto failed");
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS));
  expect(service.getAll).toHaveBeenCalledTimes(3);
  expect(screen.queryByText("Auto failed")).not.toBeInTheDocument();
});
it("desmontar retira una lectura pendiente y su timer", async () => {
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  const view = render(<Page />);
  view.unmount();
  await act(async () => pending.resolve(rows));
  await act(async () => jest.advanceTimersByTime(RIDER_MAP_POLL_MS * 3));
  expect(service.getAll).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});
it("cambiar credenciales retira los datos anteriores y su consulta pendiente", async () => {
  const pending = deferred<Rider[]>();
  service.getAll.mockReturnValueOnce(pending.promise);
  render(<Page />);
  service.getAll.mockResolvedValue([
    { ...rows[0], id: "new-rider", first_name: "Nueva" },
  ]);
  await act(async () =>
    storeTokens({ access_token: "new-token", refresh_token: "new-refresh" }),
  );
  await screen.findByRole("article", { name: "Repartidor new-rider" });
  await act(async () => pending.resolve(rows));
  expect(
    screen.queryByRole("article", { name: "Repartidor rider-zero" }),
  ).not.toBeInTheDocument();
});
it("StrictMode retira su primera lectura sin bloquear ni reemplazar la segunda", async () => {
  const old = deferred<Rider[]>();
  service.getAll
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce([{ ...rows[0], first_name: "Confirmada" }]);
  render(
    <React.StrictMode>
      <Page />
    </React.StrictMode>,
  );
  await screen.findByText("Confirmada Pérez");
  await act(async () => old.resolve(rows));
  expect(screen.queryByText("José Pérez")).not.toBeInTheDocument();
});
it.each([
  ["+58 (412) 123-4567", "tel:+584121234567"],
  ["0412 1234567", "tel:04121234567"],
  ["javascript:alert(1)", null],
  ["+", null],
  [null, null],
])("el enlace de llamada usa solo un teléfono válido %s", (input, output) => {
  expect(riderMapTelephone(input)).toBe(output);
});
it("la búsqueda no usa una placa de asignación ajena ni inventa datos", () => {
  const mismatch = { ...rows[1], assigned_vehicle_id: "other" };
  expect(riderMapMatches(mismatch, "ASSIGNED-80", "ALL", "ALL", "ALL")).toBe(
    false,
  );
  expect(riderMapMatches(mismatch, "OLD-80", "ALL", "ALL", "ALL")).toBe(false);
});
