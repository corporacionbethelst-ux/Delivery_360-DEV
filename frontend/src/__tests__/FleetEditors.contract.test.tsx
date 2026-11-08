import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import VehicleEditor from "@/app/(dashboard)/manager/fleet/vehicles/[id]/page";
import ZoneEditor from "@/app/(dashboard)/manager/fleet/zones/[id]/page";
import { vehicleService, type Vehicle } from "@/services/vehicle.service";
import { zoneService, type Zone } from "@/services/zone.service";

let mockId = "123e4567-e89b-42d3-a456-426614174000";
const nextId = "123e4567-e89b-42d3-a456-426614174001";
const mockRouter = { push: jest.fn(), back: jest.fn() };
jest.mock("next/navigation", () => ({
  useParams: () => ({ id: mockId }),
  useRouter: () => mockRouter,
}));
jest.mock("sonner", () => ({
  toast: { error: jest.fn(), success: jest.fn() },
}));
jest.mock("@/services/vehicle.service", () => ({
  vehicleService: { getById: jest.fn(), update: jest.fn() },
}));
jest.mock("@/services/zone.service", () => ({
  zoneService: { getById: jest.fn(), update: jest.fn(), delete: jest.fn() },
}));
jest.mock("@/components/ui/select", () => ({
  Select: ({ children, value, onValueChange }: any) => (
    <select value={value} onChange={(e) => onValueChange(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ children, value }: any) => (
    <option value={value}>{children}</option>
  ),
}));
const vehicles = jest.mocked(vehicleService),
  zones = jest.mocked(zoneService);
const vehicle = {
  id: mockId,
  edit_revision: "a".repeat(64),
  plate: "TEST-1",
  model: "Modelo",
  type: "MOTO",
  status: "ACTIVO",
  year: 2026,
  color: "Azul",
  insurance_expiry: null,
  notes: "Nota",
  created_at: "2026-01-01",
} as Vehicle;
const zone = {
  id: mockId,
  name: "Centro",
  code: "CTR",
  color_hex: "#3b82f6",
  description: "Zona cargada",
  is_active: true,
  is_priority: false,
  riders_count: 0,
  active_orders_count: 0,
  delivery_fee_base: 0,
  cost_per_km: 0.75,
  estimated_time_min: 30,
  bonus_multiplier: 1.5,
  center_lat: null,
  center_lng: null,
  created_at: "2026-01-01",
} as Zone;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  jest.clearAllMocks();
  mockId = vehicle.id;
  vehicles.getById.mockResolvedValue(vehicle);
  vehicles.update.mockResolvedValue(vehicle);
  zones.getById.mockResolvedValue(zone);
  zones.update.mockResolvedValue(zone);
  zones.delete.mockResolvedValue(undefined as never);
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Guardar Cambios" }));

it.each([
  ["2026-11-07", "Fecha de vencimiento pasada"],
  ["2026-11-08", "Vence hoy"],
  ["2026-11-09", "Vencimiento futuro"],
])(
  "compares insurance date %s by calendar day instead of UTC midnight",
  async (date, label) => {
    jest.useFakeTimers().setSystemTime(new Date(2026, 10, 8, 12));
    vehicles.getById.mockResolvedValueOnce({
      ...vehicle,
      insurance_expiry: date,
    });
    render(<VehicleEditor />);
    await screen.findByDisplayValue("Modelo");
    expect(screen.getByText(label)).toBeInTheDocument();
  },
);

it.each([
  ["vehículo", VehicleEditor, vehicles.getById],
  ["zona", ZoneEditor, zones.getById],
] as const)(
  "does not expose a default %s draft when reading fails and supports retry",
  async (_, Component, read) => {
    read.mockRejectedValueOnce(new Error("Sin conexión"));
    render(<Component />);
    await screen.findByText("Sin conexión");
    expect(
      screen.queryByRole("button", { name: "Guardar Cambios" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recargar ficha" }));
    await screen.findByRole("button", { name: "Guardar Cambios" });
  },
);
it.each([
  [VehicleEditor, vehicles.getById, { ...vehicle, id: nextId }],
  [ZoneEditor, zones.getById, { ...zone, id: nextId }],
] as const)(
  "rejects a successful response for another record",
  async (Component, read, value) => {
    read.mockResolvedValueOnce(value as never);
    render(<Component />);
    await screen.findByText(/La ficha no coincide/);
    expect(
      screen.queryByRole("button", { name: "Guardar Cambios" }),
    ).not.toBeInTheDocument();
    expect(vehicles.update).not.toHaveBeenCalled();
    expect(zones.update).not.toHaveBeenCalled();
  },
);
it.each([VehicleEditor, ZoneEditor])(
  "handles a missing route ID without making a request",
  async (Component) => {
    mockId = "";
    render(<Component />);
    await screen.findByText(/ID de .* no informado/);
    expect(vehicles.getById).not.toHaveBeenCalled();
    expect(zones.getById).not.toHaveBeenCalled();
  },
);
it("preserves unknown coordinates and decimal fees when another zone field changes", async () => {
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  expect(screen.getByLabelText("Latitud")).toHaveValue(null);
  expect(screen.getByLabelText("Longitud")).toHaveValue(null);
  fireEvent.change(screen.getByLabelText("Descripción Operativa"), {
    target: { value: "Nueva nota" },
  });
  save();
  await waitFor(() =>
    expect(zones.update).toHaveBeenCalledWith(
      zone.id,
      expect.objectContaining({
        center_lat: null,
        center_lng: null,
        delivery_fee_base: 0,
        cost_per_km: 0.75,
      }),
    ),
  );
});
it("preserves actual coordinate zero and allows explicitly clearing a known location", async () => {
  zones.getById.mockResolvedValueOnce({
    ...zone,
    center_lat: 0,
    center_lng: 20,
  });
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  expect(screen.getByLabelText("Latitud")).toHaveValue(0);
  fireEvent.change(screen.getByLabelText("Longitud"), {
    target: { value: "" },
  });
  save();
  await waitFor(() =>
    expect(zones.update).toHaveBeenCalledWith(
      zone.id,
      expect.objectContaining({ center_lat: 0, center_lng: null }),
    ),
  );
});
it("preserves a valid fractional multiplier in the example and payload", async () => {
  zones.getById.mockResolvedValueOnce({ ...zone, bonus_multiplier: 1.25 });
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  expect(screen.getByLabelText("Multiplicador de Bono")).toHaveValue(1.25);
  expect(screen.getByText(/unidades × 1.25 ≈/)).toBeInTheDocument();
  save();
  await waitFor(() =>
    expect(zones.update).toHaveBeenCalledWith(
      zone.id,
      expect.objectContaining({ bonus_multiplier: 1.25 }),
    ),
  );
});
it.each([
  ["Nombre de la Zona *", "   ", /obligatorios/],
  ["Código Corto *", "   ", /obligatorios/],
  ["Tarifa Base", "-1", /tarifas deben/],
  ["Costo por Km", "-1", /tarifas deben/],
  ["Tiempo Est. (min)", "0", /tiempo estimado/],
  ["Tiempo Est. (min)", "1.5", /tiempo estimado/],
  ["Tiempo Est. (min)", "241", /tiempo estimado/],
  ["Multiplicador de Bono", "0", /multiplicador debe/],
  ["Multiplicador de Bono", "5.1", /multiplicador debe/],
  ["Latitud", "90.1", /coordenadas/],
  ["Longitud", "-180.1", /coordenadas/],
] as const)(
  "blocks invalid %s before sending any update",
  async (label, value, error) => {
    render(<ZoneEditor />);
    await screen.findByDisplayValue("Centro");
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    save();
    await screen.findByText(error);
    expect(zones.update).not.toHaveBeenCalled();
  },
);
it("locks a zone draft while saving and prevents duplicate submissions", async () => {
  const pending = deferred<Zone>();
  zones.update.mockReturnValueOnce(pending.promise);
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  save();
  expect(screen.getByLabelText("Nombre de la Zona *")).toBeDisabled();
  expect(screen.getByRole("button", { name: /Guardando/ })).toBeDisabled();
  expect(zones.update).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(zone));
});
it("keeps the zone draft on a save failure and allows correcting it", async () => {
  zones.update.mockRejectedValueOnce(new Error("Fallo al guardar"));
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  fireEvent.change(screen.getByLabelText("Descripción Operativa"), {
    target: { value: "Conservar" },
  });
  save();
  await screen.findByText("Fallo al guardar");
  expect(screen.getByDisplayValue("Conservar")).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Nombre de la Zona *"), {
    target: { value: "Centro nuevo" },
  });
  save();
  await waitFor(() =>
    expect(zones.update).toHaveBeenLastCalledWith(
      zone.id,
      expect.objectContaining({
        name: "Centro nuevo",
        description: "Conservar",
      }),
    ),
  );
});
it("ignores an obsolete zone read after navigating to a different record", async () => {
  const old = deferred<Zone>();
  zones.getById.mockReturnValueOnce(old.promise);
  const { rerender } = render(<ZoneEditor />);
  mockId = nextId;
  zones.getById.mockResolvedValueOnce({ ...zone, id: nextId, name: "Segunda" });
  rerender(<ZoneEditor />);
  await screen.findByDisplayValue("Segunda");
  await act(async () => old.resolve(zone));
  expect(screen.queryByDisplayValue("Centro")).not.toBeInTheDocument();
  save();
  await waitFor(() =>
    expect(zones.update).toHaveBeenCalledWith(
      nextId,
      expect.objectContaining({ name: "Segunda" }),
    ),
  );
});
it.each([
  [
    VehicleEditor,
    vehicles.getById,
    vehicles.update,
    vehicle,
    "Modelo",
    "Segundo vehículo",
  ],
  [ZoneEditor, zones.getById, zones.update, zone, "Centro", "Segunda zona"],
] as const)(
  "retires late save results and timers when changing records",
  async (Component, read, update, row, initial, next) => {
    jest.useFakeTimers();
    const pending = deferred<any>();
    update.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<Component />);
    await screen.findByDisplayValue(initial);
    save();
    mockId = nextId;
    read.mockResolvedValueOnce({
      ...row,
      id: nextId,
      name: next,
      model: next,
    } as never);
    rerender(<Component />);
    await screen.findByDisplayValue(next);
    await act(async () => pending.resolve(row));
    await act(async () => {
      jest.advanceTimersByTime(2000);
    });
    expect(mockRouter.push).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue(next)).toBeInTheDocument();
  },
);
it("requires confirmation before zone deletion and retains a delete failure for review", async () => {
  zones.delete.mockRejectedValueOnce(new Error("Zona no eliminada"));
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  fireEvent.click(screen.getByRole("button", { name: "Eliminar Zona" }));
  expect(zones.delete).not.toHaveBeenCalled();
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Cancelar",
    }),
  );
  expect(zones.delete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Eliminar Zona" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Sí, eliminar zona",
    }),
  );
  await screen.findByText("Zona no eliminada");
  expect(screen.getByLabelText("Nombre de la Zona *")).toBeEnabled();
});
it("identifies the loaded zone instead of an unsaved name in delete confirmation", async () => {
  render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  fireEvent.change(screen.getByLabelText("Nombre de la Zona *"), {
    target: { value: "Nombre sin guardar" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Eliminar Zona" }));
  expect(
    within(screen.getByRole("dialog")).getByText("Centro"),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("dialog")).queryByText("Nombre sin guardar"),
  ).not.toBeInTheDocument();
  expect(zones.delete).not.toHaveBeenCalled();
});
it("does not navigate away from a newer zone when an older deletion resolves", async () => {
  const pending = deferred<never>();
  zones.delete.mockReturnValueOnce(pending.promise);
  const { rerender } = render(<ZoneEditor />);
  await screen.findByDisplayValue("Centro");
  fireEvent.click(screen.getByRole("button", { name: "Eliminar Zona" }));
  fireEvent.click(screen.getByRole("button", { name: "Sí, eliminar zona" }));
  mockId = nextId;
  zones.getById.mockResolvedValueOnce({ ...zone, id: nextId, name: "Segunda" });
  rerender(<ZoneEditor />);
  await screen.findByDisplayValue("Segunda");
  await act(async () => pending.resolve(undefined as never));
  expect(mockRouter.push).not.toHaveBeenCalled();
});
it("does not invent a rider profile link from a user ID", async () => {
  vehicles.getById.mockResolvedValueOnce({
    ...vehicle,
    rider_id: "actual-user",
    rider_name: null,
    rider_profile_id: null,
  });
  render(<VehicleEditor />);
  await screen.findByDisplayValue("Modelo");
  expect(
    screen.getByText("Nombre de repartidor no informado"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Ver Rider" }),
  ).not.toBeInTheDocument();
});
it("uses the actual rider profile ID for navigation", async () => {
  vehicles.getById.mockResolvedValueOnce({
    ...vehicle,
    rider_id: "actual-user",
    rider_profile_id: "actual-profile",
    rider_name: "Ana",
  });
  render(<VehicleEditor />);
  fireEvent.click(await screen.findByRole("button", { name: "Ver Rider" }));
  expect(mockRouter.push).toHaveBeenCalledWith(
    "/manager/fleet/riders/actual-profile",
  );
});
it("rejects fractional vehicle years rather than rounding them", async () => {
  render(<VehicleEditor />);
  await screen.findByDisplayValue("Modelo");
  fireEvent.change(screen.getByLabelText("Año *"), {
    target: { value: "2025.5" },
  });
  save();
  await screen.findByText("Año del vehículo inválido.");
  expect(vehicles.update).not.toHaveBeenCalled();
});
it("locks the vehicle draft and preserves the loaded revision while saving", async () => {
  const pending = deferred<Vehicle>();
  vehicles.update.mockReturnValueOnce(pending.promise);
  render(<VehicleEditor />);
  await screen.findByDisplayValue("Modelo");
  save();
  expect(screen.getByLabelText("Modelo *")).toBeDisabled();
  expect(vehicles.update).toHaveBeenCalledWith(
    vehicle.id,
    expect.any(Object),
    vehicle.edit_revision,
  );
  await act(async () => pending.resolve(vehicle));
});
it.each([
  [VehicleEditor, "Modelo"],
  [ZoneEditor, "Centro"],
] as const)(
  "cancels the delayed success navigation on unmount",
  async (Component, value) => {
    jest.useFakeTimers();
    const { unmount } = render(<Component />);
    await screen.findByDisplayValue(value);
    save();
    await screen.findByText(/actualizad[ao] correctamente/);
    unmount();
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(mockRouter.push).not.toHaveBeenCalled();
  },
);
