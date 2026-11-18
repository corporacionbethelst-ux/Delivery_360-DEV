import { act, fireEvent, render, screen } from "@testing-library/react";
import OrderDetail from "@/app/(dashboard)/operator/orders/[id]/page";
import DeliveryDetail from "@/app/(dashboard)/operator/deliveries/[id]/page";
import MyOrders from "@/app/(dashboard)/rider/my-orders/page";
import { orderService } from "@/services/order.service";
import { deliveryService } from "@/services/delivery.service";
import { priceOrder } from "@/lib/order-pricing";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";

let mockParams = { id: "order-a" };
let mockUser = { id: "operator-a", role: "OPERADOR" };
const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useParams: () => mockParams,
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ isAuthenticated: true, user: mockUser }),
}));
jest.mock("@/services/order.service", () => ({
  orderService: { getById: jest.fn(), getAll: jest.fn() },
}));
jest.mock("@/services/delivery.service", () => ({
  deliveryService: { getById: jest.fn() },
}));
const order = () => ({
  id: "order-a",
  external_id: "EXACT-107",
  status: "PENDIENTE",
  currency: "USD",
  created_at: "2026-11-17T10:00:00Z",
  delivery_address: "Destino de prueba",
  total: 999,
  subtotal: 888,
  items: [{ name: "Alias antiguo", price: 777 }],
  pricing: {
    ...priceOrder(
      [{ product_name: "Producto real", quantity: "3", unit_price: "0.10" }],
      "0.01",
    ),
    revision: 4,
  },
  delivery: { id: "delivery-a", order_id: "order-a", status: "PENDIENTE" },
});
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "ra" });
  mockUser = { id: "operator-a", role: "OPERADOR" };
  mockParams = { id: "order-a" };
  jest.mocked(orderService.getById).mockResolvedValue(order() as never);
  jest.mocked(orderService.getAll).mockResolvedValue([order()] as never);
  jest.mocked(deliveryService.getById).mockResolvedValue({
    id: "delivery-a",
    order_id: "order-a",
    status: "PENDIENTE",
    total_amount: 555,
    delivery_address: "Destino de entrega",
    started_at: null,
  } as never);
});
afterEach(() => clearStoredTokens());
it("operator order detail uses exact products, fee and total, never compatibility aliases", async () => {
  render(<OrderDetail />);
  expect(await screen.findByText("USD 0,31")).toBeInTheDocument();
  expect(screen.getByText("Producto real")).toBeInTheDocument();
  expect(screen.getByText("USD 0,01")).toBeInTheDocument();
  expect(
    screen.queryByText(/Alias antiguo|999|888|777/),
  ).not.toBeInTheDocument();
});
it("operator order detail handles an unavailable historic price without a synthetic total", async () => {
  jest
    .mocked(orderService.getById)
    .mockResolvedValue({ ...order(), pricing: null, currency: null } as never);
  render(<OrderDetail />);
  await screen.findByText(/Precio versionado no disponible/);
  expect(screen.queryByText(/USD|999|888|777/)).not.toBeInTheDocument();
});
it("operator order retry reads again after a rejected response", async () => {
  jest
    .mocked(orderService.getById)
    .mockRejectedValueOnce(new Error("Consulta interrumpida"));
  render(<OrderDetail />);
  await screen.findByText("Consulta interrumpida");
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  await screen.findByText("USD 0,31");
  expect(orderService.getById).toHaveBeenCalledTimes(2);
});
it("operator order rejects a wrong response identity even with a valid exact price", async () => {
  jest
    .mocked(orderService.getById)
    .mockResolvedValue({ ...order(), id: "other" } as never);
  render(<OrderDetail />);
  await screen.findByText("La respuesta pertenece a otra orden.");
  expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
});
it("delivery detail reads its linked order rather than nested or numeric delivery totals", async () => {
  mockParams = { id: "delivery-a" };
  render(<DeliveryDetail />);
  await screen.findByText("USD 0,31");
  expect(orderService.getById).toHaveBeenCalledWith("order-a");
  expect(screen.queryByText(/555|999/)).not.toBeInTheDocument();
});
it("delivery price failure preserves operational data and retries only the linked order", async () => {
  mockParams = { id: "delivery-a" };
  jest.mocked(orderService.getById).mockRejectedValueOnce(new Error("503"));
  render(<DeliveryDetail />);
  await screen.findByRole("alert");
  expect(screen.getByText("Destino de entrega")).toBeInTheDocument();
  expect(screen.queryByText(/USD|555/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar precio" }));
  await screen.findByText("USD 0,31");
  expect(deliveryService.getById).toHaveBeenCalledTimes(1);
  expect(orderService.getById).toHaveBeenCalledTimes(2);
});
it("delivery detail rejects a different delivery identity before loading any price", async () => {
  mockParams = { id: "delivery-a" };
  jest
    .mocked(deliveryService.getById)
    .mockResolvedValue({ id: "other", order_id: "order-a" } as never);
  render(<DeliveryDetail />);
  await screen.findByText("La respuesta pertenece a otra entrega.");
  expect(orderService.getById).not.toHaveBeenCalled();
});
it("rider list shows versioned zero and absence separately and never says the price is outstanding debt", async () => {
  mockUser = { id: "rider-a", role: "REPARTIDOR" };
  const zero = {
    ...order(),
    pricing: { ...priceOrder([], "0.00", "0.00"), revision: 2 },
  };
  jest.mocked(orderService.getAll).mockResolvedValue([
    zero,
    {
      ...order(),
      id: "old",
      external_id: "HISTORIC",
      pricing: null,
      currency: null,
    },
  ] as never);
  render(<MyOrders />);
  await screen.findByText("USD 0,00");
  expect(screen.getByText("Precio no disponible")).toBeInTheDocument();
  expect(screen.queryByText(/A cobrar|999|888/)).not.toBeInTheDocument();
});
it("rider initial read failure is visible and never becomes an empty assignment list", async () => {
  mockUser = { id: "rider-a", role: "REPARTIDOR" };
  jest.mocked(orderService.getAll).mockRejectedValueOnce(new Error("503"));
  render(<MyOrders />);
  await screen.findByRole("alert");
  expect(screen.queryByText("No tienes entregas aún")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  await screen.findByText("USD 0,31");
});
it("rider retains the confirmed list explicitly after refresh fails", async () => {
  mockUser = { id: "rider-a", role: "REPARTIDOR" };
  jest
    .mocked(orderService.getAll)
    .mockResolvedValueOnce([order()] as never)
    .mockRejectedValueOnce(new Error("503"));
  render(<MyOrders />);
  await screen.findByText("USD 0,31");
  fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "última lectura confirmada",
  );
  expect(screen.getByText("USD 0,31")).toBeInTheDocument();
});
it.each(["CLIENTE", "AUDITOR", "REPARTIDOR"])(
  "does not expose the operator price to %s",
  async (role) => {
    mockUser = { id: "other", role };
    render(<OrderDetail />);
    await act(async () => {});
    expect(orderService.getById).not.toHaveBeenCalled();
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
  },
);
it("ignores an old account's pending order read after credentials and identity change", async () => {
  let resolve!: (value: any) => void;
  jest
    .mocked(orderService.getById)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce({
      ...order(),
      pricing: null,
      currency: null,
    } as never);
  render(<OrderDetail />);
  await act(async () => {
    mockUser = { id: "operator-b", role: "OPERADOR" };
    storeTokens({ access_token: "b", refresh_token: "rb" });
  });
  await screen.findByText(/Precio versionado no disponible/);
  await act(async () => {
    resolve(order());
  });
  expect(screen.queryByText("USD 0,31")).not.toBeInTheDocument();
});

it("operator detail uses the canonical assigned rider instead of showing an assigned order as unassigned", async () => {
  jest
    .mocked(orderService.getById)
    .mockResolvedValue({
      ...order(),
      assigned_rider: {
        id: "rider-assigned",
        full_name: "Repartidora asignada",
      },
    } as never);
  render(<OrderDetail />);
  expect(await screen.findByText("Repartidora asignada")).toBeInTheDocument();
  expect(screen.queryByText("Sin asignar")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Ver Perfil" })).toHaveAttribute(
    "href",
    "/operator/riders/rider-assigned",
  );
});
