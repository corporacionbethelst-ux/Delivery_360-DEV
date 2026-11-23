import "@testing-library/jest-dom";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { FeedbackHost } from "@/components/layout/FeedbackHost";
import { clearFeedback, confirmAction, showAlert, toast } from "@/lib/feedback";
import { storeTokens, clearStoredTokens } from "@/lib/auth-session";
import { toast as notifications } from "sonner";
let mockPathname = "/orders";
jest.mock("next/navigation", () => ({ usePathname: () => mockPathname }));

jest.mock("sonner", () => ({
  Toaster: (props: { position: string }) => <div data-testid="toaster" data-position={props.position} />,
  toast: { success: jest.fn(), info: jest.fn(), dismiss: jest.fn() },
}));
beforeEach(() => { clearFeedback(); clearStoredTokens(); jest.clearAllMocks(); mockPathname = "/orders"; history.replaceState({}, "", "/orders"); });

it("shows errors in an accessible modal and information at bottom right", () => {
  render(<FeedbackHost />);
  act(() => { showAlert("Código OTP requerido o incorrecto"); });
  expect(screen.getByRole("alertdialog")).toHaveTextContent("Código OTP requerido o incorrecto");
  expect(screen.getByTestId("toaster")).toHaveAttribute("data-position", "bottom-right");
  fireEvent.click(screen.getByRole("button", { name: "Entendido" }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  toast.info("Lectura actualizada");
  toast.success("Orden actualizada");
  expect(notifications.info).toHaveBeenCalledWith("Lectura actualizada");
  expect(notifications.success).toHaveBeenCalledWith("Orden actualizada");
});

it("does not confirm before an explicit choice and preserves queued alerts", async () => {
  render(<FeedbackHost />);
  let confirmation!: Promise<boolean>;
  act(() => { confirmation = confirmAction("¿Cambiar esta orden?"); showAlert("Aviso siguiente"); });
  const completed = jest.fn(); confirmation.then(completed);
  expect(completed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
  await expect(confirmation).resolves.toBe(false);
  expect(screen.getByRole("alertdialog")).toHaveTextContent("Aviso siguiente");
  fireEvent.click(screen.getByRole("button", { name: "Entendido" }));
  act(() => { confirmation = confirmAction("¿Confirmar?"); });
  fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
  await expect(confirmation).resolves.toBe(true);
});

it("cancels pending actions and private messages on credential changes", async () => {
  render(<FeedbackHost />);
  let confirmation!: Promise<boolean>;
  act(() => { confirmation = confirmAction("Acción de la sesión anterior"); });
  act(() => { storeTokens({ access_token: "another-session", refresh_token: "another-refresh" }); });
  await expect(confirmation).resolves.toBe(false);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(notifications.dismiss).toHaveBeenCalled();
});

it("fails closed if its host is unmounted", async () => {
  const view = render(<FeedbackHost />);
  let confirmation!: Promise<boolean>;
  act(() => { confirmation = confirmAction("¿Eliminar?"); });
  view.unmount();
  await expect(confirmation).resolves.toBe(false);
});

it.each([false, true])("cancels confirmation when navigating away (render updated: %s)", async (rerender) => {
  const view = render(<FeedbackHost />);
  let confirmation!: Promise<boolean>;
  act(() => { confirmation = confirmAction("Acción de la página anterior"); });
  act(() => { history.pushState({}, "", "/another-page"); });
  if (rerender) {
    mockPathname = "/another-page";
    view.rerender(<FeedbackHost />);
  } else {
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
  }
  await expect(confirmation).resolves.toBe(false);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(notifications.dismiss).not.toHaveBeenCalled();
});
