import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Catalog from "@/app/(dashboard)/manager/fleet/riders/page";
import RegistrationPage from "@/app/(dashboard)/manager/fleet/riders/new/page";
import Registration from "@/components/riders/RiderRegistrationForm";
import { riderService } from "@/services/rider.service";
import { vehicleService, type Vehicle } from "@/services/vehicle.service";
import type { Rider } from "@/types/user";
import { storeTokens, clearStoredTokens } from "@/lib/auth-session";
import { riderFormSchema } from "@/lib/rider-validation";

const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockUser: { id: string; role: string } | null = {
    id: "manager",
    role: "GERENTE",
  },
  mockAuthenticated = true;
const mockCreate = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/stores/ridersStore", () => ({
  useRidersStore: () => ({ createRider: mockCreate }),
}));
jest.mock("@/services/rider.service", () => ({
  riderService: { getAll: jest.fn() },
}));
jest.mock("@/services/vehicle.service", () => ({
  vehicleService: { getAvailableCompanyVehicles: jest.fn() },
}));
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/components/ui/select", () => ({
  Select: ({ children, value, onValueChange, disabled }: any) => (
    <select
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
  SelectItem: ({ children, value, disabled }: any) => (
    <option value={value} disabled={disabled}>
      {children}
    </option>
  ),
}));
const riders = jest.mocked(riderService),
  vehicles = jest.mocked(vehicleService);
const row = {
  id: "actual-rider",
  user_id: "actual-user",
  first_name: "José",
  last_name: "Pérez",
  email: "rider@example.test",
  phone: "04121234567",
  vehicle_ownership_type: "PROPIO",
  vehicle_type: "MOTO",
  vehicle_plate: "ABC-1",
  status: "ACTIVO",
  is_online: false,
} as Rider;
const vehicle = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  revision: "a".repeat(64),
  plate: "COMPANY",
  type: "MOTO",
  model: "Modelo",
  year: 2026,
  color: "Azul",
  status: "ACTIVO",
  created_at: "2026-01-01",
} as Vehicle;
const valid = {
  fullName: "José Pérez",
  email: "rider@example.test",
  phone: "04121234567",
  cpf: "123456789",
  vehicleOwnershipType: "PROPIO",
  vehicleType: "MOTO",
  vehiclePlate: "ABC-1",
  assignedVehicleId: "",
  operatingZone: "Centro",
  password: "ValidPassword123!",
};
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fill() {
  for (const [label, value] of [
    ["Nombre Completo", valid.fullName],
    ["Email", valid.email],
    ["Teléfono", valid.phone],
    ["CPF / Documento", valid.cpf],
    ["Zona de Operación", valid.operatingZone],
    ["Contraseña Temporal", valid.password],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function ownership(value: string) {
  fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value } });
}
beforeEach(() => {
  jest.clearAllMocks();
  mockUser = { id: "manager", role: "GERENTE" };
  mockAuthenticated = true;
  storeTokens({ access_token: "test-token", refresh_token: "test-refresh" });
  riders.getAll.mockResolvedValue([row]);
  vehicles.getAvailableCompanyVehicles.mockResolvedValue([vehicle]);
  mockCreate.mockResolvedValue(row);
});
afterEach(() => {
  clearStoredTokens();
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it.each(["OPERADOR", "GERENTE", "SUPERADMIN"])(
  "allows %s to read but only managers to create",
  async (role) => {
    mockUser = { id: "staff", role };
    render(<Catalog />);
    await screen.findByRole("article");
    expect(!!screen.queryByRole("link", { name: "Nuevo Repartidor" })).toBe(
      role !== "OPERADOR",
    );
    expect(vehicles.getAvailableCompanyVehicles).not.toHaveBeenCalled();
  },
);
it.each(["CLIENTE", "AUDITOR", "REPARTIDOR"])(
  "does not start private catalog reads for %s",
  async (role) => {
    mockUser = { id: "denied", role };
    render(<Catalog />);
    await waitFor(() =>
      expect(mockRouter.replace).toHaveBeenCalledWith("/login"),
    );
    expect(riders.getAll).not.toHaveBeenCalled();
  },
);
it("does not invent pending status or offline availability", async () => {
  riders.getAll.mockResolvedValue([
    { ...row, status: null as never, is_online: null as never },
  ]);
  render(<Catalog />);
  const card = await screen.findByRole("article");
  expect(within(card).getByText("Estado no informado")).toBeInTheDocument();
  expect(
    within(card).getByText("Disponibilidad no informada"),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Estado registrado"), {
    target: { value: "PENDIENTE" },
  });
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
});
it("uses the assigned vehicle embedded in the rider, not the available fleet", async () => {
  riders.getAll.mockResolvedValue([
    {
      ...row,
      vehicle_ownership_type: "EMPRESA",
      assigned_vehicle_id: vehicle.id,
      assigned_vehicle: vehicle,
      vehicle_plate: "STALE",
    },
  ]);
  render(<Catalog />);
  const card = await screen.findByRole("article");
  expect(within(card).getByText("COMPANY")).toBeInTheDocument();
  expect(within(card).queryByText("STALE")).not.toBeInTheDocument();
});
it("does not display a vehicle with a contradictory assignment ID", async () => {
  riders.getAll.mockResolvedValue([
    {
      ...row,
      vehicle_ownership_type: "EMPRESA",
      assigned_vehicle_id: "different",
      assigned_vehicle: vehicle,
      vehicle_plate: "STALE",
    },
  ]);
  render(<Catalog />);
  const card = await screen.findByRole("article");
  expect(within(card).getByText("Placa no informada")).toBeInTheDocument();
  expect(within(card).queryByText("COMPANY")).not.toBeInTheDocument();
});
it("searches accents, telephone and ID locally and retains real profile links", async () => {
  render(<Catalog />);
  await screen.findByRole("article");
  const search = screen.getByLabelText(
    "Buscar por nombre, contacto, placa o ID",
  );
  for (const term of ["jose", "041212", "actual-rider"]) {
    fireEvent.change(search, { target: { value: term } });
    expect(screen.getByRole("article")).toBeInTheDocument();
  }
  expect(riders.getAll).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("link", { name: "Ver documentos de actual-rider" }),
  ).toHaveAttribute("href", "/manager/fleet/riders/actual-rider/documents");
});
it("preserves the last confirmed catalog on a failed refresh", async () => {
  render(<Catalog />);
  await screen.findByRole("article");
  riders.getAll.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("article")).toBeInTheDocument();
  expect(
    within(screen.getByRole("alert")).getByText(/última consulta confirmada/),
  ).toBeInTheDocument();
});
it("distinguishes an unavailable first read from a confirmed empty response", async () => {
  riders.getAll.mockRejectedValueOnce(new Error("offline"));
  render(<Catalog />);
  await screen.findByRole("alert");
  expect(
    screen.queryByText("La consulta no devolvió repartidores."),
  ).not.toBeInTheDocument();
  riders.getAll.mockResolvedValueOnce([]);
  fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
  await screen.findByText("La consulta no devolvió repartidores.");
});
it("retires an old catalog when credentials and account change", async () => {
  const old = deferred<Rider[]>();
  riders.getAll.mockReturnValueOnce(old.promise);
  const { rerender } = render(<Catalog />);
  mockUser = { id: "other-manager", role: "GERENTE" };
  riders.getAll.mockResolvedValueOnce([
    { ...row, id: "other-rider", first_name: "Nueva" },
  ]);
  act(() =>
    storeTokens({ access_token: "new-token", refresh_token: "new-refresh" }),
  );
  rerender(<Catalog />);
  await screen.findByRole("article", { name: "Repartidor other-rider" });
  await act(async () => old.resolve([row]));
  expect(
    screen.queryByRole("article", { name: "Repartidor actual-rider" }),
  ).not.toBeInTheDocument();
});
it("limits registration access to managers", async () => {
  mockUser = { id: "operator", role: "OPERADOR" };
  render(<RegistrationPage />);
  await waitFor(() =>
    expect(mockRouter.replace).toHaveBeenCalledWith("/login"),
  );
  expect(
    screen.queryByRole("button", { name: "Registrar Repartidor" }),
  ).not.toBeInTheDocument();
});
it("sends the trimmed document and actual name without an unsupported birth date", async () => {
  render(<Registration />);
  fill();
  fireEvent.change(screen.getByLabelText("Nombre Completo"), {
    target: { value: "  José   Pérez  " },
  });
  fireEvent.change(screen.getByLabelText("CPF / Documento"), {
    target: { value: " 123456789 " },
  });
  expect(
    screen.queryByLabelText("Fecha de Nacimiento"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await waitFor(() =>
    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        first_name: "José",
        last_name: "Pérez",
        cpf: "123456789",
      }),
    ),
  );
  expect(mockCreate.mock.calls[0][0]).not.toHaveProperty("birthDate");
});
it.each([
  ["fullName", "   "],
  ["fullName", "Monónimo"],
  ["fullName", `${"A".repeat(101)} Pérez`],
  ["cpf", "123"],
  ["cpf", "1".repeat(15)],
  ["password", "1234567"],
  ["password", "        "],
  ["operatingZone", "   "],
] as const)("rejects invalid %s before building a rider", (field, value) => {
  expect(riderFormSchema.safeParse({ ...valid, [field]: value }).success).toBe(
    false,
  );
});
it("accepts trimmed supported fields and an eight-character password", () => {
  const parsed = riderFormSchema.parse({
    ...valid,
    email: " rider@example.test ",
    password: "12345678",
  });
  expect(parsed.email).toBe("rider@example.test");
});
it("requires a company vehicle selection in the shared form contract", () => {
  expect(
    riderFormSchema.safeParse({
      ...valid,
      vehicleOwnershipType: "EMPRESA",
      assignedVehicleId: "",
    }).success,
  ).toBe(false);
});
it("distinguishes vehicle lookup errors from confirmed lack of available vehicles", async () => {
  vehicles.getAvailableCompanyVehicles.mockRejectedValueOnce(
    new Error("offline"),
  );
  render(<Registration />);
  ownership("EMPRESA");
  await screen.findByRole("alert");
  expect(
    screen.queryByText("No hay vehículos disponibles"),
  ).not.toBeInTheDocument();
  vehicles.getAvailableCompanyVehicles.mockResolvedValueOnce([]);
  fireEvent.click(screen.getByRole("button", { name: "Recargar vehículos" }));
  await screen.findByText("No hay vehículos disponibles");
});
it("retains the selected snapshot when a select emits an empty value during option changes", async () => {
  render(<Registration />);
  fill();
  ownership("EMPRESA");
  await screen.findByRole("option", { name: /COMPANY/ });
  fireEvent.change(screen.getAllByRole("combobox")[1], {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await waitFor(() =>
    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        assigned_vehicle_id: vehicle.id,
        expected_vehicle_revision: vehicle.revision,
      }),
    ),
  );
});
it("ignores an obsolete company lookup after changing ownership twice", async () => {
  const old = deferred<Vehicle[]>();
  vehicles.getAvailableCompanyVehicles
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce([{ ...vehicle, plate: "LATEST" }]);
  render(<Registration />);
  ownership("EMPRESA");
  ownership("PROPIO");
  ownership("EMPRESA");
  await screen.findByRole("option", { name: /LATEST/ });
  await act(async () => old.resolve([{ ...vehicle, plate: "OBSOLETE" }]));
  expect(
    screen.queryByRole("option", { name: /OBSOLETE/ }),
  ).not.toBeInTheDocument();
});
it("locks the submitted draft and prevents a duplicate after successful creation", async () => {
  const pending = deferred<Rider>();
  mockCreate.mockReturnValueOnce(pending.promise);
  render(<Registration />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await waitFor(() => expect(screen.getByLabelText("Email")).toBeDisabled());
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeDisabled();
  await act(async () => pending.resolve(row));
  expect(
    screen.getByRole("button", { name: "Repartidor registrado" }),
  ).toBeDisabled();
  expect(mockCreate).toHaveBeenCalledTimes(1);
});
it("does not report a completed create as failed when the consumer callback throws", async () => {
  render(
    <Registration
      onSuccess={() => {
        throw new Error("navigation");
      }}
    />,
  );
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await screen.findByText("Repartidor registrado correctamente.");
  expect(
    screen.getByRole("button", { name: "Repartidor registrado" }),
  ).toBeDisabled();
  expect(mockCreate).toHaveBeenCalledTimes(1);
});
it("retires a late create result after unmount", async () => {
  const pending = deferred<Rider>();
  mockCreate.mockReturnValueOnce(pending.promise);
  const success = jest.fn();
  const { unmount } = render(<Registration onSuccess={success} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
  unmount();
  await act(async () => pending.resolve(row));
  expect(success).not.toHaveBeenCalled();
});
it("clears a registration redirect timer on unmount", async () => {
  jest.useFakeTimers();
  const { unmount } = render(<RegistrationPage />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Registrar Repartidor" }));
  await screen.findByText("Repartidor registrado correctamente.");
  unmount();
  act(() => {
    jest.advanceTimersByTime(1500);
  });
  expect(mockRouter.push).not.toHaveBeenCalled();
});
