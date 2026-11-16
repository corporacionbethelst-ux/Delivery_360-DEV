"use client";
import Link from "next/link";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useTransactionDetail } from "@/hooks/useTransactionDetail";
import { TransactionAccess } from "@/components/financial/TransactionAccess";
import {
  transactionDateLabel,
  transactionId,
} from "@/lib/transaction-contract";
import { capturePrivateTask } from "@/lib/private-task";
import { exactTransactionMoney } from "@/lib/transaction-exact";
import { ArrowLeft, ArrowRightLeft, Printer, RefreshCw } from "lucide-react";
import {
  OperationsHeader,
  OperationNotice,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function TransactionDetailPage() {
  const params = useParams(),
    id = typeof params.id === "string" ? params.id : "";
  return (
    <TransactionAccess resource={id}>
      <Detail id={id} />
    </TransactionAccess>
  );
}
function Detail({ id }: { id: string }) {
  const page = useTransactionDetail(id),
    data = page.data;
  const [printError, setPrintError] = useState<string | null>(null);
  const print = () => {
    try {
      capturePrivateTask().assertCurrent();
      if (
        !data ||
        data.id !== transactionId(id) ||
        page.isLoading ||
        page.error
      )
        return;
      window.print();
      setPrintError(null);
    } catch {
      setPrintError("No se pudo imprimir el registro confirmado.");
    }
  };
  const amount = (
    value: string | null,
    field: "amount" | "balance_before" | "balance_after",
  ) =>
    exactTransactionMoney(
      value,
      data?.currency ?? null,
      data?.money_review.some((i) => i.field === field),
    );
  return (
    <div className={`${operationStyles.page} max-w-5xl`}>
      <OperationsHeader
        audit
        eyebrow="Finanzas · Registro contable"
        icon={ArrowRightLeft}
        title="Detalle de transacción"
        description={
          <p className="font-mono text-xs break-all">
            ID solicitado: {id || "No informado"}
          </p>
        }
        actions={
          <>
            <Button
              className={operationStyles.button}
              variant="outline"
              onClick={() => {
                setPrintError(null);
                void page.refresh();
              }}
            >
              <RefreshCw aria-hidden="true" className="h-4 w-4" />
              Consultar transacción
            </Button>
            <Button
              className={operationStyles.primaryButton}
              disabled={!data || page.isLoading || !!page.error}
              onClick={print}
            >
              <Printer aria-hidden="true" className="h-4 w-4" />
              Imprimir registro
            </Button>
          </>
        }
      />
      <Link
        className={operationStyles.link}
        href="/manager/financial/transactions"
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        Volver al historial
      </Link>
      {page.isLoading && <p role="status">Consultando el registro…</p>}
      {page.error && (
        <div
          role="alert"
          className="rounded border bg-red-50 p-4 text-red-800 space-y-2"
        >
          <p>{page.error}</p>
          <Button
            variant="outline"
            disabled={page.isLoading}
            onClick={() => {
              void page.refresh();
            }}
          >
            Reintentar lectura
          </Button>
        </div>
      )}
      {printError && (
        <p role="alert" className="text-red-800">
          {printError}
        </p>
      )}
      {!data && !page.isLoading && (
        <p>No hay una transacción confirmada para esta consulta.</p>
      )}
      {data && (
        <section
          aria-label="Transacción confirmada"
          aria-busy={page.isLoading}
          className="space-y-5"
        >
          {(data.money_review.length > 0 || data.currency_review) && (
            <OperationNotice tone="warning">
              <p className="font-semibold">Datos monetarios por revisar</p>
              <p>
                El registro se conserva. Los importes que no se pueden confirmar
                quedan por revisar; no se sustituyen por cero.
              </p>
              {data.money_review.map((i) => (
                <p key={i.field}>
                  {i.field === "amount"
                    ? "Importe"
                    : i.field === "balance_before"
                      ? "Saldo anterior"
                      : "Saldo posterior"}
                  :{" "}
                  {i.reason === "NO_REGISTRADO"
                    ? "No registrado"
                    : "Importe no válido"}
                </p>
              ))}
              {data.currency_review && (
                <p>
                  Moneda original por revisar:{" "}
                  {data.currency_recorded || "Código vacío"}.
                </p>
              )}
            </OperationNotice>
          )}
          <Card className={operationStyles.panel}>
            <CardHeader>
              <CardTitle>Importes y estado registrados</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="font-mono break-all">ID confirmado: {data.id}</p>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {[
                  ["Importe registrado", amount(data.amount, "amount")],
                  ["Moneda", data.currency ?? "No informada"],
                  ["Tipo registrado", data.type],
                  ["Estado registrado", data.status ?? "No informado"],
                  [
                    "Saldo anterior informado",
                    amount(data.balance_before, "balance_before"),
                  ],
                  [
                    "Saldo posterior informado",
                    amount(data.balance_after, "balance_after"),
                  ],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50/70 via-white to-violet-50/50 p-4 min-w-0"
                  >
                    <dt className="text-sm text-gray-600">{label}</dt>
                    <dd className="font-semibold break-words">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-sm text-gray-600">
                El signo es el del importe guardado, sin reinterpretar cargos
                como ingresos. Este registro contable y sus estados no son una
                confirmación bancaria. Los saldos informados son fotografías del
                registro; no representan el saldo disponible actual.
              </p>
            </CardContent>
          </Card>
          <Card className={operationStyles.panel}>
            <CardHeader>
              <CardTitle>Origen y trazabilidad informados</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {[
                  ["Descripción", data.description ?? "No informada"],
                  ["Referencia", data.reference_id ?? "No informada"],
                  ["Rider asociado", data.rider_id ?? "No informado"],
                  ["Tipo de origen", data.source_type ?? "No informado"],
                  ["ID de origen", data.source_id ?? "No informado"],
                  [
                    "Clave de idempotencia informada",
                    data.idempotency_key ?? "No informada",
                  ],
                  [
                    "Actor creador informado",
                    data.created_by_user_id ?? "No informado",
                  ],
                  [
                    "Fecha de creación registrada",
                    transactionDateLabel(data.created_at),
                  ],
                  [
                    "Última actualización registrada",
                    transactionDateLabel(data.updated_at),
                  ],
                  [
                    "Fecha de proceso informada",
                    transactionDateLabel(data.processed_at),
                  ],
                  [
                    "Corte de lectura",
                    transactionDateLabel(data.read_context.generated_at),
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-sm text-gray-600">{label}</dt>
                    <dd className="break-all">{value}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  );
}
