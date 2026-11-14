import { api } from "@/lib/api";
import {
  captureAuthSession,
  isCurrentAuthSession,
  SessionChangedError,
} from "@/lib/auth-session";
import {
  validateCurrency,
  validateQuote,
  validateRate,
  type BcvRateInput,
  type UsdVesQuoteInput,
} from "@/lib/currency";
async function inSession<T>(request: () => Promise<T>): Promise<T> {
  const session = captureAuthSession(),
    result = await request();
  if (!isCurrentAuthSession(session)) throw new SessionChangedError();
  return result;
}
export const currencyService = {
  context: async () =>
    validateCurrency(
      await inSession(() => api.get<unknown>("/currency/context")),
    ),
  saveRate: async (body: BcvRateInput) => {
    const input = { ...body },
      result = validateRate(
        await inSession(() => api.post<unknown>("/currency/rates", input)),
      );
    const [units, fraction = ""] = input.ves_per_usd.split(".");
    if (
      result.valid_on !== input.valid_on ||
      result.previous_rate_id !== input.previous_rate_id ||
      result.reference_date !== input.reference_date ||
      result.ves_per_usd !== units + "." + fraction.padEnd(8, "0") ||
      result.note !== input.note.trim()
    )
      throw new Error("La referencia confirmada no coincide con la enviada.");
    return result;
  },
  quote: async (body: UsdVesQuoteInput) => {
    const input = { ...body },
      result = validateQuote(
        await inSession(() => api.post<unknown>("/currency/quotes", input)),
      );
    const [units, cents = ""] = input.amount_usd.split(".");
    if (
      result.rate.id !== input.rate_id ||
      result.amount_usd !== units + "." + cents.padEnd(2, "0") ||
      result.reference !== input.reference
    )
      throw new Error("La cotización no corresponde a esta solicitud.");
    return result;
  },
  receipt: async (id: string) => {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      throw new Error("Identificador de cotización inválido.");
    const result = validateQuote(
      await inSession(() =>
        api.get<unknown>("/currency/quotes/" + encodeURIComponent(id)),
      ),
    );
    if (result.id !== id)
      throw new Error("La cotización recibida pertenece a otra referencia.");
    return result;
  },
};
