"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowDownLeft,
  ArrowUpRight,
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
import { customerCashbookService } from "@/services/customer-cashbook.service";
import {
  cashbookCSV,
  cashCents,
  cashText,
  type CashFilters,
  type CashReport,
  type CashMethod,
  type CashCurrency,
} from "@/lib/customer-cashbook";
import { downloadCSV } from "@/lib/csv-export";
import { Button } from "@/components/ui/button";
const names = {
  EFECTIVO: "Efectivo",
  TRANSFERENCIA: "Transferencia",
  PAGO_MOVIL: "Pago móvil",
};
const stamp = (value: string) =>
  new Intl.DateTimeFormat("es-VE", {
    timeZone: "America/Caracas",
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
export default function CustomerCashbookPage() {
  const { user, isAuthenticated } = useAuthStore(),
    router = useRouter();
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  const allowed =
    isAuthenticated &&
    !!user &&
    ["SUPERADMIN", "GERENTE", "AUDITOR"].includes(user.role);
  useEffect(() => {
    if (!allowed) router.replace("/login");
  }, [allowed, router]);
  return allowed ? (
    <CashbookView key={JSON.stringify([generation, user.id, user.role])} />
  ) : (
    <p role="status" className="p-6">
      Verificando acceso al libro…
    </p>
  );
}
function CashbookView() {
  const [draft, setDraft] = useState<CashFilters>({}),
    [report, setReport] = useState<CashReport | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [page, setPage] = useState(0);
  const sequence = useRef(0),
    mounted = useRef(true);
  async function load(input: CashFilters) {
    const request = ++sequence.current,
      task = capturePrivateTask();
    setPending(true);
    setError("");
    setReport(null);
    setPage(0);
    try {
      const value = await customerCashbookService.report(input);
      task.assertCurrent();
      if (mounted.current && request === sequence.current) {
        setReport(value);
        setDraft({
          date_from: value.date_from,
          date_to: value.date_to,
          method: value.filters.method ?? undefined,
          currency: value.filters.currency ?? undefined,
          source_key: value.filters.source_key ?? undefined,
        });
      }
    } catch (e) {
      if (mounted.current && request === sequence.current && task.isCurrent())
        setError(
          e instanceof Error ? e.message : "No se pudo cargar el libro.",
        );
    } finally {
      if (mounted.current && request === sequence.current && task.isCurrent())
        setPending(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void load({});
    return () => {
      mounted.current = false;
      sequence.current++;
    };
  }, []);
  function edit(key: keyof CashFilters, value: string) {
    sequence.current++;
    setPending(false);
    setReport(null);
    setError("");
    setPage(0);
    setDraft((old) => ({ ...old, [key]: value || undefined }));
  }
  const rows = report?.rows.slice(page * 50, (page + 1) * 50) ?? [],
    pages = report ? Math.max(1, Math.ceil(report.rows.length / 50)) : 1;
  const max =
    report?.daily.reduce((n, d) => {
      const a = cashCents(d.collection_usd) + cashCents(d.refund_usd);
      return a > n ? a : n;
    }, BigInt(1)) ?? BigInt(1);
  function exportCSV() {
    try {
      capturePrivateTask().assertCurrent();
      if (report && !pending)
        downloadCSV(
          cashbookCSV(report),
          `libro_cobros_${report.date_from}_${report.date_to}`,
        );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo exportar.");
    }
  }
  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-950 via-indigo-950 to-cyan-900 p-6 text-white shadow-lg md:p-8">
          <div
            aria-hidden="true"
            className="absolute -right-12 -top-20 h-64 w-64 rounded-full bg-cyan-400/15"
          />
          <div className="relative space-y-3">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs">
              <ShieldCheck size={15} /> Control financiero · Venezuela
            </span>
            <h1 className="text-2xl font-bold md:text-3xl">
              Libro de cobros y devoluciones
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-cyan-50">
              Cada entrada y cada devolución, con su moneda y tasa original.
              Consulta movimientos verificados manualmente y descarga el detalle
              completo.
            </p>
            <div className="flex flex-wrap gap-2 text-xs text-cyan-100">
              <span className="rounded-full bg-white/10 px-3 py-1">
                Base USD
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1">
                VES con BCV conservado
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1">
                Calendario de Caracas
              </span>
            </div>
          </div>
        </header>
        <section
          aria-label="Filtros del libro"
          className="rounded-2xl border bg-white p-5 shadow-sm"
        >
          <h2 className="mb-4 font-semibold text-slate-900">
            Consulta del período
          </h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void load(draft);
            }}
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5"
          >
            <label className="text-sm font-medium">
              Desde
              <input
                aria-label="Desde"
                type="date"
                value={draft.date_from ?? ""}
                onChange={(e) => edit("date_from", e.target.value)}
                className="mt-1 w-full rounded-lg border p-2"
              />
            </label>
            <label className="text-sm font-medium">
              Hasta
              <input
                aria-label="Hasta"
                type="date"
                value={draft.date_to ?? ""}
                onChange={(e) => edit("date_to", e.target.value)}
                className="mt-1 w-full rounded-lg border p-2"
              />
            </label>
            <label className="text-sm font-medium">
              Medio
              <select
                aria-label="Medio"
                value={draft.method ?? ""}
                onChange={(e) => edit("method", e.target.value)}
                className="mt-1 w-full rounded-lg border p-2"
              >
                <option value="">Todos los medios</option>
                {Object.entries(names).map(([v, n]) => (
                  <option key={v} value={v}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium">
              Moneda recibida
              <select
                aria-label="Moneda recibida"
                value={draft.currency ?? ""}
                onChange={(e) => edit("currency", e.target.value)}
                className="mt-1 w-full rounded-lg border p-2"
              >
                <option value="">USD y VES</option>
                <option value="USD">USD</option>
                <option value="VES">VES</option>
              </select>
            </label>
            <label className="text-sm font-medium">
              Caja o cuenta
              <input
                aria-label="Caja o cuenta"
                maxLength={80}
                value={draft.source_key ?? ""}
                onChange={(e) => edit("source_key", e.target.value)}
                placeholder="Alias exacto"
                className="mt-1 w-full rounded-lg border p-2"
              />
            </label>
            <div className="flex flex-wrap gap-3 sm:col-span-2 lg:col-span-5">
              <Button type="submit" disabled={pending}>
                <RefreshCw
                  size={16}
                  className={pending ? "mr-2 animate-spin" : "mr-2"}
                />
                Aplicar consulta
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!report || pending}
                onClick={exportCSV}
              >
                <Download size={16} className="mr-2" />
                Exportar CSV completo
              </Button>
            </div>
          </form>
          <p className="mt-3 text-xs text-slate-500">
            Hasta 31 días y 5.000 movimientos. Al editar un filtro, aplica la
            consulta para volver a mostrar y exportar cifras confirmadas.
          </p>
        </section>
        {pending && (
          <p
            role="status"
            className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-cyan-900"
          >
            Consultando movimientos verificados…
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-900"
          >
            {error}
          </p>
        )}
        {!report && !pending && !error && (
          <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
            Aplica la consulta para ver los movimientos del rango.
          </p>
        )}
        {report && (
          <section aria-label="Libro confirmado" className="space-y-6">
            <div className="flex flex-wrap justify-between gap-2 text-sm text-slate-600">
              <p>
                Rango confirmado:{" "}
                <strong>
                  {report.date_from} → {report.date_to}
                </strong>{" "}
                · Caracas
              </p>
              <p>Actualizado: {stamp(report.generated_at)}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              {[
                {
                  title: "Cobros verificados",
                  value: report.summary.collection_usd,
                  count: report.summary.collection_count,
                  tone: "border-emerald-200 bg-emerald-50 text-emerald-900",
                  Icon: ArrowDownLeft,
                },
                {
                  title: "Devoluciones verificadas",
                  value: report.summary.refund_usd,
                  count: report.summary.refund_count,
                  tone: "border-rose-200 bg-rose-50 text-rose-900",
                  Icon: ArrowUpRight,
                },
                {
                  title: "Neto del período",
                  value: report.summary.net_usd,
                  count: report.summary.entry_count,
                  tone: "border-indigo-200 bg-indigo-50 text-indigo-900",
                  Icon: Wallet,
                },
              ].map(({ title, value, count, tone, Icon }) => (
                <div key={title} className={`rounded-2xl border p-5 ${tone}`}>
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold">{title}</h2>
                    <Icon size={22} />
                  </div>
                  <p className="mt-3 break-words text-2xl font-bold">
                    {cashText(value)}
                  </p>
                  <p className="mt-1 text-xs">{count} movimientos</p>
                </div>
              ))}
            </div>
            <p className="text-sm text-slate-600">
              El neto resta devoluciones verificadas a cobros verificados del
              período. Puede ser negativo. No representa utilidad ni saldo
              bancario.
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              {report.currencies.map((c) => (
                <article
                  key={c.currency}
                  className="rounded-2xl border border-cyan-100 bg-white p-5 shadow-sm"
                >
                  <h2 className="font-semibold text-slate-900">
                    {c.currency === "USD"
                      ? "Dólares recibidos y devueltos"
                      : "Bolívares recibidos y devueltos"}
                  </h2>
                  <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
                    {[
                      ["Recibido", c.collection_original],
                      ["Devuelto", c.refund_original],
                      ["Neto", c.net_original],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-slate-500">{label}</dt>
                        <dd className="mt-1 break-words font-semibold">
                          {cashText(value, c.currency)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <p className="mt-3 text-xs text-slate-500">
                    Importes originales · sin reconvertir a la tasa de hoy
                  </p>
                </article>
              ))}
            </div>
            <div className="grid gap-5 xl:grid-cols-2">
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="mb-4 font-semibold">Actividad diaria · USD</h2>
                <ul className="max-h-80 space-y-3 overflow-y-auto">
                  {report.daily.map((d) => (
                    <li key={d.date} className="text-xs">
                      <div className="mb-1 flex justify-between gap-2">
                        <span>{d.date}</span>
                        <span>{cashText(d.net_usd)} neto</span>
                      </div>
                      <div
                        className="flex h-2 overflow-hidden rounded-full bg-slate-100"
                        aria-hidden="true"
                      >
                        <div
                          className="bg-emerald-400"
                          style={{
                            width: `${Number((cashCents(d.collection_usd) * BigInt(10000)) / max) / 100}%`,
                          }}
                        />
                        <div
                          className="bg-rose-400"
                          style={{
                            width: `${Number((cashCents(d.refund_usd) * BigInt(10000)) / max) / 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-slate-500">
                        Cobros {cashText(d.collection_usd)} · Devoluciones{" "}
                        {cashText(d.refund_usd)}
                      </span>
                    </li>
                  ))}
                </ul>
              </article>
              <article className="rounded-2xl border bg-white p-5">
                <h2 className="mb-4 font-semibold">
                  Desglose por medio y moneda
                </h2>
                <div className="space-y-3">
                  {report.methods.map((m) => (
                    <div
                      key={`${m.currency}:${m.method}`}
                      className="flex flex-wrap justify-between gap-2 rounded-xl bg-slate-50 p-3 text-sm"
                    >
                      <div>
                        <p className="font-medium">
                          {names[m.method]} · {m.currency}
                        </p>
                        <p className="text-xs text-slate-500">
                          {m.entry_count} movimientos · verificación manual
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-semibold">
                          {cashText(m.net_original, m.currency)}
                        </p>
                        <p className="text-xs text-slate-500">
                          Neto equivalente {cashText(m.net_usd)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            </div>
            <article className="rounded-2xl border bg-white p-5">
              <div className="mb-4 flex flex-wrap justify-between gap-3">
                <h2 className="font-semibold">Detalle trazable</h2>
                <p className="text-sm text-slate-500">
                  {report.rows.length} movimientos · exportación completa
                </p>
              </div>
              {!report.rows.length ? (
                <p className="rounded-xl bg-slate-50 p-5 text-slate-600">
                  No hay movimientos verificados para estos filtros.
                </p>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <caption className="sr-only">
                        Cobros y devoluciones verificados manualmente
                      </caption>
                      <thead className="bg-slate-50 text-xs text-slate-600">
                        <tr>
                          {[
                            "Verificado en Caracas",
                            "Movimiento / orden",
                            "Medio / referencia",
                            "Importe original",
                            "Base USD / BCV",
                          ].map((h) => (
                            <th scope="col" key={h} className="p-3">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.key} className="border-b align-top">
                            <td className="whitespace-nowrap p-3">
                              <p>{stamp(r.verified_at)}</p>
                              <p className="text-xs text-slate-500">
                                Operación {r.operation_date}
                              </p>
                            </td>
                            <td className="p-3">
                              <span
                                className={`rounded-full px-2 py-1 text-xs font-semibold ${r.kind === "COBRO" ? "bg-emerald-100 text-emerald-900" : "bg-rose-100 text-rose-900"}`}
                              >
                                {r.kind === "COBRO" ? "Cobro" : "Devolución"}
                              </span>
                              <p className="mt-2 break-all font-mono text-xs">
                                {r.order_id}
                              </p>
                              <details className="mt-2 text-xs">
                                <summary className="cursor-pointer text-indigo-700">
                                  Trazabilidad
                                </summary>
                                <dl className="mt-2 space-y-1 break-all">
                                  <dt>Verificación</dt>
                                  <dd>{r.verification_id}</dd>
                                  <dt>Cobro original</dt>
                                  <dd>{r.collection_id}</dd>
                                  {r.refund_id && (
                                    <>
                                      <dt>Devolución</dt>
                                      <dd>{r.refund_id}</dd>
                                    </>
                                  )}
                                  <dt>Declarado por</dt>
                                  <dd>{r.declared_by}</dd>
                                  <dt>Verificado por</dt>
                                  <dd>{r.verified_by}</dd>
                                </dl>
                              </details>
                            </td>
                            <td className="p-3">
                              <p>{names[r.method]}</p>
                              <p className="break-all text-xs text-slate-600">
                                {r.source_key}
                              </p>
                              <p className="break-all font-mono text-xs">
                                {r.reference_key}
                              </p>
                            </td>
                            <td className="whitespace-nowrap p-3 font-semibold">
                              {r.kind === "DEVOLUCION" ? "−" : ""}
                              {cashText(r.amount_original, r.original_currency)}
                            </td>
                            <td className="whitespace-nowrap p-3">
                              <p>
                                {r.kind === "DEVOLUCION" ? "−" : ""}
                                {cashText(r.amount_usd)}
                              </p>
                              <p className="text-xs text-slate-500">
                                {r.bcv_rate
                                  ? `BCV ${r.bcv_rate} · ${r.bcv_valid_on}`
                                  : "Moneda original USD"}
                              </p>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <nav
                    aria-label="Páginas de movimientos"
                    className="mt-4 flex items-center justify-between gap-2"
                  >
                    <Button
                      variant="outline"
                      disabled={page === 0}
                      onClick={() => setPage((n) => n - 1)}
                    >
                      Anterior
                    </Button>
                    <span className="text-sm">
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
                </>
              )}
              <p className="mt-4 break-all text-xs text-slate-500">
                Huella del contenido: {report.content_sha256}
              </p>
            </article>
            <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
              La verificación corresponde a un responsable del sistema. La
              confirmación y conciliación automática con bancos sigue pendiente.
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
