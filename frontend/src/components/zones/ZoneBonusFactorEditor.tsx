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
import { factorText } from "@/lib/zone-bonus-factors";
import { riderDate } from "@/lib/rider-display";
import { factorInput, type ZoneBonusFactor } from "@/lib/zone-bonus-factors";
import { zoneBonusFactorService } from "@/services/zone-bonus-factor.service";
export function ZoneBonusFactorEditor({ zoneId }: { zoneId: string }) {
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
  const [value, setValue] = useState<ZoneBonusFactor | null>(null),
    [base, setBase] = useState("");
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
      const next = await zoneBonusFactorService.get(zoneId);
      if (!current()) return;
      setValue(next);
      setBase(next.factor ?? "");

      setNeedsRead(false);
    } catch {
      if (current()) {
        setValue(null);
        setBase("");

        setError(
          "No se pudo confirmar el factor decimal. Consulta antes de guardar.",
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
      factorInput(base);
    } catch {
      setError("Introduce un factor entre 0,1 y 5, con hasta 18 decimales.");
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
      const next = await zoneBonusFactorService.save(
        zoneId,
        value.revision,
        base,
      );
      if (!current()) return;
      if (next.updated_by !== actorId)
        throw new Error("El guardado no corresponde al responsable.");
      setValue(next);
      setBase(next.factor ?? "");

      setNotice("Factor decimal guardado y confirmado.");
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
          "No se pudo confirmar el guardado. Conserva tu borrador y consulta el factor actual antes de volver a guardar.",
        );
      }
    } finally {
      inFlight.current = false;
      if (current()) setSaving(false);
    }
  }
  return (
    <section
      aria-label="Factor de bono de la zona"
      className="space-y-4 rounded-2xl border border-violet-200 bg-white p-5 shadow-sm"
    >
      <div>
        <h2 className="text-lg font-bold text-violet-950">
          Factor del bono por zona
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Multiplicador sin moneda. Solo afecta nuevas liquidaciones; los bonos
          conservados no se recalculan.
        </p>
      </div>
      {loading && <p role="status">Consultando factor…</p>}
      {error && (
        <p
          role="alert"
          className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900"
        >
          {error}
          {value && needsRead && " Se muestra la última lectura confirmada."}
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
            <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
              <p>Factor decimal sin confirmar. Continúa la regla anterior.</p>
              <p>
                Factor anterior:{" "}
                {value.legacy_factor === null
                  ? "Requiere revisión"
                  : factorText(value.legacy_factor) + " × (compatibilidad)"}
              </p>
            </div>
          ) : (
            <div className="rounded-xl bg-violet-50 p-4">
              <p className="text-sm">Factor confirmado</p>
              <p className="break-all text-lg font-bold tabular-nums text-violet-950">
                {factorText(value.factor!)} ×
              </p>
              <p className="mt-2 text-xs text-slate-600">
                Revisión {value.revision} · {riderDate(value.updated_at)} ·
                America/Caracas
              </p>
            </div>
          )}
          {canWrite && (
            <label className="block space-y-2 text-sm font-medium">
              Factor decimal de zona
              <input
                type="text"
                inputMode="decimal"
                className="block min-h-10 w-full rounded-xl border p-3"
                value={base}
                disabled={saving || loading}
                readOnly={needsRead}
                onChange={(e) => setBase(e.target.value)}
              />
            </label>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          className="min-h-10 rounded-xl border border-violet-200 px-4 py-2 text-sm font-semibold text-violet-800 disabled:opacity-50"
          disabled={loading || saving}
          onClick={() => void read()}
        >
          Consultar factor actual
        </button>
        {canWrite && (
          <button
            type="button"
            className="min-h-10 rounded-xl bg-violet-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            disabled={!value || loading || saving || needsRead}
            onClick={() => void save()}
          >
            {saving ? "Guardando factor…" : "Guardar factor decimal"}
          </button>
        )}
      </div>
      <p className="text-xs text-slate-600">
        Entre 0,1 y 5, con hasta 18 decimales. Consultar descarta el borrador y
        carga la revisión actual.
      </p>
    </section>
  );
}
