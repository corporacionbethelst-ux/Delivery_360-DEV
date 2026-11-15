import {
  withdrawalAmount,
  intentAmount,
  confirmExactWithdrawal,
} from "@/lib/withdrawal-exact";
import { withdrawalExactService } from "@/services/withdrawal-exact.service";
import { api } from "@/lib/api";
import {
  storeTokens,
  clearStoredTokens,
  SessionChangedError,
} from "@/lib/auth-session";
import fixture from "../../test-fixtures/rider-exact.json";
import type { WithdrawalIntent } from "@/lib/withdrawal-intent";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const userId = fixture.report.user_id,
  riderId = fixture.report.rider_id;
const intent: WithdrawalIntent = {
  version: 1,
  userId,
  key: "request/key",
  amountCents: 1001,
  bankLast4: "1234",
};
const reply = {
  id: fixture.report.rows[0].id,
  rider_id: riderId,
  requested_by_user_id: userId,
  idempotency_key: intent.key,
  currency: "USD",
  amount: "10.01",
  method: "TRANSFERENCIA",
  status: "PENDIENTE",
  bank_account_last4: "1234",
};
beforeEach(() => {
  jest.resetAllMocks();
  clearStoredTokens();
  storeTokens({
    access_token: "exact-withdrawal",
    refresh_token: "exact-refresh",
  });
});
afterEach(clearStoredTokens);
it.each([
  ["0", "0.00"],
  ["10", "10.00"],
  ["10.1", "10.10"],
  ["10.01", "10.01"],
  ["10,01", "10.01"],
  ["00010.01", "10.01"],
  [" 10.01 ", "10.01"],
  ["99999999.99", "99999999.99"],
])("parses %s as exact text %s", (input, output) =>
  expect(withdrawalAmount(input)).toBe(output),
);
it.each([
  "",
  " ",
  "-10",
  "+10",
  "1e2",
  "0x10",
  "10.001",
  "100000000",
  "1.000,00",
  "NaN",
  "Infinity",
  ".01",
  "10.",
])("rejects ambiguous or out-of-range input %s", (value) =>
  expect(() => withdrawalAmount(value)).toThrow(),
);
it.each([999, 1000.1, 10000000000, Number.MAX_SAFE_INTEGER, NaN])(
  "rejects invalid stored integer cents %s",
  (amountCents) =>
    expect(() => intentAmount({ ...intent, amountCents })).toThrow(),
);
it("restores maximum legacy v1 intent without multiplication or rounding", () =>
  expect(intentAmount({ ...intent, amountCents: 9999999999 })).toBe(
    "99999999.99",
  ));
it.each([
  { currency: "VES" },
  { requested_by_user_id: riderId },
  { rider_id: userId },
  { idempotency_key: "other" },
  { amount: "10.02" },
  { method: "EFECTIVO" },
  { bank_account_last4: "9999" },
])("rejects a mismatched confirmation %j", (changed) =>
  expect(() =>
    confirmExactWithdrawal({ ...reply, ...changed }, intent, riderId),
  ).toThrow(),
);
it("sends canonical decimal text and the original v1 key to the unchanged server contract", async () => {
  jest.mocked(api.post).mockResolvedValue(reply);
  const result = await withdrawalExactService.request(intent, riderId);
  expect(api.post).toHaveBeenCalledWith("/payouts/request", {
    currency: "USD",
    amount: "10.01",
    method: "TRANSFERENCIA",
    bank_account_last4: "1234",
    idempotency_key: "request/key",
  });
  expect(result.requested_by_user_id).toBe(userId);
});
it("accepts the existing bounded numeric response without inferring a new currency", () =>
  expect(
    confirmExactWithdrawal({ ...reply, amount: 10.01 }, intent).amount,
  ).toBe(10.01));
it("looks up only the encoded original key and binds confirmation to the owner", async () => {
  jest.mocked(api.get).mockResolvedValue(reply);
  await withdrawalExactService.find(intent);
  expect(api.get).toHaveBeenCalledWith(
    "/payouts/request-status?idempotency_key=request%2Fkey",
  );
  expect(api.post).not.toHaveBeenCalled();
});
it("returns point-in-time absence on 404 without deleting retry metadata", async () => {
  jest.mocked(api.get).mockRejectedValue({ response: { status: 404 } });
  await expect(withdrawalExactService.find(intent)).resolves.toBeNull();
});
it.each(["request", "find"] as const)(
  "retires a late %s confirmation after credential replacement",
  async (operation) => {
    let resolve!: (v: unknown) => void;
    const pending = new Promise((done) => {
      resolve = done;
    });
    jest
      .mocked(operation === "request" ? api.post : api.get)
      .mockReturnValue(pending);
    const promise = withdrawalExactService[operation](intent);
    storeTokens({
      access_token: "other-owner",
      refresh_token: "other-refresh",
    });
    resolve(reply);
    await expect(promise).rejects.toBeInstanceOf(SessionChangedError);
  },
);
it("captures the intent before awaiting so caller mutation cannot change confirmation", async () => {
  let resolve!: (v: unknown) => void;
  jest.mocked(api.post).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const mutable = { ...intent },
    promise = withdrawalExactService.request(mutable);
  mutable.key = "changed";
  mutable.amountCents = 2000;
  resolve(reply);
  await expect(promise).resolves.toMatchObject({ idempotency_key: intent.key });
});
it.each([
  { amountCents: 10000000000 },
  { userId: "invalid" },
  { bankLast4: "12" },
  { key: "" },
  { version: 2 },
])("blocks malformed intents before HTTP %j", async (changed) => {
  await expect(
    withdrawalExactService.request({
      ...intent,
      ...changed,
    } as WithdrawalIntent),
  ).rejects.toThrow();
  expect(api.post).not.toHaveBeenCalled();
});
