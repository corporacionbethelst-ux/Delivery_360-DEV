import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  CanonicalProfileBalance,
  readStaffBalance,
} from "@/components/riders/CanonicalProfileBalance";
import { api } from "@/lib/api";
import { clearStoredTokens, storeTokens } from "@/lib/auth-session";
import fixture from "../../test-fixtures/rider-exact.json";

jest.mock("@/lib/api", () => ({ api: { get: jest.fn() } }));
const actorId = "11111111-1111-4111-8111-111111111111";
const riderId = fixture.balance.rider_id;
const sample = () => ({
  ...fixture.balance,
  scope: "staff_canonical_usd_balance",
  actor: { user_id: actorId, role: "GERENTE" },
});
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({ access_token: "a", refresh_token: "r" });
});
afterEach(() => clearStoredTokens());
it("checks the financial owner against the loaded profile when provided", () => {
  expect(() =>
    readStaffBalance(
      sample(),
      riderId,
      actorId,
      "GERENTE",
      "00000000-0000-4000-8000-000000000001",
    ),
  ).toThrow();
});
it("retires an old account continuation and its money after credentials change", async () => {
  let resolve!: (value: unknown) => void;
  const zero = {
    ...sample(),
    available: "0.00",
    ledger_balance: "0.00",
    reserved: "0.00",
    pending: "0.00",
    processed: "0.00",
    total_earned: "0.00",
    ledger_integrity: "no_evidence",
  };
  jest
    .mocked(api.get)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce(zero);
  render(
    <CanonicalProfileBalance
      riderId={riderId}
      actorId={actorId}
      role="GERENTE"
    />,
  );
  await act(async () => {
    storeTokens({ access_token: "b", refresh_token: "rb" });
  });
  await screen.findAllByText("USD 0,00");
  await act(async () => {
    resolve(sample());
  });
  expect(screen.queryByText("USD 15,20")).not.toBeInTheDocument();
  expect(screen.queryByText("USD 25,20")).not.toBeInTheDocument();
});
it.each(["OPERADOR", "AUDITOR", "CLIENTE", "REPARTIDOR"])(
  "does not request financial data for %s",
  (role) => {
    render(
      <CanonicalProfileBalance
        riderId={riderId}
        actorId={actorId}
        role={role}
      />,
    );
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.getByText(/requiere acceso de gerencia/)).toBeInTheDocument();
  },
);
it.each([
  { rider_id: "different" },
  { actor: { user_id: "different", role: "GERENTE" } },
  { scope: "own_canonical_usd_balance" },
  { available: 0 },
  { available: "999.99" },
])("rejects inconsistent identities and monetary evidence: %j", (change) => {
  expect(() =>
    readStaffBalance({ ...sample(), ...change }, riderId, actorId, "GERENTE"),
  ).toThrow();
});
it("a failed read is not a zero balance and retry repeats only a GET", async () => {
  jest
    .mocked(api.get)
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValueOnce(sample());
  render(
    <CanonicalProfileBalance
      riderId={riderId}
      actorId={actorId}
      role="GERENTE"
    />,
  );
  await screen.findByRole("alert");
  expect(screen.queryByText(/USD 0,00/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reintentar saldo" }));
  await screen.findByText("Saldo del libro USD");
  expect(api.get).toHaveBeenCalledTimes(2);
  expect(api.get).toHaveBeenLastCalledWith(
    `/payouts/riders/${riderId}/balance/exact`,
  );
});

it("withdraws the previously confirmed money after a forbidden refresh", async () => {
  jest
    .mocked(api.get)
    .mockResolvedValueOnce(sample())
    .mockRejectedValueOnce({ response: { status: 403 } });
  render(
    <CanonicalProfileBalance
      riderId={riderId}
      actorId={actorId}
      role="GERENTE"
    />,
  );
  await screen.findByText("USD 15,20");
  fireEvent.click(screen.getByRole("button", { name: "Actualizar saldo" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("USD 15,20")).not.toBeInTheDocument();
  expect(screen.queryByText("USD 25,20")).not.toBeInTheDocument();
});
