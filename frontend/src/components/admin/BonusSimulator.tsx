"use client";
import axios from "axios";
import { useAuthStore } from "@/stores/authStore";
import { cashCents } from "@/lib/customer-cashbook";
import { useEffect, useRef, useState } from "react";
import {
  Calculator,
  CalendarDays,
  PackageCheck,
  TrendingUp,
} from "lucide-react";
import {
  OperationMetric,
  OperationNotice,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import {
  settingsService,
  type BonusSimulationResponse,
} from "@/services/bonus-settings-exact.service";
import {
  parameterInput,
  usdText,
  decimalText,
  settingsTime,
  validateBonusRequest,
} from "@/lib/bonus-settings-exact";

export function BonusSimulator({
  currentBase,
  disabled = false,
}: {
  currentBase: string | null;
  disabled?: boolean;
}) {
  const { user } = useAuthStore();
  const [proposal, setProposal] = useState(
      currentBase === null ? "" : String(currentBase),
    ),
    [days, setDays] = useState("30"),
    [pending, setPending] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<{
      result: BonusSimulationResponse;
      proposed: string;
      days: number;
      at: Date;
    } | null>(null),
    alive = useRef(false),
    writing = useRef(false),
    paused = useRef(disabled);
  paused.current = disabled;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const simulate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (disabled || currentBase === null || writing.current) return;
    let bonus: string, period: number;
    try {
      bonus = parameterInput(proposal);
      if (!/^(?:[1-9]|[1-8][0-9]|90)$/.test(days.trim()))
        throw new Error("Usa entre 1 y 90 días enteros.");
      period = Number(days.trim());
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Revisa los datos de la simulación.",
      );
      return;
    }
    writing.current = true;
    setPending(true);
    setError(null);
    try {
      const fresh = await settingsService.getSettings();
      if (!alive.current || paused.current) return;
      if (fresh.rider_delivery_bonus !== currentBase)
        throw new Error(
          "El bono guardado cambió. Recarga la configuración antes de simular.",
        );
      if (!user)
        throw new Error("La sesión no permite confirmar el escenario.");
      const request = {
        new_base_bonus: bonus,
        days_projection: period,
        expected_settings_revision: fresh.revision,
      };
      validateBonusRequest(request);
      const result = await settingsService.simulateBonusImpact(request, {
        user_id: user.id,
        role: user.role,
      });
      if (alive.current && !paused.current)
        setSnapshot({ result, proposed: bonus, days: period, at: new Date() });
    } catch (error) {
      if (alive.current)
        setError(
          axios.isAxiosError(error) && error.response?.status === 412
            ? "La configuración cambió durante el cálculo. Recarga antes de simular de nuevo; se conserva el resultado anterior."
            : axios.isAxiosError(error) && error.response?.status === 409
              ? "El bono guardado o el histórico no permiten confirmar el cálculo. Revisa la configuración y los bonos registrados."
              : error instanceof Error && error.name !== "AxiosError"
                ? error.message
                : "No se pudo confirmar el cálculo. Se conserva el último resultado, si existe.",
        );
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const amount = usdText;
  return (
    <section
      className={`${operationStyles.panel} space-y-5 border-violet-200 p-5`}
      aria-label="Simulador de bonos"
    >
      <SectionHeading
        icon={Calculator}
        title="Escenario de bono uniforme"
        tone="violet"
        description="Compara un bono uniforme para las mismas entregas completadas del período elegido. Conserva los bonos registrados por intentos fallidos. Simular no guarda cambios."
      />
      <p className="text-sm text-slate-600">
        Bono guardado:{" "}
        {currentBase === null ? "Sin configurar" : amount(currentBase)}. Los
        bonos históricos conservan su propia moneda; solo los snapshots USD
        entran al cálculo.
      </p>
      {currentBase === null && (
        <OperationNotice tone="warning">
          Configura un bono por entrega antes de simular.
        </OperationNotice>
      )}
      <form onSubmit={simulate} noValidate>
        <fieldset
          disabled={disabled || pending || currentBase === null}
          className="grid min-w-0 items-end gap-4 md:grid-cols-3"
        >
          <div className="space-y-2 text-sm font-medium">
            <label htmlFor="uniform-bonus-proposal">Bono propuesto</label>
            <input
              id="uniform-bonus-proposal"
              aria-describedby="uniform-bonus-help"
              className={operationStyles.field}
              inputMode="decimal"
              value={proposal}
              onChange={(event) => setProposal(event.target.value)}
            />
            <span
              id="uniform-bonus-help"
              className="block text-xs font-normal text-slate-600"
            >
              Importe USD uniforme con hasta dos decimales; no modifica los
              bonos guardados.
            </span>
          </div>
          <label className="space-y-2 text-sm font-medium">
            Días de histórico
            <input
              className={operationStyles.field}
              inputMode="numeric"
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
            <span className="block text-xs text-slate-600">
              Entre 1 y 90 días.
            </span>
          </label>
          <button className={operationStyles.primaryButton} type="submit">
            {pending ? "Calculando…" : "Simular impacto"}
          </button>
        </fieldset>
      </form>
      {error && (
        <OperationNotice role="alert" tone="warning">
          {error}
        </OperationNotice>
      )}
      {snapshot && (
        <div
          className="space-y-4"
          role="region"
          aria-label="Resultado confirmado de simulación"
        >
          <p className="text-sm text-slate-600">
            Resultado para bono {amount(snapshot.proposed)} y {snapshot.days}{" "}
            días de histórico. Consulta: {settingsTime(snapshot.at)} ·
            America/Caracas.
          </p>
          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
            <p className="flex items-center gap-2 font-semibold">
              <CalendarDays aria-hidden="true" className="h-4 w-4" />
              Período histórico consultado
            </p>
            <p className="mt-1">
              Desde {settingsTime(snapshot.result.period_start)} hasta{" "}
              {settingsTime(snapshot.result.period_end)} (fin excluido),
              America/Caracas.
            </p>
          </div>
          <OperationNotice>
            Este escenario usa las mismas entregas históricas. No aplica
            multiplicadores de zona ni nivel, no predice actividad futura y no
            confirma pagos. No modifica los bonos congelados.
          </OperationNotice>
          {snapshot.result.exclusions.unknown_currency +
            snapshot.result.exclusions.other_currency +
            snapshot.result.exclusions.no_bonus +
            snapshot.result.exclusions.invalid_snapshot >
            0 && (
            <OperationNotice tone="warning">
              Fuera del cálculo: {snapshot.result.exclusions.unknown_currency}{" "}
              sin moneda registrada; {snapshot.result.exclusions.other_currency}{" "}
              de otra moneda; {snapshot.result.exclusions.no_bonus} sin bono;{" "}
              {snapshot.result.exclusions.invalid_snapshot} con snapshot por
              revisar. Ninguno de esos importes se convierte a USD.
            </OperationNotice>
          )}
          {snapshot.result.exclusions.undated > 0 && (
            <OperationNotice tone="warning">
              Existen {snapshot.result.exclusions.undated} cierres sin fecha de
              cierre ni fecha del bono en el histórico global. Quedan fuera del
              cálculo porque no se pueden ubicar en este período.
            </OperationNotice>
          )}
          {snapshot.result.completed_deliveries === 0 &&
            snapshot.result.failed_bonus_deliveries === 0 && (
              <OperationNotice tone="warning">
                Sin bonos USD elegibles en el período consultado. Los ceros
                corresponden a esta muestra vacía.
              </OperationNotice>
            )}
          <div className="grid gap-4 sm:grid-cols-2">
            <OperationMetric
              icon={TrendingUp}
              label="Bonos USD históricos registrados"
              value={amount(snapshot.result.historical_cost)}
            />
            <OperationMetric
              icon={Calculator}
              label="Total del escenario uniforme"
              value={amount(snapshot.result.scenario_cost)}
              tone="violet"
            />
            <OperationMetric
              icon={TrendingUp}
              label="Diferencia"
              value={amount(snapshot.result.difference)}
              tone={
                cashCents(snapshot.result.difference, true) > BigInt(0)
                  ? "amber"
                  : "emerald"
              }
            />
            <OperationMetric
              icon={Calculator}
              label="Variación"
              value={
                snapshot.result.percentage_change === null
                  ? "Sin base porcentual"
                  : `${decimalText(snapshot.result.percentage_change)} %`
              }
              tone="violet"
            />
            <OperationMetric
              icon={PackageCheck}
              label="Entregas completadas de la muestra"
              value={snapshot.result.completed_deliveries}
            />
            <OperationMetric
              icon={Calculator}
              label="Intentos fallidos bonificados"
              value={snapshot.result.failed_bonus_deliveries}
              tone="amber"
            />
          </div>
          <p className="break-all text-xs text-slate-500">
            Huella del escenario: {snapshot.result.content_sha256} · Corte SQL:{" "}
            {settingsTime(snapshot.result.generated_at)}
          </p>
          <p className="rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">
            Cálculo: {snapshot.result.completed_deliveries} entregas ×{" "}
            {amount(snapshot.result.applied_bonus)} de bono uniforme +{" "}
            {amount(snapshot.result.recorded_failed_bonus)} de bonos fallidos
            registrados, todos en USD. No representa saldo disponible ni
            verificación bancaria.
          </p>
        </div>
      )}
    </section>
  );
}
