import { act, renderHook } from "@testing-library/react";
import { useSidebar } from "@/hooks/useSidebar";
const width = window.innerWidth;
beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", {
    value: 1200,
    configurable: true,
    writable: true,
  });
});
afterEach(() => {
  jest.restoreAllMocks();
  Object.defineProperty(window, "innerWidth", {
    value: width,
    configurable: true,
    writable: true,
  });
});
it("restores desktop preference, toggles and handles two rapid actions", () => {
  localStorage.setItem("sidebar-collapsed", "true");
  const { result } = renderHook(() => useSidebar());
  expect(result.current).toMatchObject({
    isMounted: true,
    isMobile: false,
    isCollapsed: true,
  });
  act(() => result.current.toggle());
  expect(result.current.isCollapsed).toBe(false);
  expect(localStorage.getItem("sidebar-collapsed")).toBe("false");
  act(() => {
    result.current.toggle();
    result.current.toggle();
  });
  expect(result.current.isCollapsed).toBe(false);
});
it("keeps the mobile menu local and restores desktop preference on resize", () => {
  localStorage.setItem("sidebar-collapsed", "true");
  Object.defineProperty(window, "innerWidth", { value: 500, writable: true });
  const { result, unmount } = renderHook(() => useSidebar());
  const remove = jest.spyOn(window, "removeEventListener");
  expect(result.current).toMatchObject({ isMobile: true, isCollapsed: true });
  act(() => result.current.toggle());
  expect(result.current.isCollapsed).toBe(false);
  expect(localStorage.getItem("sidebar-collapsed")).toBe("true");
  act(() => {
    window.innerWidth = 1200;
    window.dispatchEvent(new Event("resize"));
  });
  expect(result.current).toMatchObject({ isMobile: false, isCollapsed: true });
  unmount();
  expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
});
it("continues navigation when browser storage is unavailable", () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const { result } = renderHook(() => useSidebar());
  expect(result.current.isCollapsed).toBe(false);
  act(() => result.current.toggle());
  expect(result.current.isCollapsed).toBe(true);
});
