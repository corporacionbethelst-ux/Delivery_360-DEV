"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  BarChart3,
  BookOpen,
  Download,
  RefreshCw,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import {
  getCredentialGeneration,
  onCredentialsChanged,
} from "@/lib/auth-session";
import { capturePrivateTask } from "@/lib/private-task";
import { cashbookError, cashCents, cashDay } from "@/lib/customer-cashbook";
import { exactFinancialService } from "@/services/financial-exact.service";
import {
  exactReportCSV,
  financialMoney,
  exclusionLabels,
  type ExactRange,
  type ExactReport,
  type SourceKind,
} from "@/lib/financial-exact";
import { downloadCSV } from "@/lib/csv-export";
import { Button } from "@/components/ui/button";
const kindLabels = {
  ORDEN: "Órdenes",
  MOVIMIENTO: "Movimientos",
  RETIRO: "Retiros",
};
const stamp = (s: string) =>
  new Intl.DateTimeFormat("es-VE", {
    timeZone: "America/Caracas",
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(s));
export function ExactFinancialDashboard({
  mode,
}: {
  mode: "summary" | "reports";
}) {
  const { user, isAuthenticated } = useAuthStore(),
    router = useRouter();
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  const allowed =
    isAuthenticated && !!user && ["SUPERADMIN", "GERENTE"].includes(user.role);
  useEffect(() => {
    if (!allowed) router.replace("/login");
  }, [allowed, router]);
  return allowed ? (
    <View key={JSON.stringify([generation, user.id, user.role])} mode={mode} />
  ) : (
    <p role="status" className="p-6">
      Verificando acceso financiero…
    </p>
  );
}
function View({ mode }: { mode: "summary" | "reports" }) {
  const [draft, setDraft] = useState<ExactRange>({}),
    [report, setReport] = useState<ExactReport | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [kind, setKind] = useState<SourceKind | "TODOS">("TODOS"),
    [page, setPage] = useState(0);
  const alive = useRef(false),
    sequence = useRef(0);
  async function load(input: ExactRange) {
    const ticket = ++sequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () =>
      alive.current &&
      ticket === sequence.current &&
      (!task || task.isCurrent());
    setBusy(true);
    setError("");
    setNotice("");
    setReport(null);
    setPage(0);
    try {
      task = capturePrivateTask();
      const data = await exactFinancialService.report(input);
      task.assertCurrent();
      if (current()) {
        setReport(data);
        setDraft({ date_from: data.date_from, date_to: data.date_to });
      }
    } catch (e) {
      if (current()) setError(cashbookError(e));
    } finally {
      if (current()) setBusy(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void load({});
    return () => {
      alive.current = false;
    };
  }, []);
  function edit(key: keyof ExactRange, value: string) {
    sequence.current++;
    setBusy(false);
    setReport(null);
    setError("");
    setNotice("");
    setPage(0);
    setDraft((v) => ({ ...v, [key]: value || undefined }));
  }
  function period(days: number) {
    const end = cashDay(new Date().toISOString()),
      start = new Date(Date.parse(end) - (days - 1) * 86400000)
        .toISOString()
        .slice(0, 10);
    void load({ date_from: start, date_to: end });
  }
  function exportCsv() {
    try {
      capturePrivateTask().assertCurrent();
      if (
        report &&
        !busy &&
        downloadCSV(
          exactReportCSV(report),
          `reporte_exacto_${report.date_from}_${report.date_to}`,
        )
      )
        setNotice(
          `CSV generado con ${report.row_count} registros y ${report.excluded_count} exclusiones identificadas.`,
        );
    } catch (e) {
      setError(cashbookError(e));
    }
  }
  const filtered =
      report?.rows.filter((r) => kind === "TODOS" || r.kind === kind) ?? [],
    pages = Math.max(1, Math.ceil(filtered.length / 50)),
    rows = filtered.slice(page * 50, (page + 1) * 50);
  const maximum =
    report?.daily.reduce((n, d) => {
      const raw = cashCents(d.ledger.net_change_usd, true),
        v = raw < BigInt(0) ? -raw : raw;
      return v > n ? v : n;
    }, BigInt(1)) ?? BigInt(1);
  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-950 via-violet-950 to-indigo-800 p-6 text-white shadow-lg md:p-8">
          <div
            aria-hidden="true"
            className="absolute -right-12 -top-20 h-64 w-64 rounded-full bg-fuchsia-300/10"
          />
          <div className="relative space-y-3">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs">
              <ShieldCheck size={15} /> Finanzas · cifras exactas en USD
            </span>
            <h1 className="text-2xl font-bold md:text-3xl">
              {mode === "summary"
                ? "Resumen financiero exacto"
                : "Reportes y exportación exactos"}
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-indigo-100">
              Precios de órdenes, movimientos de repartidores y solicitudes de
              retiro en una misma consulta, con cada fuente identificada y sus
              centavos conservados.
            </p>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-white/10 px-3 py-1">
                Calendario de Caracas
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1">
                Exclusiones visibles
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1">
                Exportación completa
              </span>
            </div>
          </div>
        </header>
        <section
          aria-label="Filtros financieros"
          className="rounded-2xl border bg-white p-5 shadow-sm"
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">Rango de consulta</h2>
            <div
              role="group"
              aria-label="Períodos rápidos"
              className="flex flex-wrap gap-2"
            >
              {[
                [1, "Hoy"],
                [7, "7 días"],
                [30, "30 días"],
              ].map(([days, label]) => (
                <Button
                  key={days}
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => period(Number(days))}
                >
                  {label}
                </Button>
              ))}
            </div>
          </div>
          <form
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
            onSubmit={(e) => {
              e.preventDefault();
              void load(draft);
            }}
          >
            <label className="text-sm font-medium">
              Desde
              <input
                type="date"
                aria-label="Desde"
                value={draft.date_from ?? ""}
                onChange={(e) => edit("date_from", e.target.value)}
                className="mt-1 w-full min-w-0 rounded-lg border p-2"
              />
            </label>
            <label className="text-sm font-medium">
              Hasta
              <input
                type="date"
                aria-label="Hasta"
                value={draft.date_to ?? ""}
                onChange={(e) => edit("date_to", e.target.value)}
                className="mt-1 w-full min-w-0 rounded-lg border p-2"
              />
            </label>
            <div className="flex items-end">
              <Button type="submit" disabled={busy} className="w-full">
                <RefreshCw
                  size={16}
                  className={`mr-2 ${busy ? "animate-spin" : ""}`}
                />
                Aplicar consulta
              </Button>
            </div>
            <div className="flex items-end">
              <Button
                type="button"
                variant="outline"
                disabled={!report || busy}
                onClick={exportCsv}
                className="w-full"
              >
                <Download size={16} className="mr-2" />
                Exportar CSV completo
              </Button>
            </div>
          </form>
          <p className="mt-3 text-xs text-slate-500">
            Máximo 31 días y 5.000 registros entre las tres fuentes, incluidos
            los excluidos. Al editar las fechas, aplica la consulta para obtener
            cifras confirmadas.
          </p>
        </section>
        {busy && (
          <p
            role="status"
            className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-indigo-900"
          >
            Consultando las tres fuentes del reporte exacto…
          </p>
        )}
        {error && (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-900"
          >
            <p>{error}</p>
            <Button
              className="mt-3"
              variant="outline"
              disabled={busy}
              onClick={() => {
                void load(draft);
              }}
            >
              Reintentar consulta
            </Button>
          </div>
        )}
        {notice && (
          <p
            role="status"
            className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900"
          >
            {notice}
          </p>
        )}
        {!report && !busy && !error && (
          <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
            Aplica el rango para consultar y exportar sus cifras.
          </p>
        )}
        {report && (
          <section aria-label="Reporte exacto confirmado" className="space-y-6">
            <div className="flex flex-wrap justify-between gap-3 text-sm text-slate-600">
              <p>
                Rango confirmado:{" "}
                <strong>
                  {report.date_from} → {report.date_to}
                </strong>{" "}
                · Caracas
              </p>
              <p>Corte: {stamp(report.generated_at)}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              {[
                {
                  title: "Valor de órdenes",
                  value: report.orders.total_usd,
                  count: report.orders.count,
                  tone: "border-indigo-200 bg-indigo-50 text-indigo-950",
                  Icon: BarChart3,
                  note: "Precio exacto; no acredita un cobro",
                },
                {
                  title: "Cambio contable de riders",
                  value: report.ledger.net_change_usd,
                  count: report.ledger.count,
                  tone: "border-cyan-200 bg-cyan-50 text-cyan-950",
                  Icon: BookOpen,
                  note: "Movimientos procesados; no es saldo disponible",
                },
                {
                  title: "Solicitudes de retiro",
                  value: report.payouts.amount_usd,
                  count: report.payouts.count,
                  tone: "border-violet-200 bg-violet-50 text-violet-950",
                  Icon: Wallet,
                  note: "Todos los estados; no confirma pago bancario",
                },
              ].map(({ title, value, count, tone, Icon, note }) => (
                <article
                  key={title}
                  className={`rounded-2xl border p-5 ${tone}`}
                >
                  <div className="flex justify-between gap-3">
                    <h2 className="text-sm font-semibold">{title}</h2>
                    <Icon size={21} />
                  </div>
                  <p className="mt-3 break-words text-2xl font-bold">
                    {financialMoney(value)}
                  </p>
                  <p className="mt-1 text-xs">{count} registros incluidos</p>
                  <p className="mt-3 text-xs">{note}</p>
                </article>
              ))}
            </div>
            <aside
              aria-label="Criterio financiero"
              className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950"
            >
              <p>
                Las tres fuentes se presentan por separado. Los precios no
                equivalen a ingresos cobrados y los retiros no se restan otra
                vez del libro contable.
              </p>
              <p className="mt-2">
                El rango selecciona registros por fecha de creación; sus precios
                y estados son los observados al consultar. No reconstruye un
                cierre histórico ni determina utilidad.
              </p>
              <Link
                href="/manager/financial/customer-cashbook"
                className="mt-3 inline-block font-semibold text-indigo-800 underline"
              >
                Consultar cobros y devoluciones verificados USD/VES
              </Link>
            </aside>
            <div className="grid gap-5 lg:grid-cols-2">
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="font-semibold">Precios exactos de órdenes</h2>
                <dl className="my-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-slate-500">Artículos</dt>
                    <dd className="break-words font-semibold">
                      {financialMoney(report.orders.subtotal_usd)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Tarifas de entrega</dt>
                    <dd className="break-words font-semibold">
                      {financialMoney(report.orders.delivery_fee_usd)}
                    </dd>
                  </div>
                </dl>
                <p className="mb-3 text-xs text-slate-500">
                  Órdenes creadas en el rango · precio y estado actuales
                </p>
                <div className="space-y-2">
                  {report.orders.by_status.map((s) => (
                    <div
                      key={s.status}
                      className="flex flex-wrap justify-between gap-2 rounded-lg bg-slate-50 p-2 text-xs"
                    >
                      <span>
                        {s.status.replaceAll("_", " ")} · {s.count}
                      </span>
                      <strong>{financialMoney(s.total_usd)}</strong>
                    </div>
                  ))}
                </div>
              </article>
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="font-semibold">
                  Libro contable de repartidores
                </h2>
                <div className="my-4 grid gap-3 sm:grid-cols-3">
                  {[
                    ["Créditos", report.ledger.credit_usd],
                    ["Débitos", report.ledger.debit_usd],
                    ["Ajustes con signo", report.ledger.adjustment_usd],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="rounded-xl bg-cyan-50 p-3 text-sm"
                    >
                      <p className="text-xs text-slate-500">{label}</p>
                      <p className="mt-1 break-words font-semibold">
                        {financialMoney(value)}
                      </p>
                    </div>
                  ))}
                </div>
                <p className="mb-3 text-xs text-slate-500">
                  Solo USD procesado/pagado, con dirección contable canónica.
                  Débitos incluye retiros; el libro de wallets en centavos
                  permanece separado.
                </p>
                <div className="max-h-80 space-y-2 overflow-auto">
                  {report.ledger.by_type.map((t) => (
                    <div
                      key={t.transaction_type}
                      className="flex flex-wrap justify-between gap-2 rounded-lg bg-slate-50 p-2 text-xs"
                    >
                      <span>
                        {t.transaction_type.replaceAll("_", " ")} · {t.count}
                      </span>
                      <strong>{financialMoney(t.delta_usd)}</strong>
                    </div>
                  ))}
                </div>
              </article>
            </div>
            <article className="rounded-2xl border bg-white p-5">
              <h2 className="font-semibold">
                Solicitudes de retiro por estado
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Creadas en el período, con su estado actual. Una aprobación o un
                estado EN PROCESO no acredita una transferencia bancaria.
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {report.payouts.by_status.map((s) => (
                  <div
                    key={s.status}
                    className="rounded-xl border border-violet-100 bg-violet-50 p-3 text-sm"
                  >
                    <p className="text-xs text-violet-800">
                      {s.status.replaceAll("_", " ")} · {s.count}
                    </p>
                    <p className="mt-2 break-words font-bold text-violet-950">
                      {financialMoney(s.amount_usd)}
                    </p>
                  </div>
                ))}
              </div>
            </article>
            <div className="grid gap-5 lg:grid-cols-2">
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="mb-4 font-semibold">Cambio contable por día</h2>
                <ul className="max-h-80 space-y-3 overflow-auto">
                  {report.daily.map((d) => {
                    const n = cashCents(d.ledger.net_change_usd, true),
                      negative = n < BigInt(0),
                      width =
                        Number(((negative ? -n : n) * BigInt(5000)) / maximum) /
                        100;
                    return (
                      <li key={d.date} className="text-xs">
                        <div className="mb-1 flex justify-between gap-2">
                          <span>{d.date}</span>
                          <span>{financialMoney(d.ledger.net_change_usd)}</span>
                        </div>
                        <div
                          className="relative h-3 rounded-full bg-slate-100"
                          aria-hidden="true"
                        >
                          <span className="absolute left-1/2 h-3 border-l border-slate-300" />
                          <span
                            data-direction={negative ? "negative" : "positive"}
                            className={`absolute h-3 rounded ${negative ? "bg-rose-400" : "bg-cyan-500"}`}
                            style={{
                              left: `${negative ? 50 - width : 50}%`,
                              width: `${width}%`,
                            }}
                          />
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </article>
              <article
                aria-label="Exclusiones del reporte"
                className="rounded-2xl border border-amber-200 bg-amber-50 p-5"
              >
                <h2 className="font-semibold text-amber-950">
                  {report.excluded_count} registros excluidos de los importes
                </h2>
                <p className="mt-2 text-sm text-amber-900">
                  El historial sin moneda o precio exacto se conserva. No se
                  convierte, se etiqueta como USD ni se mezcla con los totales.
                  Los registros sin fecha se muestran para revisión en cualquier
                  rango.
                </p>
                <dl className="mt-4 space-y-2 text-sm">
                  {report.exclusions.map((x) => (
                    <div key={x.reason} className="flex justify-between gap-2">
                      <dt>{exclusionLabels[x.reason]}</dt>
                      <dd className="font-bold">{x.count}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            </div>
            <article className="rounded-2xl border bg-white p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Detalle de las fuentes</h2>
                  <p className="text-xs text-slate-500">
                    {report.row_count} registros completos, incluidos los
                    excluidos
                  </p>
                </div>
                <label className="text-sm">
                  Mostrar
                  <select
                    aria-label="Mostrar fuente"
                    value={kind}
                    onChange={(e) => {
                      setKind(e.target.value as SourceKind | "TODOS");
                      setPage(0);
                    }}
                    className="ml-2 rounded-lg border p-2"
                  >
                    <option value="TODOS">Todas las fuentes</option>
                    {Object.entries(kindLabels).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {!rows.length ? (
                <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
                  No hay registros para esta vista del rango confirmado.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">
                      Registros exactos y exclusiones identificadas
                    </caption>
                    <thead className="bg-slate-50 text-xs text-slate-600">
                      <tr>
                        {[
                          "Fecha de creación",
                          "Fuente / identificador",
                          "Estado / tipo",
                          "Valor exacto USD",
                          "Tratamiento",
                        ].map((h) => (
                          <th key={h} scope="col" className="p-3">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.key} className="border-b align-top">
                          <td className="whitespace-nowrap p-3">
                            {r.occurred_at ? stamp(r.occurred_at) : "Sin fecha"}
                          </td>
                          <td className="p-3">
                            <p className="font-medium">{kindLabels[r.kind]}</p>
                            <p className="mt-1 break-all font-mono text-xs">
                              {r.id}
                            </p>
                            {r.pricing_revision && (
                              <p className="text-xs text-slate-500">
                                Precio revisión {r.pricing_revision}
                              </p>
                            )}
                          </td>
                          <td className="p-3 text-xs">
                            <p>
                              {r.status?.replaceAll("_", " ") ?? "Sin estado"}
                            </p>
                            <p className="mt-1">
                              {r.transaction_type?.replaceAll("_", " ")}
                            </p>
                          </td>
                          <td className="whitespace-nowrap p-3 font-semibold">
                            {r.included
                              ? financialMoney(
                                  (r.kind === "ORDEN"
                                    ? r.total_usd
                                    : r.kind === "MOVIMIENTO"
                                      ? r.delta_usd
                                      : r.amount_usd)!,
                                )
                              : "Excluido"}
                          </td>
                          <td className="p-3">
                            <span
                              className={`rounded-full px-2 py-1 text-xs ${r.included ? "bg-emerald-50 text-emerald-900" : "bg-amber-100 text-amber-950"}`}
                            >
                              {r.exclusion_reason
                                ? exclusionLabels[r.exclusion_reason]
                                : "Incluido en su fuente"}
                            </span>
                            <p className="mt-2 text-xs text-slate-500">
                              {r.currency ?? "Moneda no verificada"}
                            </p>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <nav
                aria-label="Páginas del reporte"
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
                Huella del contenido: {report.content_sha256}. El CSV contiene
                las tres fuentes completas, independientemente de la vista
                elegida.
              </p>
            </article>
          </section>
        )}
      </div>
    </div>
  );
}
