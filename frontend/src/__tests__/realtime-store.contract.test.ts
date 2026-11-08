import { useRealtimeStore as store } from "@/stores/realtimeStore";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import type { Order } from "@/types/order";
import type { Delivery } from "@/types/delivery";
import type { Rider } from "@/types/user";
import type { Alert } from "@/types/alerts";
const order = (status: string, id = "o") => ({ id, status }) as Order,
  delivery = (status: string, id = "d") => ({ id, status }) as Delivery,
  rider = (is_online: boolean, status = "ACTIVO", id = "r") =>
    ({ id, is_online, status }) as Rider,
  alert = (id = "a") => ({ id, title: "Actual alert" }) as Alert;
beforeEach(() => {
  store.setState(store.getInitialState(), true);
  storeTokens({ access_token: "a", refresh_token: "ra" });
});
afterEach(() => clearStoredTokens());
it("distinguishes disconnected, connecting, connected and error without a false reconnect", () => {
  store.getState().connect();
  expect(store.getState()).toMatchObject({ isConnecting: true, error: null });
  store.getState().setConnected(true);
  expect(store.getState()).toMatchObject({
    isConnected: true,
    isConnecting: false,
    lastMessageAt: expect.any(Date),
  });
  store.getState().setConnected(false);
  expect(store.getState()).toMatchObject({
    isConnected: false,
    isConnecting: false,
    lastMessageAt: null,
  });
  store.getState().reconnect();
  expect(store.getState().isConnecting).toBe(true);
  store.getState().setError("offline");
  expect(store.getState()).toMatchObject({
    error: "offline",
    isConnecting: false,
  });
  store.getState().disconnect();
  expect(store.getState().isConnected).toBe(false);
});
it("updates existing orders and removes only the correct terminal order", () => {
  store.getState().updateOrder(order("PENDIENTE"));
  store.getState().updateOrder(order("ASIGNADO", "other"));
  store
    .getState()
    .updateOrder({ ...order("EN_RUTA"), customer_name: "Changed" } as Order);
  expect(store.getState().activeOrders).toHaveLength(2);
  expect(store.getState().activeOrders[0].status).toBe("EN_RUTA");
  store.getState().updateOrder(order("ENTREGADO"));
  expect(store.getState().activeOrders.map((x) => x.id)).toEqual(["other"]);
  store.getState().updateOrder(order("CANCELADO"));
  expect(store.getState().activeOrders.map((x) => x.id)).toEqual(["other"]);
});
it.each([
  "COMPLETADA",
  "FALLIDA",
  "CANCELADA",
  "ENTREGADO",
  "FALLIDO",
  "CANCELADO",
])("retires delivery terminal state %s without re-inserting it", (status) => {
  store.getState().updateDelivery(delivery("EN_ROUTE"));
  store.getState().updateDelivery(delivery("EN_ROUTE", "other"));
  store.getState().updateDelivery(delivery("EN_DESTINO"));
  expect(store.getState().activeDeliveries[0].status).toBe("EN_DESTINO");
  store.getState().updateDelivery(delivery(status));
  expect(store.getState().activeDeliveries.map((x) => x.id)).toEqual(["other"]);
  store.getState().updateDelivery(delivery(status));
  expect(store.getState().activeDeliveries.map((x) => x.id)).toEqual(["other"]);
});
it("updates rider availability and removes offline/inactive profiles without duplicates", () => {
  store.getState().updateRider(rider(true));
  store
    .getState()
    .updateRider({ ...rider(true), first_name: "Changed" } as Rider);
  expect(store.getState().onlineRiders).toHaveLength(1);
  store.getState().updateRider(rider(false));
  expect(store.getState().onlineRiders).toHaveLength(0);
  store.getState().updateRider(rider(true, "INACTIVO"));
  expect(store.getState().onlineRiders).toHaveLength(0);
  store.getState().updateRider(rider(true));
  store.getState().updateRider(rider(true, "INACTIVO"));
  expect(store.getState().onlineRiders).toHaveLength(0);
});
it("deduplicates, bounds and dismisses alert state", () => {
  for (let i = 0; i < 51; i++) store.getState().addAlert(alert(String(i)));
  expect(store.getState().alerts).toHaveLength(50);
  store.getState().addAlert(alert("50"));
  expect(store.getState().alerts).toHaveLength(50);
  store.getState().dismissAlert("50");
  expect(store.getState().alerts.some((x) => x.id === "50")).toBe(false);
});
it("clears all private state on credentials change while retaining callable actions", () => {
  store.getState().updateOrder(order("PENDIENTE"));
  store.getState().updateDelivery(delivery("INICIADA"));
  store.getState().updateRider(rider(true));
  store.getState().addAlert(alert());
  storeTokens({ access_token: "b", refresh_token: "rb" });
  expect(store.getState()).toMatchObject({
    activeOrders: [],
    activeDeliveries: [],
    onlineRiders: [],
    alerts: [],
  });
  expect(typeof store.getState().updateOrder).toBe("function");
  store.getState().updateOrder(order("PENDIENTE"));
  store.getState().clearAll();
  expect(store.getState().activeOrders).toEqual([]);
});
