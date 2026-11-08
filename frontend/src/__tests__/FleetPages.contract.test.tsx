import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Vehicles from "@/app/(dashboard)/manager/fleet/vehicles/page";
import NewVehicle from "@/app/(dashboard)/manager/fleet/vehicles/new/page";
import Zones from "@/app/(dashboard)/manager/fleet/zones/page";
import { vehicleService, type Vehicle } from "@/services/vehicle.service";
import { zoneService, type Zone } from "@/services/zone.service";

const mockRouter = { push: jest.fn(), back: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/services/vehicle.service", () => ({
  vehicleService: { getAll: jest.fn(), create: jest.fn() },
}));
jest.mock("@/services/zone.service", () => ({
  zoneService: { getAll: jest.fn(), create: jest.fn(), delete: jest.fn() },
}));
jest.mock("@/components/ui/select", () => ({
  Select: ({ children, value, disabled, onValueChange }: any) => (
    <select
      aria-label="Tipo de Vehículo"
      value={value}
      disabled={disabled}
      onChange={(e) => onValueChange(e.target.value)}
    >
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
  id: "123e4567-e89b-42d3-a456-426614174000",
  plate: "TEST-1",
  model: "Modelo",
  type: "MOTO",
  status: "ACTIVO",
  year: 2026,
  color: "Azul",
  insurance_expiry: null,
  created_at: "2026-01-01",
} as Vehicle;
const zone = {
  id: "123e4567-e89b-42d3-a456-426614174001",
  name: "Centro",
  code: "CTR",
  color_hex: "#3b82f6",
  is_active: true,
  is_priority: false,
  riders_count: 0,
  active_orders_count: 0,
  delivery_fee_base: 0,
  cost_per_km: 0,
  estimated_time_min: 30,
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
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  vehicles.getAll.mockResolvedValue([vehicle]);
  zones.getAll.mockResolvedValue([zone]);
  zones.create.mockResolvedValue(zone);
  zones.delete.mockResolvedValue(undefined as never);
});
afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

it("labels vehicle actions and distinguishes assigned names and unknown status", async () => {
  vehicles.getAll.mockResolvedValue([
    {
      ...vehicle,
      rider_id: "actual-rider",
      status: "FUTURO" as never,
      type: "OTRO" as never,
    },
  ]);
  render(<Vehicles />);
  expect(
    await screen.findByRole("button", { name: "Acciones de vehículo TEST-1" }),
  ).toBeEnabled();
  expect(
    screen.getByText("Nombre de repartidor no informado"),
  ).toBeInTheDocument();
  expect(screen.getByText("Fecha no informada")).toBeInTheDocument();
  expect(screen.getByText("FUTURO")).toBeInTheDocument();
  expect(screen.queryByText("Sin asignar")).not.toBeInTheDocument();
});
it("never presents a failed initial vehicle read as an empty inventory", async () => {
  vehicles.getAll.mockRejectedValueOnce(new Error("Sin conexión"));
  render(<Vehicles />);
  await screen.findByText(
    "El inventario no está confirmado. Reintenta la consulta para conocer los vehículos.",
  );
  expect(
    screen.queryByText("No se encontraron vehículos"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  await screen.findByText("TEST-1");
});
it("ignores a refresh that completes after the newer debounced search", async () => {
  jest.useFakeTimers();
  render(<Vehicles />);
  await screen.findByText("TEST-1");
  const old = deferred<Vehicle[]>();
  vehicles.getAll
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce([{ ...vehicle, plate: "LATEST" }]);
  fireEvent.change(
    screen.getByLabelText("Buscar vehículos por placa, modelo o repartidor"),
    { target: { value: "latest" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  await act(async () => {
    jest.advanceTimersByTime(350);
  });
  await screen.findByText("LATEST");
  await act(async () => old.resolve([{ ...vehicle, plate: "OBSOLETE" }]));
  expect(screen.queryByText("OBSOLETE")).not.toBeInTheDocument();
  expect(
    screen.getByText("Consulta cargada: tipo Todos; búsqueda latest."),
  ).toBeInTheDocument();
});
it("retains the confirmed vehicle query after a filter error", async () => {
  render(<Vehicles />);
  await screen.findByText("TEST-1");
  vehicles.getAll.mockRejectedValueOnce(new Error("Filtro no disponible"));
  fireEvent.change(screen.getByLabelText("Tipo de vehículo en la consulta"), {
    target: { value: "AUTO" },
  });
  await screen.findByText("Filtro no disponible");
  expect(screen.getByText("TEST-1")).toBeInTheDocument();
  expect(
    screen.getByText("Consulta cargada: tipo Todos; búsqueda Sin búsqueda."),
  ).toBeInTheDocument();
});
it("preserves zero zone values and explicitly reports unknown currency and missing counts", async () => {
  zones.getAll.mockResolvedValue([
    zone,
    {
      ...zone,
      id: "missing",
      name: "Sin datos",
      riders_count: null as never,
      active_orders_count: undefined as never,
      delivery_fee_base: undefined as never,
    },
  ]);
  render(<Zones />);
  const known = await screen.findByRole("article", { name: "Zona Centro" });
  expect(within(known).getAllByText("0")).toHaveLength(2);
  expect(
    within(known).getByText("0,00 (moneda no informada)"),
  ).toBeInTheDocument();
  const missing = screen.getByRole("article", { name: "Zona Sin datos" });
  expect(within(missing).getAllByText("No informado")).toHaveLength(2);
  expect(within(missing).getByText("Monto no informado")).toBeInTheDocument();
  expect(zones.getAll).toHaveBeenCalledWith({ limit: 100, page: 1 });
});
it("searches only loaded zones and exposes a bounded schematic with real links", async () => {
  zones.getAll.mockResolvedValue(
    Array.from({ length: 10 }, (_, i) => ({
      ...zone,
      id: `zone/${i}`,
      name: `Zona ${i}`,
      code: `Z${i}`,
    })),
  );
  render(<Zones />);
  await screen.findByRole("article", { name: "Zona Zona 0" });
  const preview = screen.getByRole("region", {
    name: "Vista esquemática de zonas",
  });
  expect(within(preview).getAllByRole("link")).toHaveLength(8);
  expect(
    within(preview).getByRole("link", { name: "Ver zona Zona 0" }),
  ).toHaveAttribute("href", "/manager/fleet/zones/zone%2F0");
  fireEvent.change(screen.getByLabelText("Buscar zonas por nombre o código"), {
    target: { value: "Z9" },
  });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(zones.getAll).toHaveBeenCalledTimes(1);
});
it("distinguishes failed zones from a confirmed empty response", async () => {
  zones.getAll.mockRejectedValueOnce(new Error("Sin conexión"));
  render(<Zones />);
  await screen.findByText("Consulta no confirmada");
  expect(screen.queryByText("No se encontraron zonas")).not.toBeInTheDocument();
  zones.getAll.mockResolvedValueOnce([]);
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  await screen.findByText("No se encontraron zonas");
});
it("names color choices, preserves a decimal zone fee and sends its selected color", async () => {
  render(<Zones />);
  await screen.findByRole("article");
  fireEvent.click(screen.getByRole("button", { name: "Nueva Zona" }));
  fireEvent.change(screen.getByLabelText("Nombre *"), {
    target: { value: "Nueva" },
  });
  fireEvent.change(screen.getByLabelText("Código *"), {
    target: { value: "nv" },
  });
  fireEvent.change(screen.getByLabelText("Tarifa Base"), {
    target: { value: "0.75" },
  });
  const color = screen.getByRole("button", { name: "Color Violeta" });
  fireEvent.click(color);
  expect(color).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Crear Zona" }));
  await waitFor(() =>
    expect(zones.create).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "NV",
        delivery_fee_base: 0.75,
        color_hex: "#a855f7",
      }),
    ),
  );
});
it("rejects whitespace-only zone names before calling the service", async () => {
  render(<Zones />);
  await screen.findByRole("article");
  fireEvent.click(screen.getByRole("button", { name: "Nueva Zona" }));
  fireEvent.change(screen.getByLabelText("Nombre *"), {
    target: { value: "   " },
  });
  fireEvent.change(screen.getByLabelText("Código *"), {
    target: { value: "XX" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Crear Zona" }));
  await screen.findByText("El nombre y el código son obligatorios.");
  expect(zones.create).not.toHaveBeenCalled();
});
it("locks the zone draft while its creation is pending", async () => {
  const pending = deferred<Zone>();
  zones.create.mockReturnValueOnce(pending.promise);
  render(<Zones />);
  await screen.findByRole("article");
  fireEvent.click(screen.getByRole("button", { name: "Nueva Zona" }));
  fireEvent.change(screen.getByLabelText("Nombre *"), {
    target: { value: "Nueva" },
  });
  fireEvent.change(screen.getByLabelText("Código *"), {
    target: { value: "XX" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Crear Zona" }));
  expect(screen.getByLabelText("Nombre *")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Color Azul" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeDisabled();
  await act(async () => pending.resolve(zone));
});
it("allows another zone deletion after the first confirmed operation completes", async () => {
  zones.getAll.mockResolvedValue([
    zone,
    { ...zone, id: "second", name: "Segunda" },
  ]);
  render(<Zones />);
  await screen.findByRole("article", { name: "Zona Centro" });
  fireEvent.click(screen.getByRole("button", { name: "Eliminar zona Centro" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Sí, eliminar",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Eliminar zona Segunda" }),
  );
  const confirm = within(screen.getByRole("dialog")).getByRole("button", {
    name: "Sí, eliminar",
  });
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(zones.delete).toHaveBeenNthCalledWith(2, "second"),
  );
});
it("rejects a fractional vehicle year before creating the vehicle", async () => {
  render(<NewVehicle />);
  for (const [label, value] of [
    ["Placa / Patente *", "AB-1"],
    ["Modelo *", "Modelo"],
    ["Color *", "Azul"],
    ["Año *", "2025.5"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "MOTO" } });
  fireEvent.submit(
    screen.getByRole("button", { name: "Guardar Vehículo" }).closest("form")!,
  );
  await screen.findByText(
    "Año inválido (debe ser entre 1900 y el año siguiente)",
  );
  expect(vehicles.create).not.toHaveBeenCalled();
});
