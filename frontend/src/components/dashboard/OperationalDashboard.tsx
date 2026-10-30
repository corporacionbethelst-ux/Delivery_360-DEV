"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Clock,
  Loader2,
  Package,
  RefreshCw,
  Users,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useOperationalDashboard } from "@/hooks/useOperationalDashboard";
import type { DashboardMode } from "@/services/operational-dashboard.service";

const integer = (value: number) => value.toLocaleString("es-VE");
const measurement = (value: number | null, suffix: string) =>
  value === null
    ? "Sin datos"
    : `${value.toLocaleString("es-VE", { maximumFractionDigits: 1 })}${suffix}`;

export default function OperationalDashboard({
  mode,
}: {
  mode: DashboardMode;
}) {
  const [days, setDays] = useState(7);
  const { allowed, data, loading, error, refresh } = useOperationalDashboard(
    mode,
    days,
  );
  if (!allowed)
    return (
      <div role="status" className="p-8">
        Este panel requiere acceso operativo autorizado.
      </div>
    );
  const summary = data?.summary;
  const cards = summary
    ? [
        {
          label: "Pedidos creados",
          value: integer(summary.orders_created),
          help: "En el período seleccionado",
          icon: Package,
        },
        {
          label: "Entregas completadas",
          value: integer(summary.completed_deliveries),
          help: "Por fecha de finalización",
          icon: CheckCircle,
        },
        {
          label: "SLA conocido",
          value: measurement(summary.sla_percent, "%"),
          help: `${integer(summary.sla_known_count)} resultados conocidos · ${integer(summary.sla_unknown_count)} sin dato`,
          icon: Activity,
        },
        {
          label: "Repartidores conectados",
          value: integer(summary.riders_online),
          help: "Estado actual reportado",
          icon: Users,
        },
        {
          label: "Pedidos pendientes",
          value: integer(summary.pending_orders),
          help: "Total actual, sin límite de lista",
          icon: Clock,
        },
        {
          label: "Alertas abiertas",
          value: integer(summary.open_alerts),
          help: "Abiertas o reconocidas",
          icon: AlertCircle,
        },
        {
          label: "Entregas en curso",
          value: integer(summary.active_deliveries),
          help: `${integer(summary.in_progress_orders)} pedidos en proceso`,
          icon: Package,
        },
        {
          label: "Repartidores disponibles",
          value: integer(summary.available_riders),
          help: "Conectados y con estado activo",
          icon: Users,
        },
        {
          label: "Turnos en curso",
          value: integer(summary.active_shifts),
          help: "Entrada registrada y sin salida",
          icon: Clock,
        },
      ]
    : [];
  const max = data
    ? Math.max(
        1,
        ...data.series.map((item) =>
          Math.max(item.orders_created, item.completed_deliveries),
        ),
      )
    : 1;

  return (
    <main className="space-y-6 p-6 bg-slate-50 min-h-screen">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            {mode === "manager" ? "Panel General" : "Panel de Operador"}
          </h1>
          <p className="text-sm text-slate-600">
            Actividad operativa y resultados registrados
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm">
            Período{" "}
            <select
              aria-label="Período"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              className="ml-2 rounded border p-2 bg-white"
            >
              <option value={1}>Hoy</option>
              <option value={7}>Últimos 7 días</option>
              <option value={30}>Últimos 30 días</option>
            </select>
          </label>
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Actualizar
          </Button>
        </div>
      </header>
      {loading && (
        <div role="status" className="flex items-center gap-3 p-8">
          <Loader2 className="h-5 w-5 animate-spin" />
          Consultando métricas...
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-5 text-red-800"
        >
          {error}
        </div>
      )}
      {data && summary && (
        <>
          <p className="text-sm text-slate-500">
            Última consulta:{" "}
            {new Date(data.generated_at).toLocaleString("es-VE", {
              timeZone: data.timezone,
            })}{" "}
            · Calendario: {data.timezone}
          </p>
          <section
            aria-label="Indicadores operativos"
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          >
            {cards.map(({ label, value, help, icon: Icon }) => (
              <Card key={label}>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                  <CardTitle className="text-sm font-medium">{label}</CardTitle>
                  <Icon className="h-4 w-4 text-blue-600" />
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold" data-testid={label}>
                    {value}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{help}</p>
                </CardContent>
              </Card>
            ))}
          </section>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Actividad diaria</CardTitle>
              <p className="text-sm text-slate-500">
                Pedidos por fecha de creación y entregas por fecha de
                finalización. Son cohortes distintas.
              </p>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table aria-label="Actividad diaria" className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="py-2">Fecha</th>
                    <th>Pedidos creados</th>
                    <th>Entregas completadas</th>
                    <th aria-label="Comparación visual" />
                  </tr>
                </thead>
                <tbody>
                  {data.series.map((item) => (
                    <tr key={item.date} className="border-b last:border-0">
                      <td className="py-3">{item.date}</td>
                      <td>{integer(item.orders_created)}</td>
                      <td>{integer(item.completed_deliveries)}</td>
                      <td className="min-w-24 w-1/3 py-2" aria-hidden="true">
                        <div
                          className="mb-1 h-2 rounded bg-blue-500"
                          style={{
                            width: `${(item.orders_created / max) * 100}%`,
                          }}
                        />
                        <div
                          className="h-2 rounded bg-emerald-500"
                          style={{
                            width: `${(item.completed_deliveries / max) * 100}%`,
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
          <p className="text-sm text-slate-600">
            Duración media registrada:{" "}
            <strong>{measurement(summary.avg_delivery_minutes, " min")}</strong>{" "}
            · {integer(summary.valid_duration_count)} entregas con duración
            válida.
          </p>
          {mode === "operator" && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Pendientes y asignados
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {data.pending_orders.length === 0 ? (
                    <p className="text-sm text-slate-500">
                      No hay pedidos en esta cola.
                    </p>
                  ) : (
                    <ul className="divide-y">
                      {data.pending_orders.map((order) => (
                        <li key={order.id} className="py-3">
                          <p className="font-medium">
                            {order.number || "Sin referencia externa"} ·{" "}
                            {order.status}
                          </p>
                          <p className="text-sm text-slate-600">
                            {order.address}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                  {data.queue_truncated && (
                    <p className="text-sm text-slate-500 mt-3">
                      Se muestran los primeros 20. Consulta la lista de pedidos
                      para ver más.
                    </p>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Ubicaciones recientes
                  </CardTitle>
                  <p className="text-sm text-slate-500">
                    Reportes válidos de los últimos cinco minutos
                  </p>
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold">
                    {data.riders_online.length}
                    {data.positions_truncated ? "+" : ""}
                  </p>
                  <p className="text-sm text-slate-500">
                    Ubicaciones disponibles en esta consulta
                  </p>
                </CardContent>
              </Card>
            </div>
          )}
          <nav
            aria-label="Accesos operativos"
            className="flex flex-wrap gap-4 text-sm text-blue-700"
          >
            <Link
              href={
                mode === "manager"
                  ? "/manager/operations/orders"
                  : "/operator/orders"
              }
            >
              Gestionar pedidos
            </Link>
            {mode === "manager" && (
              <>
                <Link href="/manager/operations/live-map">
                  Mapa de operaciones
                </Link>
                <Link href="/manager/financial/resumen">
                  Consultar Finanzas
                </Link>
                <Link href="/manager/fleet/riders">Repartidores</Link>
                <Link href="/manager/financial/reports">Reportes</Link>
              </>
            )}
            {mode === "operator" && (
              <>
                <Link href="/operator/deliveries">Gestionar entregas</Link>
                <Link href="/operator/live-map">Mapa de operaciones</Link>
                <Link href="/operator/alerts">Consultar alertas</Link>
              </>
            )}
          </nav>
        </>
      )}
    </main>
  );
}
