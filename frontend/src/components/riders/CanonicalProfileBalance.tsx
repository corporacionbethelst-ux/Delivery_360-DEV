"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  getCredentialGeneration,
  onCredentialsChanged,
} from "@/lib/auth-session";
import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  validateRiderBalance,
  type RiderExactBalance,
} from "@/lib/rider-earnings-exact";
import { riderDate } from "@/lib/rider-display";
import { moneyText } from "@/lib/currency";

export type StaffProfileBalance = Omit<RiderExactBalance, "scope"> & {
  scope: "staff_canonical_usd_balance";
  actor: { user_id: string; role: string };
};

export function readStaffBalance(
  raw: unknown,
  riderId: string,
  actorId: string,
  role: string,
  ownerId?: string,
): StaffProfileBalance {
  const v =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : null;
  const actor =
    v?.actor && typeof v.actor === "object" && !Array.isArray(v.actor)
      ? (v.actor as Record<string, unknown>)
      : null;
  if (
    !v ||
    v.scope !== "staff_canonical_usd_balance" ||
    v.rider_id !== riderId ||
    (ownerId !== undefined && v.user_id !== ownerId) ||
    !["SUPERADMIN", "GERENTE"].includes(role) ||
    typeof v.user_id !== "string" ||
    actor?.user_id !== actorId ||
    actor?.role !== role
  )
    throw new Error(
      "La lectura financiera no corresponde al perfil o al responsable.",
    );
  const checked = validateRiderBalance(
    { ...v, scope: "own_canonical_usd_balance" },
    v.user_id,
  );
  return {
    ...checked,
    scope: "staff_canonical_usd_balance",
    actor: { user_id: actorId, role },
  };
}

export function CanonicalProfileBalance({
  riderId,
  actorId,
  role,
  ownerId,
}: {
  riderId: string;
  actorId: string;
  role: string;
  ownerId?: string;
}) {
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  return (
    <BalanceRead
      key={JSON.stringify([riderId, ownerId, actorId, role, generation])}
      riderId={riderId}
      actorId={actorId}
      role={role}
      ownerId={ownerId}
    />
  );
}

function BalanceRead({
  riderId,
  actorId,
  role,
  ownerId,
}: {
  riderId: string;
  actorId: string;
  role: string;
  ownerId?: string;
}) {
  const [value, setValue] = useState<StaffProfileBalance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const sequence = useRef(0);
  const allowed = role === "SUPERADMIN" || role === "GERENTE";
  const load = useCallback(async () => {
    if (!allowed) return;
    const ticket = ++sequence.current;
    let current = () => ticket === sequence.current;
    setLoading(true);
    setError(null);
    try {
      const task = capturePrivateTask();
      current = () => ticket === sequence.current && task.isCurrent();
      const data = await api.get<unknown>(
        `/payouts/riders/${encodeURIComponent(riderId)}/balance/exact`,
      );
      if (!current()) return;
      setValue(readStaffBalance(data, riderId, actorId, role, ownerId));
    } catch (failure) {
      const rejected = failure as {
        status?: number;
        response?: { status?: number };
      } | null;
      const status = rejected?.status ?? rejected?.response?.status;
      if (current() && (status === 401 || status === 403)) setValue(null);
      if (current())
        setError(
          "No se pudo confirmar el saldo USD. Revisa el libro o reintenta la consulta.",
        );
    } finally {
      if (current()) setLoading(false);
    }
  }, [allowed, riderId, ownerId, actorId, role]);
  useEffect(() => {
    void load();
    const requests = sequence;
    return () => {
      requests.current++;
    };
  }, [load]);
  if (!allowed)
    return (
      <p className="text-sm text-slate-600">
        La consulta financiera requiere acceso de gerencia.
      </p>
    );
  return (
    <div className="space-y-4">
      {loading && (
        <p role="status" className="text-sm text-slate-600">
          Consultando libro y reservas…
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          {error}
          {value && " Se conserva la última lectura confirmada."}
        </p>
      )}
      {value && (
        <>
          <dl className="space-y-3">
            {(
              [
                ["Saldo del libro USD", value.ledger_balance],
                ["Reservas de retiro", value.reserved],
                ["Disponible contable", value.available],
              ] as const
            ).map(([label, amount]) => (
              <div
                key={label}
                className="flex flex-wrap justify-between gap-2 rounded-xl bg-emerald-50 p-4"
              >
                <dt>{label}</dt>
                <dd className="font-bold tabular-nums">
                  {amount.startsWith("-")
                    ? "−" + moneyText(amount.slice(1), "USD")
                    : moneyText(amount, "USD")}
                </dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-slate-600">
            Corte: {riderDate(value.generated_at)} · America/Caracas. Libro{" "}
            {value.ledger_integrity === "verified"
              ? "verificado"
              : "sin movimientos USD"}
            . No confirma un pago bancario.
          </p>
          {(value.unverified_financial_count > 0 ||
            value.unverified_payout_count > 0) && (
            <p className="text-sm text-amber-900">
              Fuera del saldo USD: {value.unverified_financial_count}{" "}
              movimientos y {value.unverified_payout_count} retiros sin moneda
              verificada.
            </p>
          )}
        </>
      )}
      <button
        type="button"
        onClick={() => void load()}
        disabled={loading}
        className="min-h-10 rounded-xl border border-blue-200 px-4 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50"
      >
        {error ? "Reintentar saldo" : "Actualizar saldo"}
      </button>
    </div>
  );
}
