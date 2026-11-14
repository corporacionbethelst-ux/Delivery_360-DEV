import type { BcvRate, CurrencyContext, UsdVesQuote } from "@/lib/currency";
export const rateId = "11111111-1111-4111-8111-111111111111";
export const nextId = "22222222-2222-4222-8222-222222222222";
export const quoteId = "33333333-3333-4333-8333-333333333333";
export const actorId = "44444444-4444-4444-8444-444444444444";
export const rate: BcvRate = {
  id: rateId,
  previous_rate_id: null,
  valid_on: "2026-11-14",
  reference_date: "2026-11-14",
  revision: 1,
  ves_per_usd: "1.50000000",
  note: "Referencia sintética de pruebas",
  recorded_at: "2026-11-14T16:00:00Z",
  recorded_by: actorId,
  source: "MANUAL_BCV",
  source_url: "https://www.bcv.org.ve/",
  automatically_verified: false,
};
export const context: CurrencyContext = {
  scope: "quotation_only",
  country: "VE",
  base_currency: "USD",
  quote_currency: "VES",
  today: "2026-11-14",
  timezone: "America/Caracas",
  current_rate: rate,
  rates: [rate],
  automatic_bcv_available: false,
  historical_balances_relabelled: false,
};
export const quote: UsdVesQuote = {
  id: quoteId,
  amount_usd: "0.01",
  amount_ves: "0.02",
  reference: "Cotización de pruebas",
  created_at: "2026-11-14T16:00:00Z",
  created_by: actorId,
  rate,
  country: "VE",
  base_currency: "USD",
  quote_currency: "VES",
  quotation_only: true,
  payment_confirmed: false,
};
