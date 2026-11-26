'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Settings2, RefreshCw, CheckCircle2, AlertCircle, PauseCircle } from 'lucide-react';
import { useAuthStore } from '@/stores/authStore';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { toast } from '@/lib/feedback';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { capturePrivateTask } from '@/lib/private-task';
import { readProviderDiagnostics, type ProviderDiagnostics, type CheckCode, type CheckState } from '@/services/notification-diagnostics.service';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

const labels: Record<CheckCode, string> = { mail_enabled:'Correo habilitado', host:'Servidor indicado', port:'Puerto válido', authentication:'Credenciales SMTP presentes', sender:'Formato del remitente', tls:'Transporte cifrado', timeout:'Tiempo de espera acotado', account_sid:'Formato de la cuenta', auth_token:'Credencial de acceso presente', sdk:'Componente de envío disponible', credentials_reference:'Referencia de credenciales indicada', credentials_file:'Archivo local accesible' };
const checks: Record<CheckState, string> = { ok:'Comprobado localmente', missing:'Sin configurar', invalid:'Revisar', disabled:'Deshabilitado' };
const names = {EMAIL:'Correo electrónico',SMS:'Mensajes SMS',PUSH:'Notificaciones push'};
const states = {paused:'Canal pausado',incomplete:'Configuración pendiente',locally_configured:'Datos locales presentes'};

export function NotificationProviderDiagnosticsPanel() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const {user} = useAuthStore();
  if (!user || !['GERENTE','SUPERADMIN'].includes(user.role)) return null;
  return <DiagnosticsPanel key={JSON.stringify([generation,user.id,user.role])} />;
}
function DiagnosticsPanel() {
  const [data,setData] = useState<ProviderDiagnostics | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState(false);
  const pending = useRef(false); const alive = useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  async function load() {
    if(pending.current)return;
    pending.current=true;setBusy(true);setError(false);
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    try {
      task=capturePrivateTask();const result=await readProviderDiagnostics();task.assertCurrent();
      if(alive.current){setData(result);toast.success('Diagnóstico local actualizado');}
    } catch {if(alive.current && task?.isCurrent())setError(true);}
    finally {pending.current=false;if(alive.current && task?.isCurrent())setBusy(false);}
  }
  return <section aria-label="Configuración de canales externos" className="overflow-hidden rounded-2xl border border-cyan-100 bg-white shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cyan-100 bg-gradient-to-br from-cyan-50 via-sky-50 to-white p-5">
      <div className="flex items-center gap-3"><div className="rounded-xl bg-white p-2 text-cyan-700 shadow-sm"><Settings2 aria-hidden="true" className="h-6 w-6" /></div><div><h2 className="font-semibold text-slate-900">Configuración de canales externos</h2><p className="text-xs text-slate-600">Diagnóstico local de correo, SMS y push</p></div></div>
      <Button variant="outline" disabled={busy} onClick={()=>void load()}><RefreshCw aria-hidden="true" className={`mr-2 h-4 w-4 ${busy?'animate-spin':''}`} />{data?'Actualizar diagnóstico':'Consultar configuración'}</Button>
    </div>
    <div className="space-y-4 p-5">
      <p className="text-sm text-slate-600">Esta consulta no envía mensajes ni verifica conexión, credenciales con el proveedor, cuotas o recepción. No muestra valores de configuración privados.</p>
      <Dialog open={error} onOpenChange={setError}><DialogContent className="w-[calc(100vw-2rem)] sm:w-full sm:max-w-md max-h-[90dvh] overflow-y-auto"><DialogHeader><DialogTitle>No se pudo consultar la configuración</DialogTitle><DialogDescription>La consulta no se completó. No se ha enviado ningún mensaje.</DialogDescription></DialogHeader><Alert variant="destructive"><AlertDescription>{data?'Se conservan los últimos datos consultados; actualiza para comprobar el estado vigente.':'Vuelve a intentarlo para obtener el diagnóstico local.'}</AlertDescription></Alert><DialogFooter className="gap-2"><Button variant="outline" onClick={()=>setError(false)}>Volver</Button><Button disabled={busy} onClick={()=>void load()}>Reintentar diagnóstico</Button></DialogFooter></DialogContent></Dialog>
      {!data && !busy && !error && <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-500">Consulta los canales para identificar qué configuración local está pendiente.</p>}
      {data && <>
        <div className="flex flex-wrap justify-between gap-2 text-xs text-slate-500"><p>{data.notifications_enabled?'Notificaciones externas habilitadas':'Notificaciones externas pausadas'}</p><p>Consulta: {new Intl.DateTimeFormat('es-VE',{timeZone:'America/Caracas',dateStyle:'short',timeStyle:'short'}).format(new Date(data.checked_at))} (Caracas)</p></div>
        <div className="grid gap-3 lg:grid-cols-3">{data.providers.map(provider=><article key={provider.channel} aria-label={`Configuración ${names[provider.channel]}`} className="min-w-0 rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-800">{names[provider.channel]}</h3><span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{provider.provider}</span></div>
          <p className={`mt-2 text-xs font-medium ${provider.state==='incomplete'?'text-amber-800':provider.state==='paused'?'text-slate-500':'text-blue-700'}`}>{states[provider.state]}</p>
          <ul className="mt-4 space-y-3">{provider.checks.map(check=><li key={check.code} className="flex items-start gap-2 text-xs"><span className="mt-0.5 shrink-0">{check.state==='ok'?<CheckCircle2 aria-hidden="true" className="h-4 w-4 text-teal-600" />:check.state==='disabled'?<PauseCircle aria-hidden="true" className="h-4 w-4 text-slate-400" />:<AlertCircle aria-hidden="true" className="h-4 w-4 text-amber-600" />}</span><span className="min-w-0 text-slate-700">{labels[check.code]}<span className="mt-0.5 block text-slate-500">{checks[check.state]}</span></span></li>)}</ul>
        </article>)}</div>
        <p className="rounded-xl bg-blue-50 p-3 text-xs text-blue-900">Los datos locales presentes no acreditan un envío. La homologación del proveedor y de los destinos reales sigue siendo un paso independiente.</p>
      </>}
    </div>
  </section>;
}
