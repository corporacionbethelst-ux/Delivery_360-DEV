"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Download,
  RefreshCw,
  ShieldCheck,
  Wallet,
  TrendingUp,
  Clock,
} from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { PayoutSessionBoundary } from "@/components/financial/PayoutSessionBoundary";
import { capturePrivateTask } from "@/lib/private-task";
import { riderExactService } from "@/services/rider-earnings-exact.service";
import {
  riderMoney,
  riderEarningsCSV,
  riderExclusions,
  type RiderExactReport,
  type RiderExactBalance,
} from "@/lib/rider-earnings-exact";
import { cashCents, cashbookError } from "@/lib/customer-cashbook";
import { downloadCSV } from "@/lib/csv-export";
import { Button } from "@/components/ui/button";
const stamp = (value: string) =>
  new Intl.DateTimeFormat("es-VE", {
    timeZone: "America/Caracas",
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
export default function RiderEarningsPage() {
  return (
    <PayoutSessionBoundary>
      <ExactRiderEarnings />
    </PayoutSessionBoundary>
  );
}
function ExactRiderEarnings() {
  const router = useRouter(),
    { user, isAuthenticated } = useAuthStore(),
    allowed = isAuthenticated && user?.role === "REPARTIDOR";
  const [report, setReport] = useState<RiderExactReport | null>(null),
    [balance, setBalance] = useState<RiderExactBalance | null>(null),
    [reportError, setReportError] = useState(""),
    [balanceError, setBalanceError] = useState(""),
    [busy, setBusy] = useState(true),
    [page, setPage] = useState(0),
    [notice, setNotice] = useState("");
  const alive = useRef(false),
    sequence = useRef(0);
  async function load() {
    if (!allowed || !user) return;
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      (!task || task.isCurrent());
    setBusy(true);
    setReport(null);
    setBalance(null);
    setReportError("");
    setBalanceError("");
    setNotice("");
    setPage(0);
    try {
      task = capturePrivateTask();
      const [income, funds] = await Promise.allSettled([
        riderExactService.report(user.id),
        riderExactService.balance(user.id),
      ]);
      task.assertCurrent();
      if (!current()) return;
      if (
        income.status === "fulfilled" &&
        funds.status === "fulfilled" &&
        income.value.rider_id !== funds.value.rider_id
      )
        throw new Error(
          "Las respuestas no corresponden al mismo perfil de repartidor.",
        );
      if (income.status === "fulfilled") setReport(income.value);
      else setReportError(cashbookError(income.reason));
      if (funds.status === "fulfilled") setBalance(funds.value);
      else setBalanceError(cashbookError(funds.reason));
    } catch (e) {
      if (current()) {
        setReportError(cashbookError(e));
        setBalanceError(cashbookError(e));
      }
    } finally {
      if (current()) setBusy(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    if (allowed) void load();
    else if (isAuthenticated) router.push("/login");
    return () => {
      alive.current = false;
    };
  }, [allowed, user?.id]);
  const canWithdraw =
    !!report &&
    !!balance &&
    !busy &&
    cashCents(balance.available) >= cashCents(balance.minimum_withdrawal_usd);
  const rows = report?.rows.slice(page * 50, (page + 1) * 50) ?? [],
    pages = Math.max(1, Math.ceil((report?.row_count ?? 0) / 50));
  const max =
    report?.daily.reduce((n, d) => {
      const value = cashCents(d.credit_usd);
      return value > n ? value : n;
    }, BigInt(1)) ?? BigInt(1);
  function exportCSV() {
    try {
      capturePrivateTask().assertCurrent();
      if (
        report &&
        !busy &&
        downloadCSV(riderEarningsCSV(report), "mis_movimientos_usd")
      )
        setNotice(
          `CSV generado con ${report.row_count} movimientos completos.`,
        );
    } catch (e) {
      setReportError(cashbookError(e));
    }
  }
  if (!allowed)
    return (
      <p role="status" className="p-6">
        Verificando acceso a tus ganancias…
      </p>
    );
  return (
    <div className="min-h-screen bg-slate-50 p-4 pb-20 md:p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-950 via-emerald-950 to-cyan-900 p-6 text-white shadow-lg md:p-8">
          <div
            aria-hidden="true"
            className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-emerald-300/10"
          />
          <div className="relative space-y-3">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs">
              <ShieldCheck size={15} /> Tu libro USD · cifras exactas
            </span>
            <h1 className="text-2xl font-bold md:text-3xl">Mis Ganancias</h1>
            <p className="max-w-2xl text-sm leading-relaxed text-emerald-100">
              Créditos registrados, movimientos y saldo disponible. El valor de
              una orden entregada no se convierte en ganancia si no existe su
              asiento contable.
            </p>
            <div className="flex flex-wrap gap-2 pt-2">
              <Button
                variant="outline"
                className="border-white/30 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                disabled={busy}
                onClick={() => {
                  void load();
                }}
              >
                <RefreshCw
                  size={15}
                  className={`mr-2 ${busy ? "animate-spin" : ""}`}
                />
                Actualizar
              </Button>
              <Button
                variant="outline"
                className="border-white/30 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                disabled={!report || busy}
                onClick={exportCSV}
              >
                <Download size={15} className="mr-2" />
                Exportar movimientos
              </Button>
              <Button
                variant="outline"
                className="border-white/30 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                onClick={() => router.push("/rider/earnings/payouts")}
              >
                Historial de retiros
              </Button>
            </div>
          </div>
        </header>
        {busy && (
          <p
            role="status"
            className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-cyan-950"
          >
            Consultando tus movimientos y el saldo USD…
          </p>
        )}
        {reportError && (
          <div
            role="alert"
            className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950"
          >
            <h2 className="font-semibold">Ganancias por confirmar</h2>
            <p className="mt-1">{reportError}</p>
          </div>
        )}
        {balanceError && (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-950"
          >
            <h2 className="font-semibold">Saldo USD por confirmar</h2>
            <p className="mt-1">{balanceError}</p>
            <p className="mt-2 text-sm">
              No se habilitan retiros hasta confirmar tu saldo con el servidor.
            </p>
          </div>
        )}
        {notice && (
          <p
            role="status"
            className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950"
          >
            {notice}
          </p>
        )}
        {report && (
          <section
            aria-label="Ganancias exactas confirmadas"
            className="space-y-5"
          >
            <p className="text-xs text-slate-500">
              Corte del historial: {stamp(report.generated_at)} · Caracas ·{" "}
              {report.row_count} movimientos completos
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              {[
                {
                  label: "Total Ganado",
                  value: report.lifetime.credit_usd,
                  note: "Créditos procesados registrados en tu historial USD",
                  tone: "border-emerald-200 bg-emerald-50 text-emerald-950",
                  Icon: TrendingUp,
                },
                {
                  label: "Ganancias de hoy",
                  value: report.day.credit_usd,
                  note: `${report.today} · ${report.day.completed_delivery_count} abonos de entrega`,
                  tone: "border-cyan-200 bg-cyan-50 text-cyan-950",
                  Icon: Clock,
                },
                {
                  label: "Últimos 7 días",
                  value: report.week.credit_usd,
                  note: `${report.week_from} → ${report.today} · calendario Caracas`,
                  tone: "border-violet-200 bg-violet-50 text-violet-950",
                  Icon: Wallet,
                },
              ].map(({ label, value, note, tone, Icon }) => (
                <article
                  key={label}
                  className={`rounded-2xl border p-5 ${tone}`}
                >
                  <div className="flex justify-between gap-2">
                    <h2 className="text-sm font-semibold">{label}</h2>
                    <Icon size={21} />
                  </div>
                  <p className="mt-3 break-words text-2xl font-bold">
                    {riderMoney(value)}
                  </p>
                  <p className="mt-3 text-xs">{note}</p>
                </article>
              ))}
            </div>
          </section>
        )}
        <section
          aria-label="Saldo para retiro"
          className="rounded-2xl border border-blue-200 bg-gradient-to-br from-white to-blue-50 p-5 shadow-sm"
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="font-semibold text-blue-950">
                Disponible para Retiro
              </h2>
              <p className="mt-2 break-words text-3xl font-bold text-blue-950">
                {balance ? riderMoney(balance.available) : "Por confirmar"}
              </p>
              {balance && (
                <p className="mt-2 text-xs text-slate-500">
                  Corte del saldo: {stamp(balance.generated_at)} · mínimo{" "}
                  {riderMoney(balance.minimum_withdrawal_usd)}
                </p>
              )}
            </div>
            <Button
              disabled={!canWithdraw}
              className="bg-emerald-700 hover:bg-emerald-800"
              onClick={() => router.push("/rider/earnings/withdraw")}
            >
              Solicitar Retiro
            </Button>
          </div>
          {balance && (
            <>
              <dl className="mt-5 grid gap-3 sm:grid-cols-3">
                {[
                  ["Saldo del libro", balance.ledger_balance],
                  ["Reservado sin débito", balance.reserved],
                  ["Solicitudes pendientes", balance.pending],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-xl border bg-white p-3 text-sm"
                  >
                    <dt className="text-xs text-slate-500">{label}</dt>
                    <dd className="mt-1 break-words font-semibold">
                      {riderMoney(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-xs text-slate-600">
                Un retiro ya descontado del libro no vuelve a reservarse. Las
                solicitudes históricas completadas sin débito conciliado
                conservan su reserva.
              </p>
            </>
          )}
          <p className="mt-4 text-sm text-blue-950">
            El saldo y el historial tienen sus propios cortes de consulta. El
            formulario de retiro vuelve a verificar disponibilidad antes de
            guardar. Un retiro aprobado contablemente no confirma una
            transferencia bancaria.
          </p>
        </section>
        {(balance || report) && (
          <aside
            role="note"
            className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
          >
            <strong>Tu saldo está denominado en USD.</strong> Los registros sin
            moneda confirmada permanecen separados.
            {!!balance?.unverified_financial_count && (
              <p className="mt-2">
                {balance.unverified_financial_count} movimientos anteriores
                requieren revisión de moneda.
              </p>
            )}
            {!!balance?.unverified_payout_count && (
              <p className="mt-1">
                {balance.unverified_payout_count} retiros anteriores conservan
                su moneda sin verificar.
              </p>
            )}
            {report && (
              <p className="mt-2">
                {report.excluded_count} movimientos excluidos de los importes.
                El libro de wallets en centavos y las cotizaciones VES
                permanecen separados.
              </p>
            )}
          </aside>
        )}
        {report && (
          <>
            <div className="grid gap-5 lg:grid-cols-2">
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="mb-4 font-semibold">
                  Créditos registrados por día
                </h2>
                <ul className="space-y-3">
                  {report.daily.map((d) => (
                    <li key={d.date} className="text-xs">
                      <div className="mb-1 flex justify-between gap-2">
                        <span>{d.date}</span>
                        <span>{riderMoney(d.credit_usd)}</span>
                      </div>
                      <div
                        className="h-2 rounded-full bg-slate-100"
                        aria-hidden="true"
                      >
                        <div
                          className="h-2 rounded-full bg-emerald-500"
                          style={{
                            width: `${Number((cashCents(d.credit_usd) * BigInt(10000)) / max) / 100}%`,
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </article>
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="font-semibold">
                  Movimientos históricos incluidos
                </h2>
                <dl className="mt-4 space-y-3 text-sm">
                  {[
                    ["Créditos", report.lifetime.credit_usd],
                    ["Débitos, incluidos retiros", report.lifetime.debit_usd],
                    ["Ajustes con signo", report.lifetime.adjustment_usd],
                    ["Cambio neto del libro", report.lifetime.net_change_usd],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex flex-wrap justify-between gap-2 rounded-xl bg-slate-50 p-3"
                    >
                      <dt>{label}</dt>
                      <dd className="font-semibold">{riderMoney(value)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-4 text-xs text-slate-500">
                  {report.lifetime.completed_delivery_count} entregas con abono
                  registrado. El cambio neto no equivale al saldo disponible
                  después de reservas.
                </p>
              </article>
            </div>
            <article className="rounded-2xl border bg-white p-5">
              <div className="mb-4 flex flex-wrap justify-between gap-2">
                <h2 className="font-semibold">
                  Últimos movimientos financieros
                </h2>
                <p className="text-xs text-slate-500">
                  {report.row_count} registros completos · CSV del mismo corte
                </p>
              </div>
              {!rows.length ? (
                <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
                  Aún no hay movimientos financieros para mostrar.
                </p>
              ) : (
                <div className="space-y-3">
                  {rows.map((r) => (
                    <article
                      key={r.id}
                      className={`flex flex-wrap justify-between gap-3 rounded-xl border p-4 ${r.included ? "border-slate-200 bg-white" : "border-amber-200 bg-amber-50"}`}
                    >
                      <div className="min-w-0 flex-1">
                        <h3 className="break-words text-sm font-semibold">
                          {r.description ?? "Sin descripción"}
                        </h3>
                        <p className="mt-1 break-words text-xs text-slate-500">
                          {r.transaction_type ?? "Tipo sin identificar"} ·{" "}
                          {r.status ?? "Sin estado"} ·{" "}
                          {r.occurred_at ? stamp(r.occurred_at) : "Sin fecha"}
                        </p>
                        <p className="mt-1 break-all font-mono text-xs text-slate-500">
                          {r.id}
                        </p>
                      </div>
                      <div className="text-right text-sm">
                        <p
                          className={`font-semibold ${r.included && cashCents(r.delta_usd!, true) < BigInt(0) ? "text-rose-700" : "text-emerald-800"}`}
                        >
                          {r.included ? riderMoney(r.delta_usd!) : "Excluido"}
                        </p>
                        <p className="mt-1 text-xs text-amber-900">
                          {r.exclusion_reason
                            ? riderExclusions[
                                r.exclusion_reason as keyof typeof riderExclusions
                              ]
                            : "Movimiento USD registrado"}
                        </p>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <nav
                aria-label="Páginas de movimientos"
                className="mt-4 flex items-center justify-between gap-2"
              >
                <Button
                  variant="outline"
                  disabled={!page}
                  onClick={() => setPage((n) => n - 1)}
                >
                  Anterior
                </Button>
                <span className="text-xs">
                  Página {page + 1} de {pages}
                </span>
                <Button
                  variant="outline"
                  disabled={page + 1 >= pages}
                  onClick={() => setPage((n) => n + 1)}
                >
                  Siguiente
                </Button>
              </nav>
              <p className="mt-4 break-all text-xs text-slate-500">
                Huella del historial: {report.content_sha256}
              </p>
            </article>
          </>
        )}
      </div>
    </div>
  );
}
