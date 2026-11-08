import { act, renderHook } from "@testing-library/react";
import useGeolocation from "@/hooks/useGeolocation";
let success: PositionCallback,
  failure: PositionErrorCallback,
  geo: {
    watchPosition: jest.Mock;
    getCurrentPosition: jest.Mock;
    clearWatch: jest.Mock;
  };
const original = Object.getOwnPropertyDescriptor(navigator, "geolocation");
const point = (changes: Record<string, unknown> = {}) =>
  ({
    coords: {
      latitude: 0,
      longitude: 0,
      accuracy: 0,
      altitude: null,
      heading: 0,
      speed: 0,
      ...changes,
    },
    timestamp: Date.now(),
  }) as GeolocationPosition;
beforeEach(() => {
  jest.useFakeTimers();
  geo = {
    watchPosition: jest.fn((a, b) => {
      success = a;
      failure = b;
      return 0;
    }),
    getCurrentPosition: jest.fn((a, b) => {
      success = a;
      failure = b;
    }),
    clearWatch: jest.fn(),
  };
  Object.defineProperty(navigator, "geolocation", {
    value: geo,
    configurable: true,
  });
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
  if (original) Object.defineProperty(navigator, "geolocation", original);
  else delete (navigator as unknown as Record<string, unknown>).geolocation;
});
it("starts a GPS watch with explicit defaults and preserves zero coordinates, accuracy and heading", () => {
  const { result } = renderHook(() => useGeolocation());
  expect(geo.watchPosition).toHaveBeenCalledWith(
    expect.any(Function),
    expect.any(Function),
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 5000 },
  );
  expect(result.current.loading).toBe(true);
  act(() => success(point()));
  expect(result.current).toMatchObject({
    latitude: 0,
    longitude: 0,
    accuracy: 0,
    speed: 0,
    heading: 0,
    error: null,
    loading: false,
    isSupported: true,
  });
  expect(result.current.getBearing()).toBe(0);
  expect(result.current.calculateDistance(0, 0)).toBe(0);
  expect(result.current.calculateDistance(0, 180)).toBeCloseTo(20015086.796, 2);
});
it("reports unavailable GPS without attempting to call a missing browser API", () => {
  Object.defineProperty(navigator, "geolocation", {
    value: undefined,
    configurable: true,
  });
  const { result } = renderHook(() => useGeolocation());
  expect(result.current.isSupported).toBe(false);
  expect(result.current.error?.code).toBe(0);
  expect(result.current.loading).toBe(false);
});
it("does not start manually disabled collection and can request a single reading", () => {
  const { result } = renderHook(() =>
    useGeolocation({
      autoStart: false,
      watchPosition: false,
      timeout: 10,
      maximumAge: 0,
      enableHighAccuracy: false,
    }),
  );
  expect(geo.watchPosition).not.toHaveBeenCalled();
  act(() => result.current.startWatching());
  expect(geo.getCurrentPosition).toHaveBeenCalledWith(
    expect.any(Function),
    expect.any(Function),
    { timeout: 10, maximumAge: 0, enableHighAccuracy: false },
  );
  act(() => success(point({ heading: null, speed: null, altitude: -30 })));
  expect(result.current.getBearing()).toBeNull();
  expect(result.current.position?.altitude).toBe(-30);
});
it.each([
  [1, "Permiso denegado"],
  [2, "Ubicación no disponible"],
  [3, "Tiempo de espera"],
  [9, "Error desconocido"],
])("reports browser error %s and can recover", (code, message) => {
  const { result } = renderHook(() => useGeolocation());
  act(() => failure({ code } as GeolocationPositionError));
  expect(result.current.error?.message).toContain(message);
  expect(result.current.loading).toBe(false);
  act(() => success(point()));
  expect(result.current.error).toBeNull();
});
it("invalidates old callbacks after stop, restart and unmount, including watch ID zero", () => {
  const callback = jest.fn(),
    { result, unmount } = renderHook(() => useGeolocation());
  act(() => result.current.setCallback(callback));
  const retired = success;
  act(() => result.current.stopWatching());
  expect(geo.clearWatch).toHaveBeenCalledWith(0);
  act(() => retired(point()));
  expect(result.current.position).toBeNull();
  expect(callback).not.toHaveBeenCalled();
  act(() => result.current.startWatching());
  const live = success;
  act(() => retired(point()));
  expect(callback).not.toHaveBeenCalled();
  act(() => live(point()));
  expect(callback).toHaveBeenCalledTimes(1);
  unmount();
  act(() => live(point()));
  expect(callback).toHaveBeenCalledTimes(1);
});
it("clears refresh timers so unmount cannot restart GPS in the background", () => {
  const { result, unmount } = renderHook(() => useGeolocation());
  act(() => result.current.refreshPosition());
  expect(geo.clearWatch).toHaveBeenCalledWith(0);
  unmount();
  act(() => jest.advanceTimersByTime(200));
  expect(geo.watchPosition).toHaveBeenCalledTimes(1);
});
it("refreshes explicitly and lets stop cancel a pending restart", () => {
  const { result } = renderHook(() => useGeolocation());
  act(() => result.current.refreshPosition());
  act(() => jest.advanceTimersByTime(200));
  expect(geo.watchPosition).toHaveBeenCalledTimes(2);
  act(() => {
    result.current.refreshPosition();
    result.current.stopWatching();
    jest.advanceTimersByTime(200);
  });
  expect(geo.watchPosition).toHaveBeenCalledTimes(2);
});
it("replaces the watch when active options change and retires the previous reading", () => {
  const { result, rerender } = renderHook(
    ({ timeout }) => useGeolocation({ timeout }),
    { initialProps: { timeout: 10 } },
  );
  const old = success;
  rerender({ timeout: 20 });
  expect(geo.clearWatch).toHaveBeenCalled();
  act(() => old(point()));
  expect(result.current.position).toBeNull();
  act(() => success(point()));
  expect(result.current.position?.latitude).toBe(0);
});
it.each([
  { latitude: 91 },
  { longitude: 181 },
  { latitude: NaN },
  { accuracy: -1 },
  { accuracy: Infinity },
])("does not publish invalid position %j", (changes) => {
  const callback = jest.fn(),
    { result } = renderHook(() => useGeolocation());
  act(() => result.current.setCallback(callback));
  act(() => success(point(changes)));
  expect(result.current.error?.message).toContain("inválidas");
  expect(callback).not.toHaveBeenCalled();
});
it("normalizes unavailable optional telemetry and contains callback failures", () => {
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  const { result } = renderHook(() => useGeolocation());
  act(() =>
    result.current.setCallback(() => {
      throw new Error("private callback failure");
    }),
  );
  act(() => success(point({ heading: NaN, speed: -1, altitude: Infinity })));
  expect(result.current).toMatchObject({
    heading: null,
    speed: null,
    error: null,
  });
  expect(result.current.position?.altitude).toBeNull();
  expect(console.error).toHaveBeenCalledWith(
    "Error en callback de geolocalización",
  );
});
it("contains browser API exceptions and missing/invalid distance inputs", () => {
  geo.watchPosition.mockImplementation(() => {
    throw new Error("browser denied");
  });
  const { result } = renderHook(() => useGeolocation());
  expect(result.current.error?.message).toContain("No se pudo iniciar");
  expect(result.current.calculateDistance(0, 0)).toBe(-1);
  expect(result.current.getBearing()).toBeNull();
});
it.each([
  [91, 0],
  [0, 181],
  [NaN, 0],
  [0, Infinity],
])("rejects invalid destination %s/%s", (lat, lng) => {
  const { result } = renderHook(() => useGeolocation());
  act(() => success(point()));
  expect(result.current.calculateDistance(lat, lng)).toBe(-1);
});
