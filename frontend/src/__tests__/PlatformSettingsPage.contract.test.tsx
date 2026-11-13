import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/manager/admin/settings/page";
import {
  settingsService,
  type PlatformSettings,
} from "@/services/settings.service";
import { storeTokens } from "@/lib/auth-session";
import { BonusSimulator } from "@/components/admin/BonusSimulator";
const mockRouter = { replace: jest.fn() };
let mockUser: { id: string; role: string } | null = {
    id: "admin",
    role: "SUPERADMIN",
  },
  mockAuthenticated = true;
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: mockAuthenticated }),
}));
jest.mock("@/services/settings.service", () => ({
  settingsService: {
    getSettings: jest.fn(),
    updateSettings: jest.fn(),
    simulateBonusImpact: jest.fn(),
  },
}));
const service = jest.mocked(settingsService),
  saved: PlatformSettings = {
    revision: "s1-" + "a".repeat(64),
    delivery_fee_base: 0,
    commission_percentage: 12.1234,
    min_order_amount: null,
    rider_delivery_bonus: 2.50001,
    rider_failed_attempt_bonus: 0,
    active_zones: ["Centro, Norte", "Sur"],
    support_email: null,
    maintenance_mode: false,
    updated_at: "2026-11-10T12:00:00",
    updated_by_user_id: "admin",
  };
const calculation = {
  current_monthly_cost: 100,
  projected_monthly_cost: 110,
  difference: 10,
  percentage_increase: 10,
  message: "Resultado del servidor",
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
  mockUser = { id: "admin", role: "SUPERADMIN" };
  mockAuthenticated = true;
  service.getSettings.mockResolvedValue(saved);
  service.updateSettings.mockResolvedValue({ ...saved, delivery_fee_base: 4 });
  service.simulateBonusImpact.mockResolvedValue(calculation);
});
const loaded = async () => {
  await screen.findByLabelText("Tarifa base de envío", { exact: false });
};
const field = (name: string) =>
  screen.getByRole("textbox", { name: new RegExp(`^${name}`) });
async function review() {
  fireEvent.change(field("Tarifa base de envío"), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar cambios" }));
  return screen.findByRole("dialog", {
    name: "Confirmar cambios de configuración",
  });
}
const simulate = () =>
  fireEvent.click(screen.getByRole("button", { name: "Simular impacto" }));

it("pausing the simulator retires its pending preflight before calculation", async () => {
  const pending = deferred<PlatformSettings>();
  service.getSettings.mockReturnValueOnce(pending.promise);
  const view = render(<BonusSimulator currentBase={2.50001} />);
  simulate();
  view.rerender(<BonusSimulator currentBase={2.50001} disabled />);
  await act(async () => pending.resolve(saved));
  expect(service.simulateBonusImpact).not.toHaveBeenCalled();
});

it("a late simulation from the previous account does not populate the new page", async () => {
  const pending = deferred<typeof calculation>();
  service.simulateBonusImpact.mockReturnValueOnce(pending.promise);
  const view = render(<Page />);
  await loaded();
  simulate();
  await waitFor(() =>
    expect(service.simulateBonusImpact).toHaveBeenCalledTimes(1),
  );
  mockUser = { id: "next-account", role: "SUPERADMIN" };
  view.rerender(<Page />);
  await act(async () => pending.resolve(calculation));
  expect(
    screen.queryByRole("region", {
      name: "Resultado confirmado de simulación",
    }),
  ).not.toBeInTheDocument();
});

it.each(["OPERADOR", "REPARTIDOR", "CLIENTE", "AUDITOR"])(
  "blocks %s before reading configuration",
  (role) => {
    mockUser = { id: "denied", role };
    render(<Page />);
    expect(service.getSettings).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/login");
  },
);
it("does not read configuration without confirmed authentication", () => {
  mockUser = null;
  mockAuthenticated = false;
  render(<Page />);
  expect(service.getSettings).not.toHaveBeenCalled();
});
it("keeps zero, null, exact precision and comma-containing zones in the loaded form", async () => {
  render(<Page />);
  await loaded();
  expect(field("Tarifa base de envío")).toHaveValue("0");
  expect(field("Pedido mínimo")).toHaveValue("");
  expect(field("Bono por entrega")).toHaveValue("2.50001");
  expect(field("Email de soporte")).toHaveValue("");
  expect(field("Zonas activas")).toHaveValue("Centro, Norte\nSur");
  expect(screen.getByLabelText("Bono propuesto")).toHaveValue("2.50001");
  expect(
    screen.getByRole("button", { name: "Revisar cambios" }),
  ).toBeDisabled();
});
it("manager can inspect and simulate but has no save control or editable settings", async () => {
  mockUser = { id: "manager", role: "GERENTE" };
  render(<Page />);
  await loaded();
  expect(field("Tarifa base de envío")).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Revisar cambios" }),
  ).not.toBeInTheDocument();
  simulate();
  await waitFor(() => expect(service.simulateBonusImpact).toHaveBeenCalled());
  expect(service.updateSettings).not.toHaveBeenCalled();
});
it("initial read error has retry and does not expose a default form", async () => {
  service.getSettings.mockRejectedValueOnce(new Error("read"));
  render(<Page />);
  await screen.findByText(/No se pudo confirmar la configuración/);
  expect(
    screen.queryByRole("textbox", { name: /^Tarifa base/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar configuración" }),
  );
  await loaded();
});
it("failed refresh preserves fields and reading time but locks editing until a confirmed retry", async () => {
  render(<Page />);
  await loaded();
  const before = screen.getByText(/Consulta confirmada:/).textContent;
  service.getSettings.mockRejectedValueOnce(new Error("read"));
  fireEvent.click(
    screen.getByRole("button", { name: "Recargar configuración" }),
  );
  await screen.findByText(/No se pudo confirmar la configuración/);
  expect(screen.getByText(/Consulta confirmada:/).textContent).toBe(before);
  expect(field("Tarifa base de envío")).toHaveValue("0");
  expect(field("Tarifa base de envío")).toBeDisabled();
});
it.each(["", "-1", "NaN"])(
  "invalid amount %j cannot create a save confirmation",
  async (value) => {
    render(<Page />);
    await loaded();
    fireEvent.change(field("Tarifa base de envío"), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Revisar cambios" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(service.updateSettings).not.toHaveBeenCalled();
  },
);
it("reviews the exact diff and cancels without issuing PATCH or another GET", async () => {
  render(<Page />);
  await loaded();
  const dialog = await review();
  expect(dialog).toHaveTextContent("Guardado: 0");
  expect(dialog).toHaveTextContent("Propuesto: 4");
  expect(within(dialog).queryByText("Comisión (%)")).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
  expect(service.getSettings).toHaveBeenCalledTimes(1);
  expect(service.updateSettings).not.toHaveBeenCalled();
  expect(field("Tarifa base de envío")).toHaveValue("4");
});
it("preflights the target values and sends only edited fields while preserving concurrent changes to others", async () => {
  render(<Page />);
  await loaded();
  const dialog = await review();
  service.getSettings.mockResolvedValueOnce({
    ...saved,
    revision: "s1-" + "b".repeat(64),
    commission_percentage: 17,
  });
  service.updateSettings.mockResolvedValueOnce({
    ...saved,
    delivery_fee_base: 4,
    commission_percentage: 17,
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirmar guardado" }),
  );
  await screen.findByText("Configuración guardada y confirmada correctamente.");
  expect(service.updateSettings).toHaveBeenCalledWith(
    { delivery_fee_base: 4 },
    "s1-" + "b".repeat(64),
  );
  expect(field("Comisión")).toHaveValue("17");
});
it("changed target values stop before PATCH and require reloading", async () => {
  render(<Page />);
  await loaded();
  const dialog = await review();
  service.getSettings.mockResolvedValueOnce({ ...saved, delivery_fee_base: 9 });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirmar guardado" }),
  );
  await within(dialog).findByText(/Alguno de los campos/);
  expect(service.updateSettings).not.toHaveBeenCalled();
  expect(
    within(dialog).getByRole("button", { name: "Recargar y revisar" }),
  ).toBeInTheDocument();
});
it("a server revision conflict keeps the draft, blocks retries and asks before discarding it", async () => {
  service.updateSettings.mockRejectedValueOnce({
    isAxiosError: true,
    response: { status: 412 },
  });
  render(<Page />);
  await loaded();
  const dialog = await review();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirmar guardado" }),
  );
  await within(dialog).findByText(/Otra persona cambió/);
  expect(
    screen.getByLabelText("Tarifa base de envío", { exact: false }),
  ).toHaveValue("4");
  expect(
    within(dialog).queryByRole("button", { name: "Confirmar guardado" }),
  ).not.toBeInTheDocument();
  expect(service.updateSettings).toHaveBeenCalledTimes(1);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Recargar y revisar" }),
  );
  const reload = await screen.findByRole("dialog", {
    name: "Recargar configuración",
  });
  fireEvent.click(
    within(reload).getByRole("button", { name: "Conservar borrador" }),
  );
  expect(field("Tarifa base de envío")).toHaveValue("4");
  expect(
    screen.getByRole("button", { name: "Revisar cambios" }),
  ).toBeDisabled();
  expect(service.getSettings).toHaveBeenCalledTimes(2);
});
it("pending save locks close and duplicates, then confirms the actual response", async () => {
  const pending = deferred<PlatformSettings>();
  service.updateSettings.mockReturnValueOnce(pending.promise);
  render(<Page />);
  await loaded();
  const dialog = await review(),
    confirm = within(dialog).getByRole("button", {
      name: "Confirmar guardado",
    });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(service.updateSettings).toHaveBeenCalledTimes(1));
  expect(
    within(dialog).getByRole("button", { name: "Cancelar" }),
  ).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => pending.resolve({ ...saved, delivery_fee_base: 4 }));
  await screen.findByText("Configuración guardada y confirmada correctamente.");
});
it.each(["rejected", "wrong-ack"])(
  "uncertain %s save does not announce success and requires a new read",
  async (kind) => {
    if (kind === "rejected")
      service.updateSettings.mockRejectedValueOnce(new Error("network"));
    else service.updateSettings.mockResolvedValueOnce(saved);
    render(<Page />);
    await loaded();
    const dialog = await review();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirmar guardado" }),
    );
    await within(dialog).findByRole("alert");
    expect(
      screen.queryByText("Configuración guardada y confirmada correctamente."),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Recargar y revisar" }),
    ).toBeInTheDocument();
  },
);
it("reloading a dirty form asks to preserve or discard the draft", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(field("Email de soporte"), {
    target: { value: "support@example.com" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Recargar configuración" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Recargar configuración",
  });
  expect(service.getSettings).toHaveBeenCalledTimes(1);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Conservar borrador" }),
  );
  expect(field("Email de soporte")).toHaveValue("support@example.com");
});
it("accepts zero proposal and binds a result to its actual request window", async () => {
  render(<Page />);
  await loaded();
  fireEvent.change(screen.getByLabelText("Bono propuesto"), {
    target: { value: "0" },
  });
  fireEvent.change(
    screen.getByLabelText("Días de histórico", { exact: false }),
    { target: { value: "7" } },
  );
  simulate();
  await screen.findByRole("region", {
    name: "Resultado confirmado de simulación",
  });
  expect(service.simulateBonusImpact).toHaveBeenCalledWith({
    new_base_bonus: 0,
    days_projection: 7,
  });
  expect(
    screen.getByText(/Resultado para bono 0 y 7 días/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/COP|Costo Mensual|2.500,00/),
  ).not.toBeInTheDocument();
});
it("missing saved bonus disables simulation without inventing a baseline", async () => {
  service.getSettings.mockResolvedValue({
    ...saved,
    rider_delivery_bonus: null,
  });
  render(<Page />);
  await loaded();
  expect(screen.getByLabelText("Bono propuesto")).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "Simular impacto" }),
  ).toBeDisabled();
  expect(service.simulateBonusImpact).not.toHaveBeenCalled();
});
it.each(["0", "91", "1.5", ""])(
  "invalid days %j cannot POST a simulation",
  async (value) => {
    render(<Page />);
    await loaded();
    fireEvent.change(
      screen.getByLabelText("Días de histórico", { exact: false }),
      { target: { value } },
    );
    simulate();
    await screen.findByRole("alert");
    expect(service.simulateBonusImpact).not.toHaveBeenCalled();
    expect(service.getSettings).toHaveBeenCalledTimes(1);
  },
);
it("simulation preflight stops when the saved base has changed", async () => {
  render(<Page />);
  await loaded();
  service.getSettings.mockResolvedValueOnce({
    ...saved,
    rider_delivery_bonus: 9,
  });
  simulate();
  await screen.findByText(/El bono guardado cambió/);
  expect(service.simulateBonusImpact).not.toHaveBeenCalled();
});
it("simulation blocks duplicates and pending inputs", async () => {
  const pending = deferred<typeof calculation>();
  service.simulateBonusImpact.mockReturnValueOnce(pending.promise);
  render(<Page />);
  await loaded();
  const button = screen.getByRole("button", { name: "Simular impacto" });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() =>
    expect(service.simulateBonusImpact).toHaveBeenCalledTimes(1),
  );
  expect(screen.getByLabelText("Bono propuesto")).toBeDisabled();
  await act(async () => pending.resolve(calculation));
  await screen.findByRole("region", {
    name: "Resultado confirmado de simulación",
  });
});
it("failed simulation preserves the old result and its actual proposal", async () => {
  render(<Page />);
  await loaded();
  simulate();
  await screen.findByRole("region", {
    name: "Resultado confirmado de simulación",
  });
  service.simulateBonusImpact.mockRejectedValueOnce(new Error("network"));
  fireEvent.change(screen.getByLabelText("Bono propuesto"), {
    target: { value: "9" },
  });
  simulate();
  await screen.findByRole("alert");
  expect(
    screen.getByText(/Resultado para bono 2.50001 y 30 días/),
  ).toBeInTheDocument();
});
it("zero historical cost is not displayed as a meaningful zero-percent base", async () => {
  service.simulateBonusImpact.mockResolvedValue({
    ...calculation,
    current_monthly_cost: 0,
    projected_monthly_cost: 10,
    difference: 10,
    percentage_increase: 0,
  });
  render(<Page />);
  await loaded();
  simulate();
  await screen.findByText("Sin base porcentual");
});
it.each(["account", "credentials"])(
  "retired %s preflight cannot proceed to PATCH",
  async (kind) => {
    const pending = deferred<PlatformSettings>();
    const view = render(<Page />);
    await loaded();
    const dialog = await review();
    service.getSettings.mockReturnValueOnce(pending.promise);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirmar guardado" }),
    );
    if (kind === "account") {
      mockUser = { id: "another", role: "SUPERADMIN" };
      view.rerender(<Page />);
    } else
      act(() =>
        storeTokens({
          access_token: "settings85-session",
          refresh_token: "settings85-refresh",
        }),
      );
    await act(async () => pending.resolve(saved));
    expect(service.updateSettings).not.toHaveBeenCalled();
  },
);
