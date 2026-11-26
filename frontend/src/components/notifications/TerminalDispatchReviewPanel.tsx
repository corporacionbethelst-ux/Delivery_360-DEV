'use client';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ShieldCheck, AlertTriangle, RefreshCw } from 'lucide-react';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { capturePrivateTask } from '@/lib/private-task';
import { toast } from '@/lib/feedback';
import { terminalNotifications, newReviewId, type TerminalDispatch, type DispatchReview } from '@/services/terminal-notifications.service';
import { TechnicalDispatchResolutionDialog } from '@/components/notifications/TechnicalDispatchResolutionDialog';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

const names = { entrega_completada: 'Entrega completada', entrega_fallida: 'Intento fallido', orden_cancelada: 'Orden cancelada', nuevo_pedido_asignado: 'Pedido asignado', payout_solicitado: 'Retiro solicitado', payout_aprobado: 'Retiro aprobado contablemente', payout_rechazado: 'Retiro rechazado' };
const states = { queued: 'En cola', uncertain: 'Resultado sin confirmar', invalid: 'Revisión técnica requerida', resolved: 'Cerrado sin reenvío' };
function timeLabel(row: TerminalDispatch): string {
  const attempted = row.state === 'uncertain' && row.attempt_started_at;
  const value = attempted || row.created_at;
  if (!value || !Number.isFinite(new Date(value).getTime())) return 'Fecha por revisar';
  const time = new Intl.DateTimeFormat('es-VE', { timeZone: 'America/Caracas', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
  return `${attempted ? 'Intento registrado' : 'Aviso creado'}: ${time} (Caracas)`;
}
function failureText(error: unknown): string {
  const e = error as { response?: { data?: { detail?: unknown } }; message?: unknown };
  return typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : typeof e?.message === 'string' ? e.message : 'No se pudo completar la consulta';
}
export function TerminalDispatchReviewPanel() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user } = useAuthStore();
  if (!user || !['SUPERADMIN', 'GERENTE'].includes(user.role)) return null;
  return <ReviewPanel key={JSON.stringify([generation, user.id, user.role])} />;
}
function ReviewPanel() {
  const [view, setView] = useState<'pending' | 'resolved'>('pending');
  const [technical, setTechnical] = useState<TerminalDispatch | null>(null);
  const [rows, setRows] = useState<TerminalDispatch[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [selected, setSelected] = useState<TerminalDispatch | null>(null);
  const [decision, setDecision] = useState<DispatchReview['decision'] | ''>('');
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('');
  const [locked, setLocked] = useState(false);
  const pending = useRef(false);
  const submitted = useRef<DispatchReview | null>(null);
  const reviewId = useRef('');
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function load(offset = 0, targetView = view) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask(); const page = await terminalNotifications.list(offset, targetView); task.assertCurrent();
      if (!alive.current) return;
      setRows(previous => offset === 0 ? page.items : [...previous, ...page.items.filter(row => !previous.some(old => old.id === row.id))]);
      setNext(page.next_offset); setLoaded(true);
    } catch (e) { if (alive.current && task?.isCurrent()) setError(failureText(e)); }
    finally { pending.current = false; if (alive.current && task?.isCurrent()) setBusy(false); }
  }
  function open(row: TerminalDispatch) {
    if (pending.current || row.state !== 'uncertain' || !row.attempt_id) return;
    try { reviewId.current = newReviewId(); } catch { setError('El navegador no permite iniciar una revisión segura'); return; }
    submitted.current = null; setLocked(false); setDecision(''); setReference(''); setNote(''); setModalError(null); setSelected(row);
  }
  async function confirm() {
    if (pending.current || !selected?.attempt_id || !decision || reference.trim().length < 8) return;
    pending.current = true; setBusy(true); setModalError(null);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task = capturePrivateTask();
      const body = submitted.current || { review_id: reviewId.current, attempt_id: selected.attempt_id, decision, reference: reference.trim(), note: note.trim() };
      submitted.current = body; setLocked(true);
      const result = await terminalNotifications.review(selected.id, body); task.assertCurrent();
      if (!alive.current) return;
      if (result.state === 'accepted') setRows(previous => previous.filter(row => row.id !== selected.id));
      setSelected(null);
      toast.success(result.state === 'accepted' ? 'Aceptación del proveedor registrada' : 'Revisión registrada; el envío sigue sin confirmación');
      try {
        const page = await terminalNotifications.list(); task.assertCurrent();
        if (alive.current) { setRows(page.items); setNext(page.next_offset); setLoaded(true); }
      } catch { if (alive.current && task.isCurrent()) setError('La revisión se registró; no se pudo actualizar la consulta. Actualiza para ver el estado vigente.'); }
    } catch (e) {
      if (alive.current && task?.isCurrent()) {
        if ((e as { response?: { status?: number } })?.response?.status === 422) {
          submitted.current = null; setLocked(false); reviewId.current = newReviewId();
        }
        setModalError(failureText(e));
      }
    }
    finally { pending.current = false; if (alive.current && task?.isCurrent()) setBusy(false); }
  }
  return <section aria-label="Revisión de avisos externos" className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-blue-100 bg-gradient-to-br from-blue-50 via-indigo-50 to-white p-5">
      <div className="flex items-center gap-3"><div className="rounded-xl bg-white p-2 text-blue-700 shadow-sm"><ShieldCheck aria-hidden="true" className="h-6 w-6" /></div>
        <div><h2 className="font-semibold text-slate-900">Revisión de avisos externos</h2><p className="text-xs text-slate-600">Seguimiento de aceptación del proveedor</p></div></div>
      <Button variant="outline" disabled={busy || !!technical} onClick={() => void load()}><RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />{loaded ? 'Actualizar revisión' : 'Consultar envíos'}</Button>
    </div>
    <div className="space-y-3 p-5">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Vista de avisos">
        {([['pending', 'Pendientes'], ['resolved', 'Cierres técnicos']] as const).map(([value, label]) => <Button key={value} variant={view === value ? 'default' : 'outline'} aria-pressed={view === value} disabled={busy || !!technical} onClick={() => { if (view === value || pending.current) return; setView(value); setRows([]); setLoaded(false); setNext(null); setError(null); void load(0, value); }}>{label}</Button>)}
      </div>
      <p className="text-sm text-slate-600">Los resultados inciertos quedan retenidos. Registrar una revisión no reenvía el aviso ni confirma lectura o pago.</p>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      {!loaded && <p className="text-sm text-slate-500">Consulta la cola para ver avisos pendientes y resultados sin confirmar.</p>}
      {loaded && !rows.length && <p role="status" className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600">{view === 'resolved' ? 'No hay cierres técnicos en esta consulta.' : 'No hay envíos pendientes en esta consulta.'}</p>}
      {loaded && !!rows.length && <p className="text-xs text-slate-500">{rows.length} avisos consultados. Actualiza para consultar cambios recientes.</p>}
      {rows.map(row => <article key={row.id} aria-label={`Envío ${row.id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4">
        <div className="min-w-0 space-y-1"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm text-slate-800">{names[row.event]}</strong><span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{row.channel}</span></div>
          <p className="text-xs text-slate-600">{row.payout_id ? `Solicitud de retiro ${row.payout_id.slice(0, 8)}` : row.order_code ? `Orden ${row.order_code}` : row.order_id ? `ID orden ${row.order_id.slice(0, 8)}` : row.delivery_id ? `Entrega ${row.delivery_id.slice(0, 8)}` : `Aviso ${row.id.slice(0, 8)}`} · Cuenta {row.recipient_id.slice(0, 8)}</p>
          <p className="text-xs text-slate-500">{timeLabel(row)}</p>
          {row.destination_hint && <p className="break-all text-xs text-slate-500">Destino del intento: {row.destination_hint}</p>}
          <p className={row.state === 'uncertain' ? 'text-xs font-medium text-amber-800' : 'text-xs text-slate-500'}>{states[row.state]}</p>
          {row.state === 'invalid' && <p className="max-w-xl text-xs text-slate-600">{row.diagnostic === 'policy_or_state' ? 'Revisa la política o el estado conservado del aviso.' : 'El historial no permite verificar el intento de envío.'}</p>}
          {row.state === 'resolved' && row.resolution && <div className="mt-2 rounded-lg bg-emerald-50 p-3 text-xs text-emerald-900"><p className="break-words">Referencia: {row.resolution.reference}</p><p className="mt-1 break-words">{row.resolution.note}</p><p className="mt-1">Acta {row.resolution.audit_id.slice(0, 8)} · {new Intl.DateTimeFormat('es-VE', { timeZone: 'America/Caracas', dateStyle: 'short', timeStyle: 'short' }).format(new Date(row.resolution.resolved_at))} (Caracas)</p><p className="mt-1">Cierre administrativo; no acredita envío ni pago.</p></div>}
        </div>
        {row.state === 'invalid' && <Button variant="outline" disabled={busy || !row.revision} onClick={() => setTechnical(row)}>Cerrar seguimiento técnico</Button>}
        {row.state === 'uncertain' && <Button variant="outline" disabled={busy} onClick={() => open(row)}>Revisar resultado</Button>}
      </article>)}
      {next !== null && <Button variant="outline" disabled={busy || !!error} onClick={() => void load(next)}>Cargar más envíos</Button>}
    </div>
    {technical && <TechnicalDispatchResolutionDialog row={technical} onClose={() => setTechnical(null)} onRefresh={() => { setTechnical(null); void load(); }} onResolved={() => { setRows(previous => previous.filter(row => row.id !== technical.id)); setTechnical(null); void load(); }} />}
    <Dialog open={!!selected} onOpenChange={value => { if (!value && !pending.current) setSelected(null); }}>
      <DialogContent className="w-[calc(100vw-2rem)] sm:w-full sm:max-w-lg max-h-[90dvh] overflow-y-auto border-amber-200">
        <DialogHeader><div className="mb-2 w-fit rounded-xl bg-amber-50 p-3 text-amber-700"><AlertTriangle aria-hidden="true" className="h-6 w-6" /></div>
          <DialogTitle>Revisar resultado externo</DialogTitle><DialogDescription>Registra únicamente lo que puedas verificar. Esta acción no genera otro envío.</DialogDescription></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2"><Label htmlFor="dispatch-decision">Resultado de la verificación</Label><select id="dispatch-decision" disabled={busy || locked} value={decision} onChange={event => setDecision(event.target.value as DispatchReview['decision'])} className="w-full rounded-lg border border-slate-200 bg-white p-3 text-sm"><option value="">Selecciona un resultado</option><option value="accepted">Aceptación del proveedor verificada</option><option value="unconfirmed">El resultado sigue sin confirmarse</option></select></div>
          <div className="space-y-2"><Label htmlFor="dispatch-reference">Referencia de la verificación</Label><Input id="dispatch-reference" value={reference} onChange={event => setReference(event.target.value)} maxLength={200} disabled={busy || locked} /><p className="text-xs text-slate-500">Indica una referencia verificable del proveedor o del caso revisado, de al menos ocho caracteres.</p></div>
          <div className="space-y-2"><Label htmlFor="dispatch-note">Observaciones de revisión</Label><Textarea id="dispatch-note" value={note} onChange={event => setNote(event.target.value)} maxLength={500} disabled={busy || locked} /></div>
          <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">La aceptación del proveedor no acredita recepción en el dispositivo ni un pago. Sin confirmación, el aviso permanece retenido.</p>
          {modalError && <Alert variant="destructive"><AlertDescription>{modalError} {locked && 'Puedes repetir la misma revisión o cerrar y actualizar la consulta.'}</AlertDescription></Alert>}
        </div>
        <DialogFooter className="gap-2"><Button variant="outline" disabled={busy} onClick={() => setSelected(null)}>Volver</Button><Button className="bg-blue-700 hover:bg-blue-800" disabled={busy || !decision || reference.trim().length < 8} onClick={() => void confirm()}>{busy ? 'Registrando...' : locked ? 'Reintentar revisión' : 'Registrar revisión'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </section>;
}
