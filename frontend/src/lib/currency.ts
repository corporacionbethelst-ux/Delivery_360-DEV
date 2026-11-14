export interface BcvRate {
  id: string;
  previous_rate_id: string | null;
  valid_on: string;
  reference_date: string;
  revision: number;
  ves_per_usd: string;
  note: string;
  recorded_at: string;
  recorded_by: string;
  source: "MANUAL_BCV";
  source_url: "https://www.bcv.org.ve/";
  automatically_verified: false;
}
export interface CurrencyContext {
  scope: "quotation_only";
  country: "VE";
  base_currency: "USD";
  quote_currency: "VES";
  today: string;
  timezone: "America/Caracas";
  current_rate: BcvRate | null;
  rates: BcvRate[];
  automatic_bcv_available: false;
  historical_balances_relabelled: false;
}
export interface UsdVesQuote {
  id: string;
  amount_usd: string;
  amount_ves: string;
  reference: string;
  created_at: string;
  created_by: string;
  rate: BcvRate;
  country: "VE";
  base_currency: "USD";
  quote_currency: "VES";
  quotation_only: true;
  payment_confirmed: false;
}
export interface BcvRateInput {
  request_key: string;
  previous_rate_id: string | null;
  valid_on: string;
  reference_date: string;
  ves_per_usd: string;
  note: string;
  confirmed_bcv: true;
}
export interface UsdVesQuoteInput {
  request_key: string;
  rate_id: string;
  amount_usd: string;
  reference: string;
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const money = /^(?:0|[1-9]\d{0,21})\.\d{2}$/;
const rateNumber = /^(?:0|[1-9]\d{0,8})\.\d{8}$/;
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Respuesta de moneda inválida.");
  return value as Record<string, unknown>;
}
function date(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  );
}
function identity(value: unknown): value is string {
  return typeof value === "string" && uuid.test(value);
}
function time(value: unknown): boolean {
  return (
    typeof value === "string" &&
    value.endsWith("Z") &&
    !Number.isNaN(Date.parse(value))
  );
}
export function canonicalDecimal(
  value: string,
  places: number,
  digits: number,
): string {
  const normalized = value.trim().replace(",", ".");
  if (
    !new RegExp(
      `^(?:0|[1-9]\\d{0,${digits - 1}})(?:\\.\\d{1,${places}})?$`,
    ).test(normalized)
  )
    throw new Error(
      `Usa cifras con hasta ${places} decimales y sin separadores de miles.`,
    );
  return normalized;
}
export function exactVes(usd: string, rate: string): string {
  if (!/^(?:0|[1-9]\d{0,11})\.\d{2}$/.test(usd) || !rateNumber.test(rate))
    throw new Error("Importe o tasa inválidos.");
  const cents =
    (BigInt(usd.replace(".", "")) * BigInt(rate.replace(".", "")) +
      BigInt(50000000)) /
    BigInt(100000000);
  return (
    (cents / BigInt(100)).toString() +
    "." +
    (cents % BigInt(100)).toString().padStart(2, "0")
  );
}
export function moneyText(value: string, currency: "USD" | "VES"): string {
  if (!money.test(value)) throw new Error("Importe no confirmado.");
  const [units, cents] = value.split(".");
  return (
    (currency === "USD" ? "USD " : "Bs. ") +
    units.replace(/\B(?=(\d{3})+(?!\d))/g, ".") +
    "," +
    cents
  );
}
export function validateRate(value: unknown): BcvRate {
  const r = record(value);
  if (
    !identity(r.id) ||
    !identity(r.recorded_by) ||
    !date(r.valid_on) ||
    !date(r.reference_date) ||
    r.reference_date > r.valid_on ||
    !Number.isSafeInteger(r.revision) ||
    Number(r.revision) < 1 ||
    (r.revision === 1
      ? r.previous_rate_id !== null
      : !identity(r.previous_rate_id) || r.previous_rate_id === r.id) ||
    typeof r.ves_per_usd !== "string" ||
    !rateNumber.test(r.ves_per_usd) ||
    BigInt(r.ves_per_usd.replace(".", "")) <= BigInt(0) ||
    typeof r.note !== "string" ||
    !r.note.trim() ||
    r.note.length > 500 ||
    !time(r.recorded_at) ||
    r.source !== "MANUAL_BCV" ||
    r.source_url !== "https://www.bcv.org.ve/" ||
    r.automatically_verified !== false
  )
    throw new Error("La referencia BCV recibida no es verificable.");
  return r as unknown as BcvRate;
}
export function validateCurrency(value: unknown): CurrencyContext {
  const r = record(value);
  if (
    r.country !== "VE" ||
    r.scope !== "quotation_only" ||
    r.base_currency !== "USD" ||
    r.quote_currency !== "VES" ||
    r.timezone !== "America/Caracas" ||
    !date(r.today) ||
    !Array.isArray(r.rates) ||
    r.rates.length > 20 ||
    r.automatic_bcv_available !== false ||
    r.historical_balances_relabelled !== false
  )
    throw new Error("No se pudo confirmar el contexto USD/VES.");
  const rates = r.rates.map(validateRate),
    current = r.current_rate === null ? null : validateRate(r.current_rate);
  if (
    rates.some((rate) => rate.valid_on > String(r.today)) ||
    (current &&
      (current.valid_on !== r.today ||
        !rates.some((rate) => rate.id === current.id)))
  )
    throw new Error("La referencia no corresponde al día consultado.");
  return { ...r, rates, current_rate: current } as unknown as CurrencyContext;
}
export function validateQuote(value: unknown): UsdVesQuote {
  const r = record(value),
    rate = validateRate(r.rate);
  if (
    !identity(r.id) ||
    !identity(r.created_by) ||
    !time(r.created_at) ||
    r.country !== "VE" ||
    r.base_currency !== "USD" ||
    r.quote_currency !== "VES" ||
    r.quotation_only !== true ||
    r.payment_confirmed !== false ||
    typeof r.reference !== "string" ||
    !r.reference.trim() ||
    r.reference.length > 120 ||
    typeof r.amount_usd !== "string" ||
    typeof r.amount_ves !== "string" ||
    !money.test(r.amount_ves) ||
    exactVes(r.amount_usd, rate.ves_per_usd) !== r.amount_ves
  )
    throw new Error(
      "La cotización recibida no conserva importes y tasa coherentes.",
    );
  return { ...r, rate } as unknown as UsdVesQuote;
}
