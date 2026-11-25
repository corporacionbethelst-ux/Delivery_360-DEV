"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ClipboardList } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { FAILURE_CAUSES } from "@/lib/delivery-failure";
import { capturePrivateTask } from "@/lib/private-task";
import { toast } from "@/lib/feedback";
import type { OperationalHttpOrder } from "@/lib/operational-catalog";
import { deliveryService, type FailureCause } from "@/services/delivery.service";

export function OrderFailureDialog({ order, onClose, onRefresh }: {
  order: OperationalHttpOrder;
  onClose: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [cause, setCause] = useState<FailureCause | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const delivery = order.delivery;
  const coherent = !order.assignment_review && order.status === "EN_RUTA" &&
    !!delivery?.id && delivery.order_id === order.id && !!order.assigned_rider_id &&
    delivery.rider_id === order.assigned_rider_id &&
    ["PENDIENTE", "INICIADA", "EN_PICKUP", "EN_ROUTE", "EN_DESTINO"].includes(delivery.status);

  async function perform(refreshOnly = false) {
    if (pending.current || (!refreshOnly && (!coherent || !FAILURE_CAUSES.some(option => option.value === cause)))) return;
    pending.current = true;
    setBusy(true);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      if (!refreshOnly) await deliveryService.failDelivery(delivery!.id, cause as FailureCause);
      task.assertCurrent();
      if (!mounted.current) return;
      await onRefresh();
      task.assertCurrent();
      if (!mounted.current) return;
      if (!refreshOnly) {
        toast.success("Intento fallido registrado");
      }
      onClose();
    } catch (failure: unknown) {
      if (mounted.current && task?.isCurrent()) {
        setError(failure instanceof Error ? failure.message : "No se pudo registrar el intento fallido");
      }
    } finally {
      pending.current = false;
      if (mounted.current && task?.isCurrent()) setBusy(false);
    }
  }

  return <Dialog open onOpenChange={open => { if (!open && !pending.current) onClose(); }}>
    <DialogContent className="w-[calc(100vw-2rem)] sm:w-full sm:max-w-lg max-h-[90dvh] overflow-y-auto border-orange-200 p-0">
      <form onSubmit={event => { event.preventDefault(); void perform(); }}>
        <DialogHeader className="rounded-t-lg border-b border-orange-100 bg-gradient-to-br from-amber-50 via-orange-50 to-rose-50 px-6 py-5 text-left">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white text-orange-600 shadow-sm"><AlertTriangle className="h-6 w-6" aria-hidden="true" /></div>
            <span className="rounded-full border border-orange-200 bg-white/80 px-3 py-1 text-xs font-medium text-orange-900">Cierre operativo</span>
          </div>
          <DialogTitle className="text-xl text-slate-900">Registrar intento fallido</DialogTitle>
          <DialogDescription className="text-slate-600">Orden #{order.external_id || order.id.slice(0, 8)}. Revisa el motivo antes de confirmar el cierre.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5 px-6 py-5">
          <div className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
            <ClipboardList className="mt-0.5 h-5 w-5 shrink-0 text-orange-600" aria-hidden="true" />
            <p>La orden y su entrega se actualizarán juntas. El motivo quedará registrado en el detalle de la entrega.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="order-failure-cause">Motivo del intento fallido</Label>
            <select id="order-failure-cause" value={cause} disabled={busy || !coherent} required
              onChange={event => setCause(event.target.value as FailureCause)}
              className="h-auto min-h-11 w-full rounded-xl border border-orange-200 bg-white px-3 py-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-orange-400">
              <option value="">Selecciona el motivo observado</option>
              {FAILURE_CAUSES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <p className="text-xs text-slate-500">El sistema verificará las condiciones del bono. Seleccionar un motivo no confirma un pago.</p>
          </div>
          {!coherent && <Alert variant="destructive"><AlertDescription>La asignación o el estado requiere revisión. Actualiza la consulta antes de continuar.</AlertDescription></Alert>}
          {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        </div>
        <DialogFooter className="gap-2 border-t border-slate-100 bg-slate-50/60 px-6 py-4">
          {(error || !coherent) && <Button type="button" variant="outline" disabled={busy} onClick={() => void perform(true)}>Consultar estado</Button>}
          <Button type="button" variant="outline" disabled={busy} onClick={onClose}>Volver</Button>
          <Button type="submit" className="bg-orange-600 hover:bg-orange-700" disabled={busy || !cause || !coherent}>{busy ? "Verificando..." : "Confirmar fallo"}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
