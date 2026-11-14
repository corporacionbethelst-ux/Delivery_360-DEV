"use client";

import axios from "axios";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowLeftRight,
  CheckCircle2,
  ExternalLink,
  History,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  OperationNotice,
  SectionHeading,
  operationStyles as styles,
} from "@/components/operations/OperationsUI";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { currencyService } from "@/services/currency.service";
import {
  canonicalDecimal,
  moneyText,
  type BcvRateInput,
  type CurrencyContext,
  type UsdVesQuote,
  type UsdVesQuoteInput,
} from "@/lib/currency";
import { useAuthStore } from "@/stores/authStore";

function failure(error: unknown): string {
  if (
    axios.isAxiosError(error) &&
    typeof error.response?.data?.detail === "string"
  )
    return error.response.data.detail;
  return error instanceof Error
    ? error.message
    : "No se pudo confirmar la operación. Conserva los datos y vuelve a consultar.";
}
const dayText = (day: string) => day.split("-").reverse().join("/");

export default function CurrencyPage() {
  return (
    <ManagerPageBoundary
      scope="usd-ves-currency"
      roles={["SUPERADMIN", "GERENTE", "OPERADOR"]}
    >
      <CurrencyForm />
    </ManagerPageBoundary>
  );
}
function CurrencyForm() {
  const { user } = useAuthStore();
  const administrator = user?.role === "SUPERADMIN" || user?.role === "GERENTE";
  const [data, setData] = useState<CurrencyContext | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null),
    [success, setSuccess] = useState<string | null>(null);
  const [rate, setRate] = useState(""),
    [referenceDate, setReferenceDate] = useState(""),
    [note, setNote] = useState(""),
    [verified, setVerified] = useState(false);
  const [amount, setAmount] = useState(""),
    [reference, setReference] = useState(""),
    [receipt, setReceipt] = useState<UsdVesQuote | null>(null);
  const [confirmation, setConfirmation] = useState<BcvRateInput | null>(null);
  const alive = useRef(false),
    sequence = useRef(0),
    writing = useRef(false),
    pendingQuote = useRef<UsdVesQuoteInput | null>(null);

  const load = useCallback(async () => {
    if (writing.current) return;
    const ticket = ++sequence.current;
    setLoading(true);
    setError(null);
    try {
      const result = await currencyService.context();
      if (!alive.current || ticket !== sequence.current) return;
      setData(result);
      setReferenceDate((value) => value || result.today);
    } catch (problem) {
      if (alive.current && ticket === sequence.current)
        setError(failure(problem));
    } finally {
      if (alive.current && ticket === sequence.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    const id = new URL(window.location.href).searchParams.get("quote");
    if (id)
      void currencyService
        .receipt(id)
        .then((result) => {
          if (alive.current) setReceipt(result);
        })
        .catch((problem) => {
          if (alive.current) setError(failure(problem));
        });
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, [load]);

  const reviewRate = (event: FormEvent) => {
    event.preventDefault();
    if (!data || writing.current) return;
    setError(null);
    setSuccess(null);
    try {
      if (!verified)
        throw new Error(
          "Confirma que verificaste la referencia BCV para el día indicado.",
        );
      const value = canonicalDecimal(rate, 8, 9);
      if (BigInt(value.replace(".", "")) === BigInt(0))
        throw new Error("La tasa debe ser mayor que cero.");
      if (!referenceDate || referenceDate > data.today || !note.trim())
        throw new Error("Revisa la fecha de referencia y su nota.");
      if (referenceDate < data.today && note.trim().length < 10)
        throw new Error(
          "Explica por qué la referencia anterior sigue vigente hoy.",
        );
      setConfirmation({
        request_key: crypto.randomUUID(),
        previous_rate_id: data.current_rate?.id ?? null,
        valid_on: data.today,
        reference_date: referenceDate,
        ves_per_usd: value,
        note: note.trim(),
        confirmed_bcv: true,
      });
    } catch (problem) {
      setError(failure(problem));
    }
  };
  const saveRate = async () => {
    if (!confirmation || writing.current) return;
    writing.current = true;
    setBusy(true);
    setError(null);
    try {
      await currencyService.saveRate(confirmation);
      const result = await currencyService.context();
      if (!alive.current) return;
      setData(result);
      setConfirmation(null);
      setVerified(false);
      setSuccess(
        "Referencia guardada. Las cotizaciones anteriores conservan su tasa.",
      );
    } catch (problem) {
      if (alive.current) {
        setError(failure(problem));
        if (axios.isAxiosError(problem) && problem.response?.status === 412)
          setConfirmation(null);
      }
    } finally {
      writing.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const saveQuote = async (event: FormEvent) => {
    event.preventDefault();
    if (!data?.current_rate || writing.current) return;
    setError(null);
    setSuccess(null);
    try {
      const value = canonicalDecimal(amount, 2, 12),
        label = reference.trim();
      if (!label)
        throw new Error(
          "Escribe una referencia para identificar la cotización.",
        );
      let input = pendingQuote.current;
      if (
        !input ||
        input.rate_id !== data.current_rate.id ||
        input.amount_usd !== value ||
        input.reference !== label
      )
        input = {
          request_key: crypto.randomUUID(),
          rate_id: data.current_rate.id,
          amount_usd: value,
          reference: label,
        };
      pendingQuote.current = input;
      writing.current = true;
      setBusy(true);
      const result = await currencyService.quote(input);
      if (!alive.current) return;
      setReceipt(result);
      pendingQuote.current = null;
      window.history.replaceState(
        null,
        "",
        window.location.pathname + "?quote=" + result.id,
      );
      setSuccess(
        "Cotización conservada. Puedes recuperar este mismo comprobante mediante su enlace.",
      );
    } catch (problem) {
      if (alive.current) setError(failure(problem));
    } finally {
      writing.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <OperationsHeader
        title="USD y bolívares"
        eyebrow="Venezuela · Referencia BCV"
        icon={ArrowLeftRight}
        description="Tasas diarias y cotizaciones con importes y referencias conservados."
        actions={
          <button
            className={styles.button}
            disabled={loading || busy}
            onClick={() => void load()}
          >
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
            Actualizar referencias
          </button>
        }
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-700">
            Base de cotización
          </p>
          <p className="mt-2 text-3xl font-bold text-emerald-950">USD</p>
          <p className="mt-1 text-sm text-emerald-800">
            Importes expresados en dólares.
          </p>
        </div>
        <div className="rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-blue-700">
            Equivalente
          </p>
          <p className="mt-2 text-3xl font-bold text-blue-950">VES · Bs.</p>
          <p className="mt-1 text-sm text-blue-800">
            Redondeo a dos decimales.
          </p>
        </div>
        <div className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-white p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-violet-700">
            Día consultado · Caracas
          </p>
          <p className="mt-2 text-xl font-bold text-violet-950">
            {data ? dayText(data.today) : "Por confirmar"}
          </p>
          <p className="mt-1 text-sm text-violet-800">
            Referencia diaria, sin tasa implícita.
          </p>
        </div>
      </div>
      <OperationNotice tone="warning">
        La referencia se registra manualmente después de verificar BCV. La
        consulta automática no está habilitada. Esta herramienta convierte
        importes declarados en USD; no cambia saldos históricos ni confirma
        pagos.
      </OperationNotice>
      {error && (
        <OperationNotice role="alert" tone="warning">
          {error}
        </OperationNotice>
      )}
      {success && (
        <OperationNotice role="status" tone="success">
          {success}
        </OperationNotice>
      )}
      {loading && <p role="status">Consultando referencias…</p>}
      {data && !loading && !data.current_rate && (
        <OperationNotice>
          Falta una referencia registrada para el {dayText(data.today)}. No se
          permite usar la tasa de otro día para una cotización nueva.
        </OperationNotice>
      )}
      {data?.current_rate && (
        <section
          className="rounded-2xl border border-indigo-200 bg-indigo-50 p-5"
          aria-label="Referencia del día consultado"
        >
          <p className="text-sm font-semibold text-indigo-800">
            1 USD = {data.current_rate.ves_per_usd.replace(".", ",")} Bs.
          </p>
          <p className="mt-2 text-sm text-indigo-900">
            Día de uso: {dayText(data.current_rate.valid_on)} · Referencia:{" "}
            {dayText(data.current_rate.reference_date)} · Revisión{" "}
            {data.current_rate.revision}
          </p>
          <p className="mt-1 break-words text-sm text-indigo-800">
            {data.current_rate.note}
          </p>
          <p className="mt-2 text-xs text-indigo-700">
            Registro manual ·{" "}
            {new Date(data.current_rate.recorded_at).toLocaleString("es-VE", {
              timeZone: "America/Caracas",
            })}
          </p>
        </section>
      )}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <section className={styles.panel + " p-5 sm:p-6"}>
          <SectionHeading
            icon={ShieldCheck}
            title="Registrar referencia BCV"
            description="Cada corrección conserva las referencias y cotizaciones anteriores."
            tone="violet"
          />
          <a
            href="https://www.bcv.org.ve/"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.link + " mt-3 text-sm"}
          >
            Consultar BCV
            <ExternalLink aria-hidden="true" className="h-4 w-4" />
          </a>
          {!administrator ? (
            <p className="mt-5 text-sm text-slate-600">
              Solo gerencia y superadministración pueden registrar tasas.
            </p>
          ) : (
            <form onSubmit={reviewRate} className="mt-5 space-y-4">
              <label className="block space-y-1 text-sm font-medium">
                Bolívares por 1 USD
                <input
                  className={styles.field}
                  inputMode="decimal"
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                  disabled={busy || !data}
                  required
                  aria-describedby="rate-help"
                />
              </label>
              <p id="rate-help" className="text-xs text-slate-500">
                Hasta ocho decimales. Usa coma o punto decimal, sin separadores
                de miles.
              </p>
              <label className="block space-y-1 text-sm font-medium">
                Fecha de la referencia BCV
                <input
                  className={styles.field}
                  type="date"
                  max={data?.today}
                  value={referenceDate}
                  onChange={(e) => setReferenceDate(e.target.value)}
                  disabled={busy || !data}
                  required
                />
              </label>
              <label className="block space-y-1 text-sm font-medium">
                Nota de verificación
                <textarea
                  className={styles.field + " min-h-24"}
                  value={note}
                  maxLength={500}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={busy || !data}
                  required
                  placeholder="Referencia consultada o motivo de vigencia durante un día sin publicación."
                />
              </label>
              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0"
                  checked={verified}
                  onChange={(e) => setVerified(e.target.checked)}
                  disabled={busy || !data}
                />
                Verifiqué la referencia BCV y su vigencia para el día
                consultado.
              </label>
              <button
                className={styles.primaryButton}
                disabled={busy || !data || !verified}
                type="submit"
              >
                Revisar tasa
              </button>
            </form>
          )}
        </section>
        <section className={styles.panel + " p-5 sm:p-6"}>
          <SectionHeading
            icon={ArrowLeftRight}
            title="Guardar una cotización"
            description="El comprobante conserva la tasa elegida y el equivalente exacto en VES."
            tone="emerald"
          />
          <form onSubmit={saveQuote} className="mt-5 space-y-4">
            <label className="block space-y-1 text-sm font-medium">
              Importe en USD
              <input
                className={styles.field}
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                disabled={busy || !data?.current_rate || loading}
                required
              />
            </label>
            <label className="block space-y-1 text-sm font-medium">
              Referencia de la cotización
              <input
                className={styles.field}
                value={reference}
                maxLength={120}
                onChange={(e) => setReference(e.target.value)}
                disabled={busy || !data?.current_rate || loading}
                required
                placeholder="Concepto para identificar este importe"
              />
            </label>
            <button
              className={styles.primaryButton}
              disabled={busy || !data?.current_rate || loading}
              type="submit"
            >
              Guardar cotización
            </button>
          </form>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">
            La cotización no reserva fondos ni registra una transferencia. Una
            tasa nueva no recalcula comprobantes guardados.
          </p>
        </section>
      </div>
      {receipt && (
        <section
          className="rounded-2xl border border-emerald-200 bg-white p-5 shadow-sm sm:p-6"
          role="region"
          aria-label="Cotización conservada"
        >
          <SectionHeading
            icon={CheckCircle2}
            title="Cotización conservada"
            description={receipt.reference}
            tone="emerald"
          />
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl bg-emerald-50 p-4">
              <p className="text-xs font-semibold uppercase text-emerald-700">
                Importe base
              </p>
              <p className="mt-2 break-all text-2xl font-bold text-emerald-950">
                {moneyText(receipt.amount_usd, "USD")}
              </p>
            </div>
            <div className="rounded-xl bg-blue-50 p-4">
              <p className="text-xs font-semibold uppercase text-blue-700">
                Equivalente guardado
              </p>
              <p className="mt-2 break-all text-2xl font-bold text-blue-950">
                {moneyText(receipt.amount_ves, "VES")}
              </p>
            </div>
          </div>
          <p className="mt-4 text-sm text-slate-700">
            Tasa guardada: {receipt.rate.ves_per_usd.replace(".", ",")} Bs./USD
            · Día {dayText(receipt.rate.valid_on)} · Revisión{" "}
            {receipt.rate.revision}
          </p>
          <p className="mt-2 text-sm text-slate-600">
            Este importe permanece vinculado a esa referencia. No confirma un
            pago.
          </p>
          <a
            className={styles.link + " mt-4 break-all text-sm"}
            href={"?quote=" + receipt.id}
          >
            Recuperar comprobante {receipt.id.slice(0, 8)}
          </a>
        </section>
      )}
      {data && (
        <section className={styles.panel + " overflow-hidden"}>
          <div className="p-5">
            <SectionHeading
              icon={History}
              title="Referencias conservadas"
              description="Últimos veinte registros, incluidas correcciones del mismo día."
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className={styles.tableHead}>
                <tr>
                  <th className="px-5 py-3">Día de uso</th>
                  <th className="px-5 py-3">Revisión</th>
                  <th className="px-5 py-3">Bs./USD</th>
                  <th className="px-5 py-3">Referencia BCV</th>
                </tr>
              </thead>
              <tbody>
                {data.rates.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100">
                    <td className="whitespace-nowrap px-5 py-3">
                      {dayText(row.valid_on)}
                    </td>
                    <td className="px-5 py-3">{row.revision}</td>
                    <td className="px-5 py-3 font-mono">
                      {row.ves_per_usd.replace(".", ",")}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      {dayText(row.reference_date)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.rates.length === 0 && (
              <p className="p-5 text-sm text-slate-500">
                Todavía no hay referencias registradas.
              </p>
            )}
          </div>
        </section>
      )}
      <Dialog
        open={!!confirmation}
        onOpenChange={(open) => {
          if (!open && !busy) setConfirmation(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirmar referencia BCV</DialogTitle>
            <DialogDescription>
              Revisa el valor antes de guardarlo. Una corrección crea una nueva
              revisión y conserva las anteriores.
            </DialogDescription>
          </DialogHeader>
          {confirmation && (
            <dl className="space-y-3 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm">
              <div>
                <dt className="font-semibold">Día de uso · Caracas</dt>
                <dd>{dayText(confirmation.valid_on)}</dd>
              </div>
              <div>
                <dt className="font-semibold">Bolívares por 1 USD</dt>
                <dd className="break-all text-xl font-bold text-violet-950">
                  {confirmation.ves_per_usd.replace(".", ",")}
                </dd>
              </div>
              <div>
                <dt className="font-semibold">Referencia BCV</dt>
                <dd>{dayText(confirmation.reference_date)}</dd>
              </div>
              <div>
                <dt className="font-semibold">Verificación manual</dt>
                <dd className="break-words">{confirmation.note}</dd>
              </div>
            </dl>
          )}
          {error && (
            <p role="alert" className="text-sm text-rose-700">
              {error}
            </p>
          )}
          <DialogFooter>
            <button
              className={styles.button}
              disabled={busy}
              onClick={() => setConfirmation(null)}
            >
              Cancelar
            </button>
            <button
              className={styles.primaryButton}
              disabled={busy}
              onClick={() => void saveRate()}
            >
              {busy ? "Guardando…" : "Confirmar tasa"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
