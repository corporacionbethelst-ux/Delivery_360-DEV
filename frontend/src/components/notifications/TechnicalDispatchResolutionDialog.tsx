'use client';

import { useEffect, useRef, useState } from 'react';
import { Archive, AlertTriangle } from 'lucide-react';
import { terminalNotifications, newReviewId, type TerminalDispatch, type TechnicalResolution } from '@/services/terminal-notifications.service';
import { capturePrivateTask } from '@/lib/private-task';
import { toast } from '@/lib/feedback';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

export function TechnicalDispatchResolutionDialog({ row, onClose, onResolved, onRefresh }: {
  row: TerminalDispatch; onClose: () => void; onResolved: () => void; onRefresh: () => void;
}) {
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitted = useRef<TechnicalResolution | null>(null);
  const pending = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function confirm() {
    if (pending.current || row.state !== 'invalid' || !row.revision || !acknowledged || reference.trim().length < 8) return;
    pending.current = true; setBusy(true); setError(null);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      const body = submitted.current || { resolution_id: newReviewId(), revision: row.revision, action: 'close_without_resend' as const, reference: reference.trim(), note: note.trim() };
      submitted.current = body; setLocked(true);
      await terminalNotifications.resolve(row.id, body); task.assertCurrent();
      if (!alive.current) return;
      toast.success('Cierre técnico registrado; no se reenviará el aviso');
      onResolved();
    } catch (e) {
      if (alive.current && task?.isCurrent()) {
        const failure = e as { response?: { status?: number; data?: { detail?: unknown } }; message?: unknown };
        if (failure.response?.status === 422) { submitted.current = null; setLocked(false); }
        setError(typeof failure.response?.data?.detail === 'string' ? failure.response.data.detail : typeof failure.message === 'string' ? failure.message : 'No se pudo confirmar el cierre');
      }
    } finally { pending.current = false; if (alive.current && task?.isCurrent()) setBusy(false); }
  }
  return <Dialog open onOpenChange={value => { if (!value && !pending.current) onClose(); }}>
    <DialogContent className="w-[calc(100vw-2rem)] sm:w-full sm:max-w-lg max-h-[90dvh] flex flex-col overflow-hidden border-indigo-200">
      <DialogHeader className="shrink-0"><div className="mb-2 w-fit rounded-xl bg-indigo-50 p-3 text-indigo-700"><Archive aria-hidden="true" className="h-6 w-6" /></div>
        <DialogTitle>Cerrar seguimiento técnico</DialogTitle><DialogDescription>Documenta la decisión administrativa y conserva el aviso original.</DialogDescription></DialogHeader>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        <div className="flex gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-950"><AlertTriangle aria-hidden="true" className="h-5 w-5 shrink-0" /><p>El registro saldrá de pendientes. Este cierre no reenvía mensajes ni confirma aceptación del proveedor, entrega o pago.</p></div>
        <p className="break-all text-xs text-slate-500">Aviso {row.id}</p>
        <div className="space-y-2"><Label htmlFor="technical-reference">Referencia del cierre técnico</Label><Input id="technical-reference" value={reference} onChange={event => setReference(event.target.value)} disabled={busy || locked} maxLength={200} /><p className="text-xs text-slate-500">Indica el caso o la revisión que respalda tu decisión, con al menos ocho caracteres.</p></div>
        <div className="space-y-2"><Label htmlFor="technical-note">Observaciones del cierre técnico</Label><Textarea id="technical-note" value={note} onChange={event => setNote(event.target.value)} disabled={busy || locked} maxLength={500} /></div>
        <label className="flex gap-3 rounded-lg border border-slate-200 p-3 text-sm text-slate-700"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} disabled={busy || locked} /><span>He revisado el caso y entiendo que este cierre conserva la evidencia sin reenviar el aviso.</span></label>
      </div>
      {error && <Alert variant="destructive" className="shrink-0"><AlertDescription>{error} {locked && 'Puedes repetir el mismo cierre o consultar el estado vigente.'}</AlertDescription></Alert>}
      <DialogFooter className="shrink-0 gap-2">
        <Button variant="outline" disabled={busy} onClick={error ? onRefresh : onClose}>{error ? 'Consultar estado' : 'Volver'}</Button>
        <Button className="bg-indigo-700 hover:bg-indigo-800" disabled={busy || !acknowledged || reference.trim().length < 8} onClick={() => void confirm()}>{busy ? 'Registrando...' : locked ? 'Reintentar cierre' : 'Cerrar sin reenviar'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
