import { api } from "@/lib/api";
import { currencyService } from "@/services/currency.service";
import {
  storeTokens,
  clearStoredTokens,
  SessionChangedError,
} from "@/lib/auth-session";
import { rate, quote, rateId, quoteId, nextId } from "../../test-utils/currency-fixtures";
jest.mock("@/lib/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const post = jest.mocked(api.post),
  get = jest.mocked(api.get);
beforeEach(() => {
  jest.resetAllMocks();
  storeTokens({ access_token: "first", refresh_token: "r-first" });
});
afterEach(() => clearStoredTokens());
it("sends exact strings and checks the reference returned by rate recording", async () => {
  const body = {
    request_key: nextId,
    previous_rate_id: null,
    valid_on: rate.valid_on,
    reference_date: rate.reference_date,
    ves_per_usd: "1.5",
    note: rate.note,
    confirmed_bcv: true as const,
  };
  post.mockResolvedValueOnce(rate);
  expect(await currencyService.saveRate(body)).toEqual(rate);
  expect(post).toHaveBeenCalledWith("/currency/rates", body);
  post.mockResolvedValueOnce({ ...rate, ves_per_usd: "2.50000000" });
  await expect(currencyService.saveRate(body)).rejects.toThrow("no coincide");
});
it("captures the quote request instead of reading later field changes", async () => {
  let finish!: (value: unknown) => void;
  post.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }) as never,
  );
  const body = {
    request_key: nextId,
    rate_id: rateId,
    amount_usd: "0.01",
    reference: quote.reference,
  };
  const task = currencyService.quote(body);
  body.amount_usd = "99";
  finish(quote);
  expect(await task).toEqual(quote);
  expect(post.mock.calls[0][1]).toMatchObject({ amount_usd: "0.01" });
});
it("discards a receipt arriving after another session starts", async () => {
  let finish!: (value: unknown) => void;
  get.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }) as never,
  );
  const task = currencyService.receipt(quoteId);
  storeTokens({ access_token: "second", refresh_token: "r-second" });
  finish(quote);
  await expect(task).rejects.toBeInstanceOf(SessionChangedError);
});
it("rejects another receipt identity and invalid URL identifiers", async () => {
  get.mockResolvedValueOnce({ ...quote, id: nextId });
  await expect(currencyService.receipt(quoteId)).rejects.toThrow(
    "otra referencia",
  );
  get.mockClear();
  await expect(
    currencyService.receipt("------------------------------------"),
  ).rejects.toThrow("inválido");
  expect(get).not.toHaveBeenCalled();
});
