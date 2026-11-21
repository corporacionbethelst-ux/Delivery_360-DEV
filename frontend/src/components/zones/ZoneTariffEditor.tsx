"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useAuthStore } from "@/stores/authStore";
import {
  getCredentialGeneration,
  onCredentialsChanged,
} from "@/lib/auth-session";
import { capturePrivateTask } from "@/lib/private-task";
import { moneyText } from "@/lib/currency";
import { riderDate } from "@/lib/rider-display";
import { zoneMoneyInput, type ZoneTariff } from "@/lib/zone-tariffs";
import { zoneTariffService } from "@/services/zone-tariff.service";
export function ZoneTariffEditor({ zoneId }: { zoneId: string }) {
  const { user, isAuthenticated } = useAuthStore();
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  if (
    !isAuthenticated ||
    !user ||
    !["SUPERADMIN", "GERENTE", "OPERADOR"].includes(user.role)
  )
    return null;
  return (
    <Editor
      key={JSON.stringify([zoneId, user.id, user.role, generation])}
      zoneId={zoneId}
      actorId={user.id}
      canWrite={["SUPERADMIN", "GERENTE"].includes(user.role)}
    />
  );
}
function Editor({
  zoneId,
  canWrite,
  actorId,
}: {
  zoneId: string;
  canWrite: boolean;
  actorId: string;
}) {
  const [value, setValue] = useState<ZoneTariff | null>(null),
    [base, setBase] = useState(""),
    [perKm, setPerKm] = useState("");
  const [loading, setLoading] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState<string | null>(null),
    [notice, setNotice] = useState<string | null>(null);
  const [needsRead, setNeedsRead] = useState(false);
  const sequence = useRef(0),
    inFlight = useRef(false);
  const read = useCallback(async () => {
    if (inFlight.current) return;
    const ticket = ++sequence.current;
    let current = () => ticket === sequence.current;
    setLoading(true);
    setError(null);
    setNotice(null);
    setNeedsRead(true);
    try {
      const task = capturePrivateTask();
      current = () => ticket === sequence.current && task.isCurrent();
      const next = await zoneTariffService.get(zoneId);
      if (!current()) return;
      setValue(next);
      setBase(next.base_usd ?? "");
      setPerKm(next.per_km_usd ?? "");
      setNeedsRead(false);
    } catch {
      if (current()) {
        setValue(null);
        setBase("");
        setPerKm("");
        setError(
          "No se pudieron confirmar las tarifas USD. Vuelve a consultar antes de guardar.",
        );
      }
    } finally {
      if (current()) setLoading(false);
    }
  }, [zoneId]);
  useEffect(() => {
    void read();
    const requests = sequence;
    return () => {
      requests.current++;
    };
  }, [read]);
  async function save() {
    if (!canWrite || !value || needsRead || loading || inFlight.current) return;
    try {
      zoneMoneyInput(base);
      zoneMoneyInput(perKm);
    } catch {
      setError(
        "Introduce ambas tarifas con hasta dos decimales, sin negativos ni separadores de miles.",
      );
      return;
    }
    inFlight.current = true;
    setSaving(true);
    setError(null);
    setNotice(null);
    const ticket = sequence.current;
    let current = () => ticket === sequence.current;
    try {
      const task = capturePrivateTask();
      current = () => ticket === sequence.current && task.isCurrent();
      const next = await zoneTariffService.save(
        zoneId,
        value.revision,
        base,
        perKm,
      );
      if (!current()) return;
      if (next.updated_by !== actorId)
        throw new Error("El guardado no corresponde al responsable.");
      setValue(next);
      setBase(next.base_usd ?? "");
      setPerKm(next.per_km_usd ?? "");
      setNotice("Tarifas USD guardadas y confirmadas.");
    } catch (failure) {
      if (current()) {
        setNeedsRead(true);
        const e = failure as {
          response?: { status?: number };
          status?: number;
        } | null;
        if ([401, 403].includes(e?.response?.status ?? e?.status ?? 0))
          setValue(null);
        setError(
          "No se pudo confirmar el guardado. Conserva tu borrador y consulta las tarifas actuales antes de volver a guardar.",
        );
      }
    } finally {
      inFlight.current = false;
      if (current()) setSaving(false);
    }
  }
  return (
    <section
      aria-label="Tarifas USD de la zona"
      className="space-y-4 rounded-2xl border border-emerald-200 bg-white p-5 shadow-sm"
    >
      <div>
        <h2 className="text-lg font-bold text-emerald-950">
          Tarifas de zona en USD
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Configuración explícita de la zona. No recalcula órdenes, precios
          registrados ni bonos.
        </p>
      </div>
      {loading && <p role="status">Consultando tarifas…</p>}
      {error && (
        <p
          role="alert"
          className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          role="status"
          className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900"
        >
          {notice}
        </p>
      )}
      {value && (
        <>
          {value.revision === 0 ? (
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
              Tarifas USD sin configurar. Los importes anteriores se conservan
              sin asignarles moneda.
            </p>
          ) : (
            <>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-emerald-50 p-4">
                  <dt>Base configurada</dt>
                  <dd className="font-bold tabular-nums">
                    {moneyText(value.base_usd!, "USD")}
                  </dd>
                </div>
                <div className="rounded-xl bg-blue-50 p-4">
                  <dt>Por kilómetro</dt>
                  <dd className="font-bold tabular-nums">
                    {moneyText(value.per_km_usd!, "USD")}
                  </dd>
                </div>
              </dl>
              <p className="text-xs text-slate-600">
                Revisión {value.revision} · {riderDate(value.updated_at)} ·
                America/Caracas
              </p>
            </>
          )}
          {canWrite && (
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2 text-sm font-medium">
                Tarifa base USD
                <input
                  className="block min-h-10 w-full rounded-xl border p-3"
                  inputMode="decimal"
                  type="text"
                  value={base}
                  disabled={saving || loading || needsRead}
                  onChange={(e) => setBase(e.target.value)}
                />
              </label>
              <label className="space-y-2 text-sm font-medium">
                Tarifa por kilómetro USD
                <input
                  className="block min-h-10 w-full rounded-xl border p-3"
                  inputMode="decimal"
                  type="text"
                  value={perKm}
                  disabled={saving || loading || needsRead}
                  onChange={(e) => setPerKm(e.target.value)}
                />
              </label>
            </div>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          className="min-h-10 rounded-xl border border-blue-200 px-4 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50"
          disabled={loading || saving}
          onClick={() => void read()}
        >
          Consultar tarifas actuales
        </button>
        {canWrite && (
          <button
            type="button"
            className="min-h-10 rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            disabled={!value || loading || saving || needsRead}
            onClick={() => void save()}
          >
            {saving ? "Guardando tarifas…" : "Guardar tarifas USD"}
          </button>
        )}
      </div>
      <p className="text-xs text-slate-600">
        Usa hasta dos decimales, sin separadores de miles. Un cero debe
        introducirse expresamente. Consultar descarta el borrador y carga la
        revisión actual.
      </p>
    </section>
  );
}
