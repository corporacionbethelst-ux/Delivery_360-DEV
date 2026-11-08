import {
  act,
  renderHook,
  render,
  screen,
  fireEvent,
} from "@testing-library/react";
import { useSocket } from "@/hooks/useSocket";
import {
  NotificationProvider,
  useNotifications,
} from "@/contexts/NotificationContext";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
const originalUUID = Object.getOwnPropertyDescriptor(crypto, "randomUUID");
let ids = 0;
beforeEach(() => {
  ids = 0;
  Object.defineProperty(crypto, "randomUUID", {
    value: () => `local-${++ids}`,
    configurable: true,
  });
  jest.useFakeTimers();
  storeTokens({ access_token: "a", refresh_token: "ra" });
});
afterEach(() => {
  clearStoredTokens();
  jest.useRealTimers();
  if (originalUUID) Object.defineProperty(crypto, "randomUUID", originalUUID);
  else delete (crypto as unknown as Record<string, unknown>).randomUUID;
});
it("never fabricates a remote connection or random assigned orders", () => {
  const { result } = renderHook(() => useSocket());
  act(() => jest.advanceTimersByTime(120000));
  expect(result.current.isConnected).toBe(false);
  expect(result.current.notifications).toEqual([]);
  expect(result.current.unreadCount).toBe(0);
});
it("tracks only explicitly added local notifications with consistent read counts", () => {
  const { result } = renderHook(() => useSocket());
  act(() => {
    result.current.addNotification({
      title: "Local",
      message: "Local only",
      type: "INFO",
    });
    result.current.addNotification({
      title: "Other",
      message: "Local only",
      type: "WARNING",
    });
  });
  expect(result.current.unreadCount).toBe(2);
  const id = result.current.notifications[0].id;
  act(() => result.current.markAsRead(id));
  expect(result.current.unreadCount).toBe(1);
  act(() => result.current.markAsRead("missing"));
  expect(result.current.unreadCount).toBe(1);
  act(() => result.current.markAllAsRead());
  expect(result.current.unreadCount).toBe(0);
  act(() => result.current.clearNotifications());
  expect(result.current.notifications).toEqual([]);
});
it("bounds memory and clears private feed on credentials change", () => {
  const { result, unmount } = renderHook(() => useSocket());
  act(() => {
    for (let i = 0; i < 55; i++)
      result.current.addNotification({
        title: "Local",
        message: String(i),
        type: "INFO",
      });
  });
  expect(result.current.notifications).toHaveLength(50);
  act(() => storeTokens({ access_token: "b", refresh_token: "rb" }));
  expect(result.current.unreadCount).toBe(0);
  unmount();
  act(() => clearStoredTokens());
});
const Consumer = () => {
  const state = useNotifications();
  return (
    <>
      <p>{state.unreadCount}</p>
      <button onClick={() => state.markAllAsRead()}>Leer todas</button>
      <button onClick={() => state.markAsRead("missing")}>Leer una</button>
      <p>{state.isConnected ? "Conectado" : "Sin conexión"}</p>
    </>
  );
};
it("keeps legacy context read actions consistent with the same local feed", () => {
  render(
    <NotificationProvider>
      <Consumer />
    </NotificationProvider>,
  );
  expect(screen.getByText("Sin conexión")).toBeTruthy();
  fireEvent.click(screen.getByText("Leer todas"));
  fireEvent.click(screen.getByText("Leer una"));
  expect(screen.getByText("0")).toBeTruthy();
});
it("requires the provider explicitly", () => {
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  expect(() => renderHook(() => useNotifications())).toThrow(
    "NotificationProvider",
  );
  jest.restoreAllMocks();
});
