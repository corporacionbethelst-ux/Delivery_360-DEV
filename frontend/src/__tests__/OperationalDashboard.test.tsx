import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import OperationalDashboard from "@/components/dashboard/OperationalDashboard";
import ManagerDashboard from "@/components/dashboard/ManagerDashboard";
import OperatorDashboard from "@/components/dashboard/OperatorDashboard";
import { useAuthStore } from "@/stores/authStore";
import { storeTokens, clearStoredTokens } from "@/lib/auth-session";
import {
  DashboardSnapshot,
  getOperationalDashboard,
} from "@/services/operational-dashboard.service";
import { credentials, profile, deferred } from "../../test-utils/realtime";
import { dashboardSnapshot } from "../../test-utils/operational-dashboard";

jest.mock("@/services/operational-dashboard.service", () => ({
  getOperationalDashboard: jest.fn(),
}));
const get = jest.mocked(getOperationalDashboard);
beforeEach(() => {
  localStorage.clear();
  storeTokens(credentials);
  useAuthStore.setState({
    user: profile,
    isAuthenticated: true,
    sessionRevision: 1,
  });
  get.mockReset().mockResolvedValue(dashboardSnapshot());
});
afterEach(() => {
  cleanup();
  clearStoredTokens();
});

it("shows real totals and missing measurements without fabricated revenue or growth", async () => {
  render(<ManagerDashboard />);
  expect(await screen.findByTestId("Pedidos pendientes")).toHaveTextContent(
    "123",
  );
  expect(screen.getByTestId("SLA conocido")).toHaveTextContent("Sin datos");
  expect(screen.getByTestId("Entregas en curso")).toHaveTextContent("2");
  expect(screen.getByTestId("Turnos en curso")).toHaveTextContent("3");
  expect(screen.getByTestId("Repartidores disponibles")).toHaveTextContent("6");
  expect(screen.getByRole("link", { name: "Repartidores" })).toHaveAttribute(
    "href",
    "/manager/fleet/riders",
  );
  expect(
    screen.getByText("0 resultados conocidos · 3 sin dato"),
  ).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Actividad diaria" });
  expect(within(table).getByText("2026-10-29")).toBeInTheDocument();
  expect(within(table).getByText("5")).toBeInTheDocument();
  expect(
    screen.queryByText(/12[.,]5%|Ingresos totales|Total Revenue/),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Gestionar pedidos" }),
  ).toHaveAttribute("href", "/manager/operations/orders");
});

it("distinguishes measured zero from missing evidence", async () => {
  const data = dashboardSnapshot();
  data.summary.sla_percent = 0;
  data.summary.avg_delivery_minutes = 0;
  get.mockResolvedValueOnce(data);
  render(<OperationalDashboard mode="manager" />);
  expect(await screen.findByTestId("SLA conocido")).toHaveTextContent("0%");
  expect(screen.getByText("0 min")).toBeInTheDocument();
});

it("uses the shared real operator panel with explicit preview truncation", async () => {
  const data = dashboardSnapshot();
  data.queue_truncated = true;
  data.pending_orders = [
    {
      id: "order",
      number: "ORDER-1",
      status: "PENDIENTE",
      address: "Test destination",
      priority: null,
    },
  ];
  get.mockResolvedValueOnce(data);
  useAuthStore.setState({ user: { ...profile, role: "OPERADOR" } });
  render(<OperatorDashboard />);
  expect(await screen.findByText("Test destination")).toBeInTheDocument();
  expect(screen.getByTestId("Pedidos pendientes")).toHaveTextContent("123");
  expect(screen.getByText(/Se muestran los primeros 20/)).toBeInTheDocument();
  expect(screen.getByText(/últimos cinco minutos/)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Gestionar pedidos" }),
  ).toHaveAttribute("href", "/operator/orders");
});

it("renders an empty operator queue as an empty result", async () => {
  render(<OperationalDashboard mode="operator" />);
  expect(
    await screen.findByText("No hay pedidos en esta cola."),
  ).toBeInTheDocument();
});

it("changing period cancels and clears the previous panel until the replacement arrives", async () => {
  render(<OperationalDashboard mode="manager" />);
  await screen.findByTestId("Pedidos pendientes");
  const pending = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(pending.promise);
  fireEvent.change(screen.getByLabelText("Período"), {
    target: { value: "30" },
  });
  expect(screen.queryByTestId("Pedidos pendientes")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Consultando");
  await act(async () => pending.resolve(dashboardSnapshot()));
  expect(get).toHaveBeenLastCalledWith("manager", 30, expect.any(AbortSignal));
});

it("manual update can recover from a generic error", async () => {
  get.mockRejectedValueOnce(new Error("secret token"));
  render(<OperationalDashboard mode="manager" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "No se pudieron consultar",
  );
  expect(screen.queryByText("secret token")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  expect(await screen.findByTestId("Pedidos pendientes")).toHaveTextContent(
    "123",
  );
});

it("logout removes rendered private operational information", async () => {
  render(<OperationalDashboard mode="manager" />);
  await screen.findByTestId("Pedidos pendientes");
  act(() => useAuthStore.getState().forceLogout());
  expect(screen.queryByTestId("Pedidos pendientes")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "requiere acceso operativo",
  );
});
