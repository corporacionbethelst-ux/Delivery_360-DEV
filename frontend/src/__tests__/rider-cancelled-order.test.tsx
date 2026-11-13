import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import RiderOrder from "@/app/(dashboard)/rider/my-orders/[id]/page";
import { orderService } from "@/services/order.service";
import { deliveryService } from "@/services/delivery.service";

jest.mock("next/navigation", () => ({
  useParams: () => ({ id: "order-1" }),
  useRouter: () => ({ push: jest.fn() }),
}));
jest.mock("@/services/order.service", () => ({
  orderService: { getById: jest.fn() },
}));
jest.mock("@/services/delivery.service", () => ({
  deliveryService: { updateStatus: jest.fn(), failDelivery: jest.fn() },
}));

afterEach(() => jest.restoreAllMocks());
beforeEach(() => jest.clearAllMocks());

it.each([
  ["CANCELADO", "CANCELADA"],
  ["CANCELADO", "EN_ROUTE"],
  ["ASIGNADO", "CANCELADA"],
  ["ASIGNADO", "CANCELADO"],
])(
  "closes rider actions for order %s / delivery %s, including historical partial records",
  async (status, deliveryStatus) => {
    jest.mocked(orderService.getById).mockResolvedValue({
      id: "order-1",
      status,
      customer_name: "Cliente",
      customer_phone: "123",
      pickup_address: "Origen",
      delivery_address: "Destino",
      cancellation_reason: "Cliente solicita cancelar su pedido",
      delivery: { id: "delivery-1", status: deliveryStatus },
    } as any);
    render(<RiderOrder />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Las acciones de entrega están cerradas",
    );
    expect(
      screen.getByText("Motivo: Cliente solicita cancelar su pedido"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Acciones de Entrega")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Cancelada: sin bono de entrega/),
    ).toBeInTheDocument();
  },
);

it.each(["INICIADA", "EN_PICKUP"])(
  "reports a closed pickup business from %s without pretending departure",
  async (status) => {
    jest.spyOn(window, "alert").mockImplementation(() => undefined);
    const order = {
      id: "order-1",
      status: "ASIGNADO",
      customer_name: "Cliente",
      customer_phone: "123",
      pickup_address: "Origen",
      delivery_address: "Destino",
      delivery: { id: "delivery-1", status },
    };
    jest
      .mocked(orderService.getById)
      .mockResolvedValueOnce(order as any)
      .mockResolvedValue({
        ...order,
        status: "FALLIDO",
        delivery: {
          id: "delivery-1",
          status: "FALLIDA",
          locked_bonus_amount: 1,
          locked_bonus_type: "FAILED_ATTEMPT",
        },
      } as any);
    jest.mocked(deliveryService.failDelivery).mockResolvedValue({} as any);
    render(<RiderOrder />);
    const report = await screen.findByRole("button", {
      name: "Reportar Fallo",
    });
    expect(report).toBeEnabled();
    fireEvent.click(report);
    expect(
      screen.getByRole("dialog", { name: "Reportar Entrega Fallida" }),
    ).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirmar Reporte" });
    expect(confirm).toBeDisabled();
    fireEvent.change(
      screen.getByRole("combobox", { name: /Causa del fallo/ }),
      { target: { value: "COMERCIO_CERRADO" } },
    );
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(deliveryService.failDelivery).toHaveBeenCalledWith(
        "delivery-1",
        "COMERCIO_CERRADO",
        "",
      ),
    );
    expect(deliveryService.failDelivery).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(deliveryService.updateStatus).not.toHaveBeenCalled();
  },
);
