import React from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { useOperationalDashboard } from "@/hooks/useOperationalDashboard";
import { useAuthStore } from "@/stores/authStore";
import {
  captureAuthSession,
  clearStoredTokens,
  commitRefreshedTokens,
  storeTokens,
} from "@/lib/auth-session";
import {
  DashboardSnapshot,
  getOperationalDashboard,
} from "@/services/operational-dashboard.service";
import { credentials, deferred, profile } from "../../test-utils/realtime";
import { dashboardSnapshot } from "../../test-utils/operational-dashboard";

jest.mock("@/services/operational-dashboard.service", () => ({
  getOperationalDashboard: jest.fn(),
}));
const get = jest.mocked(getOperationalDashboard);
beforeEach(() => {
  jest.useFakeTimers();
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
  jest.clearAllTimers();
  jest.useRealTimers();
});

it("publishes a complete snapshot and leaves unknown evidence null", async () => {
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  expect(result.current.loading).toBe(true);
  await act(async () => {});
  expect(result.current.data?.summary.pending_orders).toBe(123);
  expect(result.current.data?.summary.sla_percent).toBeNull();
  expect(result.current.loading).toBe(false);
});

it.each(["CLIENTE", "REPARTIDOR", "AUDITOR", "OPERADOR"] as const)(
  "does not request manager data for %s",
  async (role) => {
    // AUDITOR is a backend role outside the current frontend union; a runtime
    // profile carrying it must still fail the manager allowlist.
    useAuthStore.setState({
      user: { ...profile, role: role as typeof profile.role },
    });
    const { result } = renderHook(() => useOperationalDashboard("manager", 7));
    await act(async () => {});
    expect(result.current.allowed).toBe(false);
    expect(get).not.toHaveBeenCalled();
  },
);

it("allows the operator panel for an authenticated operator", async () => {
  useAuthStore.setState({ user: { ...profile, role: "OPERADOR" } });
  const { result } = renderHook(() => useOperationalDashboard("operator", 7));
  await act(async () => {});
  expect(result.current.data).not.toBeNull();
  expect(get).toHaveBeenCalledWith("operator", 7, expect.any(AbortSignal));
});

it("never requests without an authenticated profile or credentials", async () => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  const { result, rerender } = renderHook(() =>
    useOperationalDashboard("manager", 7),
  );
  await act(async () => {});
  expect(get).not.toHaveBeenCalled();
  act(() => {
    clearStoredTokens();
    useAuthStore.setState({ user: profile, isAuthenticated: true });
  });
  rerender();
  await act(async () => {});
  expect(get).not.toHaveBeenCalled();
  expect(result.current.error).toContain("sesión");
});

it("retires the old period immediately and ignores its delayed result", async () => {
  const old = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(old.promise);
  const { result, rerender } = renderHook(
    ({ days }) => useOperationalDashboard("manager", days),
    { initialProps: { days: 7 } },
  );
  const signal = get.mock.calls[0][2];
  rerender({ days: 30 });
  expect(signal?.aborted).toBe(true);
  expect(result.current.data).toBeNull();
  await act(async () => {});
  const outdated = dashboardSnapshot();
  outdated.summary.pending_orders = 999;
  await act(async () => old.resolve(outdated));
  expect(result.current.data?.summary.pending_orders).toBe(123);
});

it("hides data and cancels work on logout without anonymous retries", async () => {
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  await act(async () => {});
  expect(result.current.data).not.toBeNull();
  act(() => useAuthStore.getState().forceLogout());
  expect(result.current.data).toBeNull();
  expect(result.current.allowed).toBe(false);
  await act(async () => jest.advanceTimersByTime(60000));
  expect(get).toHaveBeenCalledTimes(1);
});

it("hides payloads immediately after role loss", async () => {
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  await act(async () => {});
  act(() => useAuthStore.setState({ user: { ...profile, role: "CLIENTE" } }));
  expect(result.current.data).toBeNull();
  expect(get).toHaveBeenCalledTimes(1);
});

it("old identity results cannot overwrite the new owner", async () => {
  const old = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(old.promise);
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  act(() => {
    storeTokens({
      access_token: "owner-b-access",
      refresh_token: "owner-b-refresh",
    });
    useAuthStore.setState({
      user: { ...profile, id: "owner-b" },
      sessionRevision: 2,
    });
  });
  await act(async () => {});
  const outdated = dashboardSnapshot();
  outdated.summary.pending_orders = 999;
  await act(async () => old.resolve(outdated));
  expect(result.current.data?.summary.pending_orders).toBe(123);
});

it("ordinary token rotation can complete the same current session", async () => {
  const pending = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  act(() =>
    commitRefreshedTokens(captureAuthSession(), {
      access_token: "rotated",
      refresh_token: "rotated-refresh",
    }),
  );
  await act(async () => pending.resolve(dashboardSnapshot()));
  expect(result.current.data).not.toBeNull();
  expect(get).toHaveBeenCalledTimes(1);
});

it("bounds ignored cancellation at fifteen seconds and rejects late results", async () => {
  const pending = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  await act(async () => jest.advanceTimersByTime(15000));
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toBeNull();
  expect(result.current.error).toContain("No se pudieron");
  expect(get.mock.calls[0][2]?.aborted).toBe(true);
  await act(async () => pending.resolve(dashboardSnapshot()));
  expect(result.current.data).toBeNull();
});

it("refresh replaces old data and errors expose no server diagnostics", async () => {
  const { result } = renderHook(() => useOperationalDashboard("manager", 7));
  await act(async () => {});
  get.mockRejectedValueOnce(new Error("private URL token customer address"));
  act(() => result.current.refresh());
  await act(async () => {});
  expect(result.current.data).toBeNull();
  expect(result.current.error).toContain("No se pudieron");
  expect(result.current.error).not.toContain("private");
  act(() => result.current.refresh());
  await act(async () => {});
  expect(result.current.data).not.toBeNull();
  expect(result.current.error).toBeNull();
});

it("unmount aborts all requests and releases its timeout", async () => {
  const pending = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(pending.promise);
  const { unmount } = renderHook(() => useOperationalDashboard("manager", 7));
  const signal = get.mock.calls[0][2];
  unmount();
  await act(async () => {});
  expect(signal?.aborted).toBe(true);
  expect(jest.getTimerCount()).toBe(0);
  await act(async () => pending.resolve(dashboardSnapshot()));
});

it("StrictMode cannot publish the discarded first request", async () => {
  const pending = deferred<DashboardSnapshot>();
  get.mockReturnValueOnce(pending.promise);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <React.StrictMode>{children}</React.StrictMode>
  );
  const { result } = renderHook(() => useOperationalDashboard("manager", 7), {
    wrapper,
  });
  const outdated = dashboardSnapshot();
  outdated.summary.pending_orders = 999;
  await act(async () => pending.resolve(outdated));
  expect(result.current.data?.summary.pending_orders).toBe(123);
});
