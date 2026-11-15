import "@testing-library/jest-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import Page from "@/app/(dashboard)/rider/earnings/withdraw/page";
import { createPayoutIdempotencyKey } from "@/services/payout.service";
import { riderExactService } from "@/services/rider-earnings-exact.service";
import { withdrawalExactService } from "@/services/withdrawal-exact.service";
import fixture from "../../test-fixtures/rider-exact.json";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import {
  loadWithdrawalIntent,
  saveWithdrawalIntent,
} from "@/lib/withdrawal-intent";

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockUser = { id: "a", role: "REPARTIDOR" };
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
const intent = {
  version: 1 as const,
  userId: "a",
  key: "safe-key",
  amountCents: 6000,
  bankLast4: "1234",
};
const reply = {
  currency: "USD",
  id: "p",
  rider_id: "r",
  amount: 60,
  total_amount: 60,
  method: "TRANSFERENCIA" as const,
  status: "PENDIENTE" as const,
  requested_at: null,
  created_at: null,
  updated_at: null,
  idempotency_key: "safe-key",
  requested_by_user_id: "a",
  bank_account_last4: "1234",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
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
    rider_id: "r",
    available,
    pending,
  }) as import("@/lib/rider-earnings-exact").RiderExactBalance;
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  sessionStorage.clear();
  mockUser = { id: "a", role: "REPARTIDOR" };
  storeTokens({ access_token: "token-a", refresh_token: "ra" });
  jest.mocked(riderExactService.balance).mockResolvedValue(exactBalance());
  jest.mocked(withdrawalExactService.find).mockResolvedValue(null);
  jest.mocked(withdrawalExactService.request).mockResolvedValue(reply);
  jest.mocked(createPayoutIdempotencyKey).mockReturnValue("safe-key");
});
afterEach(() => clearStoredTokens());
const submit = () =>
  fireEvent.submit(screen.getByLabelText("Monto a Retirar").closest("form")!);
async function fill() {
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "60" },
  });
  fireEvent.change(screen.getByLabelText("Últimos 4 dígitos (Opcional)"), {
    target: { value: "1234" },
  });
}

it.each([
  { idempotency_key: "other" },
  { requested_by_user_id: "b" },
  { amount: 61, total_amount: 61 },
  { method: "EFECTIVO" },
  { bank_account_last4: "9999" },
])(
  "retains the original key and shows no success on an inconsistent POST confirmation (%j)",
  async (invalid) => {
    jest
      .mocked(withdrawalExactService.request)
      .mockResolvedValue({ ...reply, ...invalid } as never);
    render(<Page />);
    await fill();
    submit();
    await screen.findByText("Error al procesar. Intenta más tarde.");
    expect(screen.queryByText("¡Solicitud Enviada!")).not.toBeInTheDocument();
    expect(loadWithdrawalIntent("a")).toEqual(intent);
    expect(
      screen.getByRole("button", { name: "Reintentar misma solicitud" }),
    ).toBeEnabled();
  },
);
it.each([
  { idempotency_key: "other" },
  { requested_by_user_id: "b" },
  { amount: 61, total_amount: 61 },
  { bank_account_last4: "9999" },
])(
  "does not clear recovery metadata on a mismatched lookup (%j)",
  async (invalid) => {
    saveWithdrawalIntent(intent);
    jest
      .mocked(withdrawalExactService.find)
      .mockResolvedValue({ ...reply, ...invalid } as never);
    render(<Page />);
    await screen.findByText(
      "No se pudo confirmar la solicitud. Conservamos sus datos para reintentar sin crear otra.",
    );
    expect(screen.queryByText("Solicitud encontrada")).not.toBeInTheDocument();
    expect(loadWithdrawalIntent("a")).toEqual(intent);
    expect(withdrawalExactService.request).not.toHaveBeenCalled();
  },
);
it("does not publish or clear another account request after switching during POST", async () => {
  const old = deferred<typeof reply>();
  jest.mocked(withdrawalExactService.request).mockReturnValue(old.promise);
  render(<Page />);
  await fill();
  submit();
  act(() => {
    mockUser = { id: "b", role: "REPARTIDOR" };
    storeTokens({ access_token: "token-b", refresh_token: "rb" });
  });
  await screen.findByLabelText("Monto a Retirar");
  await act(async () => {
    old.resolve(reply);
  });
  expect(screen.queryByText("¡Solicitud Enviada!")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Monto a Retirar")).toHaveValue("");
  expect(loadWithdrawalIntent("a")).toEqual(intent);
  expect(loadWithdrawalIntent("b")).toBeNull();
});
it("checks the continuation gap even when the mocked service changes accounts immediately before returning", async () => {
  jest.mocked(withdrawalExactService.request).mockImplementation(async () => {
    mockUser = { id: "b", role: "REPARTIDOR" };
    storeTokens({ access_token: "token-b", refresh_token: "rb" });
    return reply;
  });
  render(<Page />);
  await fill();
  await act(async () => {
    submit();
  });
  expect(screen.queryByText("¡Solicitud Enviada!")).not.toBeInTheDocument();
  expect(loadWithdrawalIntent("a")).toEqual(intent);
});
it("does not clear the old account intent after a late lookup", async () => {
  saveWithdrawalIntent(intent);
  const old = deferred<typeof reply>();
  jest.mocked(withdrawalExactService.find).mockReturnValue(old.promise);
  render(<Page />);
  await waitFor(() => expect(withdrawalExactService.find).toHaveBeenCalled());
  act(() => {
    mockUser = { id: "b", role: "REPARTIDOR" };
    storeTokens({ access_token: "token-b", refresh_token: "rb" });
  });
  await act(async () => {
    old.resolve(reply);
  });
  expect(screen.queryByText("Solicitud encontrada")).not.toBeInTheDocument();
  expect(loadWithdrawalIntent("a")).toEqual(intent);
});
it("does not let a late balance from another account enable a withdrawal", async () => {
  const old = deferred<ReturnType<typeof exactBalance>>();
  jest
    .mocked(riderExactService.balance)
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce(exactBalance("0.00"));
  render(<Page />);
  act(() => {
    mockUser = { id: "b", role: "REPARTIDOR" };
    storeTokens({ access_token: "token-b", refresh_token: "rb" });
  });
  await screen.findByLabelText("Monto a Retirar");
  await act(async () => {
    old.resolve(exactBalance("999.00"));
  });
  expect(
    screen.getByRole("button", { name: "Enviar solicitud de retiro" }),
  ).toBeDisabled();
  expect(screen.queryByText(/999/)).not.toBeInTheDocument();
});
it("retains recovery metadata when unmounted while awaiting POST", async () => {
  const old = deferred<typeof reply>();
  jest.mocked(withdrawalExactService.request).mockReturnValue(old.promise);
  const page = render(<Page />);
  await fill();
  submit();
  page.unmount();
  await act(async () => {
    old.resolve(reply);
  });
  expect(loadWithdrawalIntent("a")).toEqual(intent);
});
it("blocks two submit events in the same render with a synchronous lock", async () => {
  const old = deferred<typeof reply>();
  jest.mocked(withdrawalExactService.request).mockReturnValue(old.promise);
  render(<Page />);
  await fill();
  act(() => {
    submit();
    submit();
  });
  expect(withdrawalExactService.request).toHaveBeenCalledTimes(1);
  expect(createPayoutIdempotencyKey).toHaveBeenCalledTimes(1);
  await act(async () => {
    old.resolve(reply);
  });
  await screen.findByText("¡Solicitud Enviada!");
});
it("keeps a failed balance unknown and offers a read-only retry", async () => {
  jest
    .mocked(riderExactService.balance)
    .mockRejectedValueOnce(new Error("degraded"));
  render(<Page />);
  await screen.findByText(
    "No se pudo cargar tu saldo disponible. Puedes volver a consultarlo.",
  );
  expect(screen.getAllByText("No disponible").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("button", { name: "Enviar solicitud de retiro" }),
  ).toBeDisabled();
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Volver a consultar saldo" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Enviar solicitud de retiro" }),
    ).toBeEnabled(),
  );
});
it("can recover an authoritative existing request even when the balance service is unavailable", async () => {
  saveWithdrawalIntent(intent);
  jest
    .mocked(riderExactService.balance)
    .mockRejectedValue(new Error("degraded"));
  jest.mocked(withdrawalExactService.find).mockResolvedValue(reply);
  render(<Page />);
  await screen.findByText("Solicitud encontrada");
  expect(loadWithdrawalIntent("a")).toBeNull();
  expect(screen.getByText("USD 60,00")).toBeInTheDocument();
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
});
it("retains an uncertain key and permits the same retry even when no balance is available", async () => {
  saveWithdrawalIntent(intent);
  jest
    .mocked(riderExactService.balance)
    .mockRejectedValue(new Error("degraded"));
  render(<Page />);
  await screen.findByText(
    "La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.",
  );
  expect(
    screen.getByRole("button", { name: "Reintentar misma solicitud" }),
  ).toBeEnabled();
  submit();
  await screen.findByText("Solicitud encontrada");
  expect(withdrawalExactService.request).toHaveBeenCalledWith(
    expect.objectContaining({ amountCents: 6000, key: "safe-key" }),
    undefined,
  );
});
it("waits for recovery initialization before exposing a new request form", async () => {
  saveWithdrawalIntent(intent);
  const balance = deferred<ReturnType<typeof exactBalance>>();
  jest.mocked(riderExactService.balance).mockReturnValue(balance.promise);
  render(<Page />);
  expect(screen.queryByLabelText("Monto a Retirar")).not.toBeInTheDocument();
  await act(async () => {
    balance.resolve(exactBalance());
  });
  await screen.findByText(
    "La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.",
  );
  expect(screen.getByLabelText("Monto a Retirar")).toBeDisabled();
  expect(createPayoutIdempotencyKey).not.toHaveBeenCalled();
});
it.each(["10.001", "100000000.00", "1e2", "-10"])(
  "rejects %s without creating or saving a request",
  async (value) => {
    render(<Page />);
    fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
      target: { value },
    });
    submit();
    await screen.findByText(/Usa un monto con hasta dos decimales/);
    expect(withdrawalExactService.request).not.toHaveBeenCalled();
    expect(loadWithdrawalIntent("a")).toBeNull();
  },
);
it("compares the last cent with the exact available balance", async () => {
  jest
    .mocked(riderExactService.balance)
    .mockResolvedValue(exactBalance("10.00"));
  render(<Page />);
  fireEvent.change(await screen.findByLabelText("Monto a Retirar"), {
    target: { value: "10.01" },
  });
  submit();
  await screen.findByText("Monto superior al disponible.");
  expect(withdrawalExactService.request).not.toHaveBeenCalled();
});
it("accepts a decimal comma and persists bounded integer cents", async () => {
  jest
    .mocked(withdrawalExactService.request)
    .mockResolvedValue({ ...reply, amount: 10.01, total_amount: 10.01 });
  render(<Page />);
  await fill();
  fireEvent.change(screen.getByLabelText("Monto a Retirar"), {
    target: { value: "10,01" },
  });
  submit();
  await screen.findByText("¡Solicitud Enviada!");
  expect(screen.getByText("USD 10,01")).toBeInTheDocument();
  expect(withdrawalExactService.request).toHaveBeenCalledWith(
    expect.objectContaining({ amountCents: 1001 }),
    "r",
  );
});
it("retires a pending POST when role changes even with unchanged credentials", async () => {
  const old = deferred<typeof reply>();
  jest.mocked(withdrawalExactService.request).mockReturnValue(old.promise);
  const view = render(<Page />);
  await fill();
  submit();
  mockUser = { id: "a", role: "GERENTE" };
  view.rerender(<Page />);
  await act(async () => old.resolve(reply));
  expect(screen.queryByText("¡Solicitud Enviada!")).not.toBeInTheDocument();
  expect(loadWithdrawalIntent("a")).toEqual(intent);
  expect(mockRouter.push).toHaveBeenCalledWith("/rider");
});
