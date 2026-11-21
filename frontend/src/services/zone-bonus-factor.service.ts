import { api } from "@/lib/api";
import { factorInput, readZoneFactor } from "@/lib/zone-bonus-factors";
export const zoneBonusFactorService = {
  async get(id: string) {
    return readZoneFactor(
      await api.get<unknown>(
        `/zones/${encodeURIComponent(id)}/bonus-factor/exact`,
      ),
      id,
    );
  },
  async save(id: string, revision: number, input: string) {
    if (
      !Number.isSafeInteger(revision) ||
      revision < 0 ||
      revision >= 2147483647
    )
      throw new Error("Revisión de factor inválida.");
    const factor = factorInput(input),
      v = readZoneFactor(
        await api.put<unknown>(
          `/zones/${encodeURIComponent(id)}/bonus-factor/exact`,
          { expected_revision: revision, factor },
        ),
        id,
      );
    if (v.revision !== revision + 1 || v.factor !== factor)
      throw new Error(
        "No se pudo confirmar el factor enviado; vuelve a consultar.",
      );
    return v;
  },
};
