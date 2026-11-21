import { canonicalDecimal } from "@/lib/currency";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function recordedFactor(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^(?:0|[1-9]\d{0,7})(?:\.\d{1,324})?$/.test(value)
  )
    throw new Error("Factor conservado inválido.");
  const [whole, part = ""] = value.split(".");
  const scale = BigInt(10) ** BigInt(Math.max(2, part.length));
  if (
    BigInt(whole) * scale + BigInt(part.padEnd(Math.max(2, part.length), "0")) >
    (BigInt("9999999999") * scale) / BigInt(100)
  )
    throw new Error("Factor fuera de rango.");
  return value;
}
export function factorInput(value: string): string {
  const v = canonicalDecimal(value, 18, 1),
    [whole, part = ""] = v.split(".");
  const n =
    BigInt(whole) * BigInt("1000000000000000000") +
    BigInt(part.padEnd(18, "0"));
  if (n < BigInt("100000000000000000") || n > BigInt("5000000000000000000"))
    throw new Error("Usa un factor entre 0,1 y 5, con hasta 18 decimales.");
  return v.includes(".") ? v.replace(/0+$/, "").replace(/\.$/, "") : v;
}
export const factorText = (v: string) => v.replace(".", ",");
export interface ZoneBonusFactor {
  version: 1;
  scope: "zone_bonus_factor";
  zone_id: string;
  revision: number;
  factor: string | null;
  legacy_factor: string | null;
  unit: "dimensionless";
  updated_at: string | null;
  updated_by: string | null;
  application: "prospective_delivery_bonus";
}
export function readZoneFactor(raw: unknown, id: string): ZoneBonusFactor {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("Factor de zona no confirmado.");
  const v = raw as Record<string, unknown>;
  if (
    v.version !== 1 ||
    v.scope !== "zone_bonus_factor" ||
    v.zone_id !== id ||
    !uuid.test(id) ||
    v.unit !== "dimensionless" ||
    v.application !== "prospective_delivery_bonus" ||
    !Number.isSafeInteger(v.revision) ||
    (v.revision as number) < 0 ||
    (v.revision as number) > 2147483647
  )
    throw new Error("El factor no corresponde a la zona o revisión.");
  if (v.legacy_factor !== null) recordedFactor(v.legacy_factor);
  if (v.revision === 0) {
    if (v.factor !== null || v.updated_at !== null || v.updated_by !== null)
      throw new Error("Factor ausente contradictorio.");
  } else if (
    typeof v.factor !== "string" ||
    factorInput(v.factor) !== v.factor ||
    typeof v.updated_at !== "string" ||
    !/(Z|[+-]\d{2}:\d{2})$/.test(v.updated_at) ||
    !Number.isFinite(Date.parse(v.updated_at)) ||
    typeof v.updated_by !== "string" ||
    !uuid.test(v.updated_by)
  )
    throw new Error("Factor o procedencia inválidos.");
  return v as unknown as ZoneBonusFactor;
}
export interface FactorSnapshot {
  version: 1;
  unit: "dimensionless";
  zone_id: string | null;
  zone_revision: number | null;
  zone_factor: string;
  tier_factor: string;
  basis: "declared_exact" | "legacy_decimal_representation" | "no_zone_default";
}
export function readFactorSnapshot(raw: unknown): FactorSnapshot {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("Factores del bono no confirmados.");
  const v = raw as Record<string, unknown>;
  if (
    Object.keys(v).sort().join(",") !==
      [
        "version",
        "unit",
        "zone_id",
        "zone_revision",
        "zone_factor",
        "tier_factor",
        "basis",
      ]
        .sort()
        .join(",") ||
    v.version !== 1 ||
    v.unit !== "dimensionless" ||
    !["1", "1.05", "1.1", "1.15"].includes(v.tier_factor as string)
  )
    throw new Error("Snapshot de factores inválido.");
  recordedFactor(v.zone_factor);
  if (v.basis === "no_zone_default") {
    if (v.zone_id !== null || v.zone_revision !== null || v.zone_factor !== "1")
      throw new Error("Factor por defecto contradictorio.");
  } else {
    if (typeof v.zone_id !== "string" || !uuid.test(v.zone_id))
      throw new Error("Zona del factor inválida.");
    if (v.basis === "declared_exact") {
      if (
        !Number.isSafeInteger(v.zone_revision) ||
        (v.zone_revision as number) < 1 ||
        (v.zone_revision as number) > 2147483647 ||
        typeof v.zone_factor !== "string" ||
        factorInput(v.zone_factor) !== v.zone_factor
      )
        throw new Error("Revisión de factor inválida.");
    } else if (
      v.basis !== "legacy_decimal_representation" ||
      v.zone_revision !== null
    )
      throw new Error("Procedencia de factor inválida.");
  }
  return v as unknown as FactorSnapshot;
}
