"use client";
import { useEffect, useRef, useState } from "react";
import { Calculator, TrendingUp } from "lucide-react";
import {
  OperationMetric,
  OperationNotice,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";
import {
  settingsService,
  type BonusSimulationResponse,
} from "@/services/settings.service";
import {
  settingsNumber,
  settingsTime,
  validateBonusRequest,
} from "@/lib/platform-settings";

export function BonusSimulator({
  currentBase,
  disabled = false,
}: {
  currentBase: number | null;
  disabled?: boolean;
}) {
  const [proposal, setProposal] = useState(
      currentBase === null ? "" : String(currentBase),
    ),
    [days, setDays] = useState("30"),
    [pending, setPending] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<{
      result: BonusSimulationResponse;
      proposed: number;
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
    let bonus: number, period: number;
    try {
      bonus = settingsNumber(proposal, "bono propuesto");
      period = settingsNumber(days, "días históricos");
      validateBonusRequest({ new_base_bonus: bonus, days_projection: period });
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
      const result = await settingsService.simulateBonusImpact({
        new_base_bonus: bonus,
        days_projection: period,
      });
      if (alive.current && !paused.current)
        setSnapshot({ result, proposed: bonus, days: period, at: new Date() });
    } catch (error) {
      if (alive.current)
        setError(
          error instanceof Error && error.name !== "AxiosError"
            ? error.message
            : "No se pudo confirmar el cálculo. Se conserva el último resultado, si existe.",
        );
    } finally {
      writing.current = false;
      if (alive.current) setPending(false);
    }
  };
  const amount = (value: number) =>
    value.toLocaleString("es-VE", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  return (
    <section
      className={`${operationStyles.panel} space-y-5 border-violet-200 p-5`}
      aria-label="Simulador de bonos"
    >
      <SectionHeading
        icon={Calculator}
        title="Simulador de impacto del bono"
        tone="violet"
        description="Compara un bono propuesto con el histórico del período elegido. Simular no guarda el bono ni aplica cambios a la configuración."
      />
      <p className="text-sm text-slate-600">
        Bono guardado:{" "}
        {currentBase === null ? "Sin configurar" : String(currentBase)}.
        Importes sin conversión de moneda.
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
          <label className="space-y-2 text-sm font-medium">
            Bono propuesto
            <input
              className={operationStyles.field}
              inputMode="decimal"
              value={proposal}
              onChange={(event) => setProposal(event.target.value)}
            />
          </label>
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
            Resultado para bono {String(snapshot.proposed)} y {snapshot.days}{" "}
            días de histórico. Consulta: {settingsTime(snapshot.at)} ·
            America/Caracas.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <OperationMetric
              icon={TrendingUp}
              label="Costo histórico"
              value={amount(snapshot.result.current_monthly_cost)}
            />
            <OperationMetric
              icon={Calculator}
              label="Costo con bono propuesto"
              value={amount(snapshot.result.projected_monthly_cost)}
              tone="violet"
            />
            <OperationMetric
              icon={TrendingUp}
              label="Diferencia"
              value={amount(snapshot.result.difference)}
              tone={snapshot.result.difference > 0 ? "amber" : "emerald"}
            />
            <OperationMetric
              icon={Calculator}
              label="Variación"
              value={
                snapshot.result.current_monthly_cost === 0
                  ? "Sin base porcentual"
                  : `${amount(snapshot.result.percentage_increase)} %`
              }
              tone="violet"
            />
          </div>
        </div>
      )}
    </section>
  );
}
