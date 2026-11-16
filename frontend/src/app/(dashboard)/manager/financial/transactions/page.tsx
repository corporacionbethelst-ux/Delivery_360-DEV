"use client";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  ArrowRightLeft,
  Download,
  ListFilter,
  ListOrdered,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  WalletCards,
} from "lucide-react";
import {
  useTransactionHistory,
  TRANSACTION_PAGE_SIZE,
} from "@/hooks/useTransactionHistory";
import {
  TRANSACTION_STATUSES,
  TRANSACTION_TYPES,
  transactionDateLabel,
} from "@/lib/transaction-contract";
import { exactTransactionMoney } from "@/lib/transaction-exact";
import { TransactionAccess } from "@/components/financial/TransactionAccess";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  OperationsHeader,
  OperationMetric,
  OperationNotice,
  OperationPill,
  SectionHeading,
  operationStyles,
} from "@/components/operations/OperationsUI";

export default function TransactionsPage() {
  return (
    <TransactionAccess>
      <History />
    </TransactionAccess>
  );
}
function History() {
  const page = useTransactionHistory(),
    review = page.visibleRows.filter(
      (r) => r.money_review.length > 0 || r.currency_review,
    ).length;
  return (
    <div className={operationStyles.page}>
      <OperationsHeader
        icon={ArrowRightLeft}
        eyebrow="Finanzas · Movimientos"
        title="Transacciones"
        description="Movimientos contables registrados con importes decimales y su moneda informada, en páginas de hasta 50 filas."
        actions={
          <>
            <Button
              className={operationStyles.button}
              variant="outline"
              onClick={() => {
                void page.refresh();
              }}
            >
              <RefreshCw
                aria-hidden="true"
                className={`h-4 w-4 ${page.isLoading ? "animate-spin motion-reduce:animate-none" : ""}`}
              />
              Actualizar consulta
            </Button>
            <Button
              className={operationStyles.primaryButton}
              disabled={
                page.isLoading ||
                !page.loaded ||
                !!page.error ||
                !page.visibleRows.length
              }
              onClick={page.exportPage}
            >
              <Download aria-hidden="true" className="h-4 w-4" />
              Exportar página CSV
            </Button>
          </>
        }
      />
      <Card className={operationStyles.panel}>
        <CardHeader>
          <SectionHeading
            icon={ListFilter}
            title="Consulta de movimientos"
            description="Filtra en el servidor y busca entre las filas de la página confirmada."
          />
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="min-w-0">
            <label
              htmlFor="transaction-search"
              className="block text-sm font-medium mb-2"
            >
              Buscar solo en esta página
            </label>
            <div className="relative">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-3 h-4 w-4 text-slate-400"
              />
              <input
                id="transaction-search"
                className={`${operationStyles.field} pl-10`}
                value={page.search}
                onChange={(e) => page.setSearch(e.target.value)}
                placeholder="ID, descripción, referencia o rider"
              />
            </div>
          </div>
          <div className="min-w-0">
            <label
              htmlFor="transaction-type"
              className="block text-sm font-medium mb-2"
            >
              Tipo en el servidor
            </label>
            <select
              id="transaction-type"
              className={operationStyles.field}
              value={page.selected.type}
              onChange={(e) => {
                void page.setFilter("type", e.target.value);
              }}
            >
              <option value="ALL">Todos los tipos</option>
              {TRANSACTION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <label
              htmlFor="transaction-status"
              className="block text-sm font-medium mb-2"
            >
              Estado en el servidor
            </label>
            <select
              id="transaction-status"
              className={operationStyles.field}
              value={page.selected.status}
              onChange={(e) => {
                void page.setFilter("status", e.target.value);
              }}
            >
              <option value="ALL">Todos los estados</option>
              {TRANSACTION_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>
      {page.error && (
        <OperationNotice role="alert" tone="error">
          <p>{page.error}</p>
          <Button
            className={operationStyles.button}
            variant="outline"
            disabled={page.isLoading}
            onClick={() => {
              void page.retry();
            }}
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            Reintentar consulta
          </Button>
        </OperationNotice>
      )}
      {page.exportError && (
        <OperationNotice role="alert" tone="error">
          {page.exportError}
        </OperationNotice>
      )}
      {page.isLoading && (
        <OperationNotice role="status">
          Consultando transacciones…
        </OperationNotice>
      )}
      {page.loaded ? (
        <section
          aria-label="Página confirmada"
          aria-busy={page.isLoading}
          className="space-y-5"
        >
          <OperationNotice>
            <p className="font-semibold">
              Consulta confirmada: tipo {page.type}; estado {page.status}.
            </p>
            <p>
              {page.rows.length} filas cargadas; {page.visibleRows.length}{" "}
              coincidencias visibles. La búsqueda y el CSV solo abarcan esta
              página.
            </p>
            <p>
              El importe conserva su signo registrado; un retiro positivo no se
              convierte en ingreso. El estado contable no certifica una
              transferencia bancaria.
            </p>
            <p>
              Corte de lectura:{" "}
              {transactionDateLabel(page.read_context?.generated_at)}.
            </p>
          </OperationNotice>
          <div
            aria-label="Indicadores de las coincidencias de esta página"
            className="grid grid-cols-1 sm:grid-cols-3 gap-3"
          >
            <OperationMetric
              icon={ListOrdered}
              tone="blue"
              label="Filas visibles"
              value={page.visibleRows.length}
            />
            <OperationMetric
              icon={WalletCards}
              tone="violet"
              label="Sin moneda informada"
              value={page.visibleRows.filter((r) => r.currency === null).length}
            />
            <OperationMetric
              icon={ShieldAlert}
              tone="amber"
              label="Registros por revisar"
              value={review}
            />
          </div>
          <Card className={operationStyles.panel}>
            <CardContent className="p-0 overflow-x-auto">
              {!page.rows.length ? (
                <p className="p-6 text-slate-600">
                  No hay transacciones en esta página de la consulta.
                </p>
              ) : !page.visibleRows.length ? (
                <p className="p-6 text-slate-600">
                  Sin coincidencias en esta página. Puedes navegar o cambiar la
                  búsqueda.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <caption className="text-left p-4 text-slate-600">
                    Movimientos de la página confirmada; fechas en UTC
                  </caption>
                  <thead className={operationStyles.tableHead}>
                    <tr className="text-left">
                      <th className="p-4">Transacción</th>
                      <th className="p-4">Fecha registrada</th>
                      <th className="p-4">Tipo / estado</th>
                      <th className="p-4">Importe registrado</th>
                      <th className="p-4">Detalle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.visibleRows.map((row) => (
                      <tr
                        key={row.id}
                        className="border-b border-slate-100 transition-colors hover:bg-blue-50/40"
                      >
                        <td className="p-4 min-w-48 max-w-sm">
                          <p className="font-mono break-all text-xs text-slate-500">
                            {row.id}
                          </p>
                          <p className="mt-1 font-semibold text-slate-900 break-words">
                            {row.description ?? "Descripción no informada"}
                          </p>
                          <p className="mt-1 text-xs text-slate-500 break-all">
                            Rider: {row.rider_id ?? "No informado"}
                          </p>
                          {row.reference_id && (
                            <p className="text-xs text-slate-500 break-all">
                              Ref: {row.reference_id}
                            </p>
                          )}
                        </td>
                        <td className="p-4 whitespace-nowrap text-slate-600">
                          {transactionDateLabel(row.created_at)}
                        </td>
                        <td className="p-4">
                          <p className="mb-2 text-xs font-medium">{row.type}</p>
                          <OperationPill
                            tone={
                              row.status === "RECHAZADO"
                                ? "rose"
                                : row.status === "PENDIENTE"
                                  ? "amber"
                                  : row.status === null
                                    ? "slate"
                                    : "emerald"
                            }
                          >
                            {row.status ?? "No informado"}
                          </OperationPill>
                        </td>
                        <td className="p-4 whitespace-nowrap">
                          <p className="font-bold text-slate-900">
                            {exactTransactionMoney(
                              row.amount,
                              row.currency,
                              row.money_review.some(
                                (i) => i.field === "amount",
                              ),
                            )}
                          </p>
                          {(row.money_review.length > 0 ||
                            row.currency_review) && (
                            <p className="mt-2 text-xs text-amber-800">
                              Datos monetarios por revisar
                            </p>
                          )}
                        </td>
                        <td className="p-4">
                          <Link
                            className={`${operationStyles.link} whitespace-nowrap`}
                            aria-label={`Ver transacción ${row.id}`}
                            href={`/manager/financial/transactions/${encodeURIComponent(row.id)}`}
                          >
                            Ver detalle
                            <ArrowRight
                              aria-hidden="true"
                              className="h-4 w-4"
                            />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </section>
      ) : (
        !page.isLoading && (
          <OperationNotice>
            No se pudo comprobar el historial. No hay movimientos confirmados
            para mostrar.
          </OperationNotice>
        )
      )}
      <nav
        aria-label="Paginación de transacciones"
        className="flex flex-wrap items-center gap-3 text-sm"
      >
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={
            page.isLoading ||
            (!page.loaded && !page.error) ||
            (page.offset === 0 && !page.error)
          }
          onClick={() => {
            void page.first();
          }}
        >
          Volver al inicio
        </Button>
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={page.isLoading || page.offset === 0}
          onClick={() => {
            void page.previous();
          }}
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          Anterior
        </Button>
        <span aria-live="polite" className="font-semibold text-slate-600">
          Página {page.offset / TRANSACTION_PAGE_SIZE + 1}
        </span>
        <Button
          className={operationStyles.button}
          variant="outline"
          disabled={page.isLoading || !page.hasNext}
          onClick={() => {
            void page.next();
          }}
        >
          Siguiente
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Button>
      </nav>
      <p className="text-xs leading-relaxed text-slate-500">
        El servidor usa desplazamientos: cambios concurrentes pueden mover
        filas. Si el historial cambia, vuelve al inicio. No se informa un total
        global ni se exporta el historial completo.
      </p>
    </div>
  );
}
