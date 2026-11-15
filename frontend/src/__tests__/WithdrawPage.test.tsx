import { storeTokens, clearStoredTokens } from "@/lib/auth-session";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import WithdrawPage from "@/app/(dashboard)/rider/earnings/withdraw/page";
import { createPayoutIdempotencyKey } from "@/services/payout.service";
import { riderExactService } from "@/services/rider-earnings-exact.service";
import { withdrawalExactService } from "@/services/withdrawal-exact.service";
import fixture from "../../test-fixtures/rider-exact.json";
const mockRouter = { push: jest.fn(), back: jest.fn() };
const mockUser = { id: "rider-user", role: "REPARTIDOR" };
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: mockUser, isAuthenticated: true }),
}));
jest.mock("@/services/payout.service", () => ({
  payoutService: {
    getAvailableBalance: jest.fn(),
    requestPayout: jest.fn(),
    findRequestByKey: jest.fn(),
  },
  createPayoutIdempotencyKey: jest.fn(),
  payoutHttpStatus: jest.requireActual("@/services/payout.service")
    .payoutHttpStatus,
}));
jest.mock("@/services/rider-earnings-exact.service", () => ({
  riderExactService: { balance: jest.fn() },
}));
jest.mock("@/services/withdrawal-exact.service", () => ({
  withdrawalExactService: { request: jest.fn(), find: jest.fn() },
}));
const exactBalance = (available = "100.00", pending = "0.00") =>
  ({
    ...fixture.balance,
    user_id: mockUser.id,
    rider_id: "rider-1",
    available,
    pending,
  }) as import("@/lib/rider-earnings-exact").RiderExactBalance;
beforeEach(() => {
  clearStoredTokens();
  storeTokens({ access_token: "withdraw-a", refresh_token: "refresh-a" });
  jest.resetAllMocks();
  sessionStorage.clear();
  jest.mocked(withdrawalExactService.find).mockResolvedValue(null);
  jest.mocked(riderExactService.balance).mockResolvedValue(exactBalance());
  jest
    .mocked(withdrawalExactService.request)
    .mockRejectedValue(new Error("Network unavailable"));
  jest
    .mocked(createPayoutIdempotencyKey)
    .mockReturnValueOnce("intent-1")
    .mockReturnValueOnce("intent-2");
});
const submit = () =>
  fireEvent.submit(screen.getByLabelText("Monto a Retirar").closest("form")!);
it("reuses the same key after an uncertain response instead of starting another withdrawal", async () => {
  render(<WithdrawPage />);
  const amount = await screen.findByLabelText("Monto a Retirar");
  fireEvent.change(amount, { target: { value: "60" } });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  submit();
  await waitFor(() =>
    expect(withdrawalExactService.request).toHaveBeenCalledTimes(2),
  );
  expect(
    jest
      .mocked(withdrawalExactService.request)
      .mock.calls.map(([data]) => data.key),
  ).toEqual(["intent-1", "intent-1"]);
  expect(createPayoutIdempotencyKey).toHaveBeenCalledTimes(1);
});
it("creates a new intent after a definite rejection when the amount changes", async () => {
  jest
    .mocked(withdrawalExactService.request)
    .mockRejectedValueOnce({ response: { status: 400 } });
  render(<WithdrawPage />);
  const amount = await screen.findByLabelText("Monto a Retirar");
  fireEvent.change(amount, { target: { value: "60" } });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  fireEvent.change(amount, { target: { value: "50" } });
  submit();
  await waitFor(() =>
    expect(withdrawalExactService.request).toHaveBeenCalledTimes(2),
  );
  expect(
    jest
      .mocked(withdrawalExactService.request)
      .mock.calls.map(([data]) => data.key),
  ).toEqual(["intent-1", "intent-2"]);
});
it("does not submit an incomplete bank suffix", async () => {
  render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  fireEvent.change(screen.getByLabelText("Últimos 4 dígitos (Opcional)"), {
    target: { value: "12" },
  });
  submit();
  expect(
    await screen.findByText(
      "Ingresa los cuatro dígitos completos de la cuenta.",
    ),
  ).toBeInTheDocument();
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
});
it("restores an uncertain request after remount and retries the original key even with a lower balance", async () => {
  const page = render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  page.unmount();
  jest
    .mocked(riderExactService.balance)
    .mockResolvedValue(exactBalance("40.00", "60.00"));
  render(<WithdrawPage />);
  await screen.findByText(
    "La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.",
  );
  expect(screen.getByLabelText("Monto a Retirar")).toHaveValue("60.00");
  expect(screen.getByLabelText("Monto a Retirar")).toBeDisabled();
  submit();
  await waitFor(() =>
    expect(withdrawalExactService.request).toHaveBeenCalledTimes(2),
  );
  expect(
    jest
      .mocked(withdrawalExactService.request)
      .mock.calls.map(([data]) => data.key),
  ).toEqual(["intent-1", "intent-1"]);
  expect(createPayoutIdempotencyKey).toHaveBeenCalledTimes(1);
});
it("recovers the authoritative request after remount without submitting again", async () => {
  const page = render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  page.unmount();
  jest.mocked(withdrawalExactService.find).mockResolvedValue({
    currency: "USD",
    id: "registered",
    rider_id: "rider-1",
    amount: 60,
    total_amount: 60,
    status: "RECHAZADO",
    method: "TRANSFERENCIA",
    requested_at: "2026-10-24",
    created_at: "2026-10-24",
    updated_at: "2026-10-24",
    idempotency_key: "intent-1",
    requested_by_user_id: "rider-user",
  });
  render(<WithdrawPage />);
  expect(await screen.findByText("Solicitud encontrada")).toBeInTheDocument();
  expect(screen.getByText("Estado actual: RECHAZADO")).toBeInTheDocument();
  expect(withdrawalExactService.request).toHaveBeenCalledTimes(1);
  expect(
    sessionStorage.getItem("delivery360-withdrawal-v1:rider-user"),
  ).toBeNull();
});
it("does not send a request if its recovery metadata cannot be saved", async () => {
  render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  const storage = jest
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("Unavailable");
    });
  submit();
  expect(
    await screen.findByText(
      "El navegador no pudo conservar la solicitud. Revisa tu historial y la configuración del navegador antes de continuar.",
    ),
  ).toBeInTheDocument();
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
  storage.mockRestore();
});
it("keeps the original key when a retry is rejected after an earlier uncertain response", async () => {
  render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  jest
    .mocked(withdrawalExactService.request)
    .mockRejectedValueOnce({ response: { status: 400 } });
  submit();
  await waitFor(() =>
    expect(withdrawalExactService.request).toHaveBeenCalledTimes(2),
  );
  await screen.findByRole("button", { name: "Reintentar misma solicitud" });
  expect(screen.getByLabelText("Monto a Retirar")).toBeDisabled();
  expect(
    JSON.parse(
      sessionStorage.getItem("delivery360-withdrawal-v1:rider-user") || "{}",
    ).key,
  ).toBe("intent-1");
});
it("shows the final server status when retrying an uncertain request", async () => {
  render(<WithdrawPage />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  submit();
  await screen.findByText("Error al procesar. Intenta más tarde.");
  jest.mocked(withdrawalExactService.request).mockResolvedValueOnce({
    currency: "USD",
    id: "registered",
    rider_id: "rider-1",
    amount: 60,
    total_amount: 60,
    status: "RECHAZADO",
    method: "TRANSFERENCIA",
    requested_at: "2026-10-24",
    created_at: "2026-10-24",
    updated_at: "2026-10-24",
    idempotency_key: "intent-1",
    requested_by_user_id: "rider-user",
  });
  submit();
  expect(await screen.findByText("Solicitud encontrada")).toBeInTheDocument();
  expect(screen.getByText("Estado actual: RECHAZADO")).toBeInTheDocument();
  expect(
    sessionStorage.getItem("delivery360-withdrawal-v1:rider-user"),
  ).toBeNull();
});
it("retains recovery metadata when the status service is unavailable", async () => {
  sessionStorage.setItem(
    "delivery360-withdrawal-v1:rider-user",
    JSON.stringify({
      version: 1,
      userId: "rider-user",
      key: "original-key",
      amountCents: 6000,
      bankLast4: "",
    }),
  );
  jest
    .mocked(withdrawalExactService.find)
    .mockRejectedValueOnce(new Error("Unavailable"));
  render(<WithdrawPage />);
  await screen.findByText(
    "No se pudo confirmar la solicitud. Conservamos sus datos para reintentar sin crear otra.",
  );
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
  submit();
  await waitFor(() =>
    expect(withdrawalExactService.request).toHaveBeenCalledTimes(1),
  );
  expect(withdrawalExactService.request).toHaveBeenCalledWith(
    expect.objectContaining({ key: "original-key" }),
    "rider-1",
  );
  expect(createPayoutIdempotencyKey).not.toHaveBeenCalled();
});

afterEach(() => clearStoredTokens());
