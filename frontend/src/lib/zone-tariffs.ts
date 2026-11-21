import { canonicalDecimal } from "@/lib/currency";
export interface ZoneTariff {
  version: 1;
  scope: "zone_usd_tariff";
  zone_id: string;
  revision: number;
  currency: "USD" | null;
  base_usd: string | null;
  per_km_usd: string | null;
  updated_at: string | null;
  updated_by: string | null;
  application: "zone_configuration_only";
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function readZoneTariff(raw: unknown, zoneId: string): ZoneTariff {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("Tarifa de zona inválida.");
  const v = raw as Record<string, unknown>;
  if (
    v.version !== 1 ||
    v.scope !== "zone_usd_tariff" ||
    v.zone_id !== zoneId ||
    !uuid.test(zoneId) ||
    v.application !== "zone_configuration_only" ||
    !Number.isSafeInteger(v.revision) ||
    (v.revision as number) < 0 ||
    (v.revision as number) > 2147483647
  )
    throw new Error("La tarifa no corresponde a la zona o revisión.");
  if (v.revision === 0) {
    if (
      [v.currency, v.base_usd, v.per_km_usd, v.updated_at, v.updated_by].some(
        (x) => x !== null,
      )
    )
      throw new Error("Tarifa no configurada contradictoria.");
  } else if (
    v.currency !== "USD" ||
    ![v.base_usd, v.per_km_usd].every(
      (x) => typeof x === "string" && /^(?:0|[1-9]\d{0,7})\.\d{2}$/.test(x),
    ) ||
    typeof v.updated_at !== "string" ||
    !Number.isFinite(Date.parse(v.updated_at)) ||
    !/(Z|[+-]\d{2}:\d{2})$/.test(v.updated_at) ||
    typeof v.updated_by !== "string" ||
    !uuid.test(v.updated_by)
  )
    throw new Error(
      "Los importes o la procedencia de la tarifa requieren revisión.",
    );
  return v as unknown as ZoneTariff;
}
export function zoneMoneyInput(value: string): string {
  const normalized = canonicalDecimal(value, 2, 8);
  const [whole, fraction = ""] = normalized.split(".");
  return whole + "." + fraction.padEnd(2, "0");
}
