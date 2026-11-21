import { api } from "@/lib/api";
import {
  readZoneTariff,
  zoneMoneyInput,
  type ZoneTariff,
} from "@/lib/zone-tariffs";
export const zoneTariffService = {
  async get(id: string): Promise<ZoneTariff> {
    return readZoneTariff(
      await api.get<unknown>(`/zones/${encodeURIComponent(id)}/tariff/exact`),
      id,
    );
  },
  async getMany(ids: string[]): Promise<Record<string, ZoneTariff>> {
    if (!ids.length) return {};
    if (ids.length > 100 || new Set(ids).size !== ids.length)
      throw new Error("Catálogo de zonas inválido.");
    const params = new URLSearchParams();
    ids.forEach((id) => params.append("zone_ids", id));
    const raw = await api.get<unknown>("/zones/tariffs/exact", { params });
    if (!raw || typeof raw !== "object" || Array.isArray(raw))
      throw new Error("Catálogo de tarifas inválido.");
    const v = raw as Record<string, unknown>;
    if (
      v.version !== 1 ||
      v.scope !== "zone_usd_tariffs" ||
      !Array.isArray(v.items) ||
      v.items.length !== ids.length
    )
      throw new Error("Catálogo de tarifas incompleto.");
    const result: Record<string, ZoneTariff> = {};
    for (const item of v.items) {
      const id =
        item && typeof item === "object"
          ? (item as Record<string, unknown>).zone_id
          : undefined;
      if (typeof id !== "string" || !ids.includes(id) || result[id])
        throw new Error("Identidades de tarifas contradictorias.");
      result[id] = readZoneTariff(item, id);
    }
    return result;
  },
  async save(
    id: string,
    revision: number,
    base: string,
    perKm: string,
  ): Promise<ZoneTariff> {
    if (
      !Number.isSafeInteger(revision) ||
      revision < 0 ||
      revision >= 2147483647
    )
      throw new Error("Revisión de tarifa inválida.");
    const base_usd = zoneMoneyInput(base),
      per_km_usd = zoneMoneyInput(perKm);
    const value = readZoneTariff(
      await api.put<unknown>(`/zones/${encodeURIComponent(id)}/tariff/exact`, {
        expected_revision: revision,
        currency: "USD",
        base_usd,
        per_km_usd,
      }),
      id,
    );
    if (
      value.revision !== revision + 1 ||
      value.base_usd !== base_usd ||
      value.per_km_usd !== per_km_usd
    )
      throw new Error(
        "No se pudo confirmar la tarifa enviada; vuelve a consultar.",
      );
    return value;
  },
};
