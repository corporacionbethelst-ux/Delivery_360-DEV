import '@testing-library/jest-dom';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {NotificationProviderDiagnosticsPanel} from '@/components/notifications/NotificationProviderDiagnosticsPanel';
import {readProviderDiagnostics} from '@/services/notification-diagnostics.service';
import {api} from '@/lib/api';
import {storeTokens,clearStoredTokens} from '@/lib/auth-session';
import {toast} from '@/lib/feedback';

let mockUser:{id:string;role:string}|null={id:'staff',role:'GERENTE'};
jest.mock('@/stores/authStore',()=>({useAuthStore:()=>({user:mockUser})}));
jest.mock('@/lib/api',()=>({api:{get:jest.fn(),post:jest.fn()}}));
jest.mock('@/lib/feedback',()=>({toast:{success:jest.fn()}}));
function report(){return {version:1,scope:'local_only',external_delivery_verified:false,checked_at:'2026-11-26T14:00:00+00:00',notifications_enabled:true,providers:[
  {channel:'EMAIL',provider:'SMTP',state:'locally_configured',checks:['mail_enabled','host','port','authentication','sender','tls','timeout'].map(code=>({code,state:'ok'}))},
  {channel:'SMS',provider:'TWILIO',state:'incomplete',checks:['account_sid','auth_token','sender','sdk','timeout'].map(code=>({code,state:code==='sdk'?'missing':'ok'}))},
  {channel:'PUSH',provider:'FCM',state:'locally_configured',checks:['credentials_reference','credentials_file','sdk','timeout'].map(code=>({code,state:'ok'}))},
]};}
const get=jest.mocked(api.get);
beforeEach(()=>{jest.resetAllMocks();mockUser={id:'staff',role:'GERENTE'};storeTokens({access_token:'diagnostics-a',refresh_token:'refresh-a'});get.mockResolvedValue(report());});
afterEach(()=>clearStoredTokens());
function deferred<T>(){let resolve!:(v:T)=>void;let reject!:(v:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
function consult(){fireEvent.click(screen.getByRole('button',{name:'Consultar configuración'}));}

it.each(['OPERADOR','REPARTIDOR','CLIENTE','AUDITOR',null])('does not load or expose diagnostics for %s',role=>{
 mockUser=role?{id:'other',role}:null;render(<NotificationProviderDiagnosticsPanel/>);expect(get).not.toHaveBeenCalled();expect(screen.queryByRole('region')).not.toBeInTheDocument();
});
it.each(['GERENTE','SUPERADMIN'])('consults explicitly for %s without a sending request',async role=>{
 mockUser={id:'staff',role};render(<NotificationProviderDiagnosticsPanel/>);expect(get).not.toHaveBeenCalled();consult();
 expect(await screen.findByRole('article',{name:'Configuración Correo electrónico'})).toBeInTheDocument();
 expect(screen.getAllByRole('article')).toHaveLength(3);expect(screen.getByText('Configuración pendiente')).toBeInTheDocument();
 expect(screen.getByText(/La homologación del proveedor/)).toBeInTheDocument();expect(screen.getByText(/Caracas/)).toBeInTheDocument();
 expect(api.post).not.toHaveBeenCalled();expect(toast.success).toHaveBeenCalledWith('Diagnóstico local actualizado');
});
it('blocks double clicks while the private read is pending',async()=>{
 const request=deferred<any>();get.mockReturnValue(request.promise);render(<NotificationProviderDiagnosticsPanel/>);consult();consult();
 expect(get).toHaveBeenCalledTimes(1);await act(async()=>request.resolve(report()));
 expect(screen.getByRole('button',{name:'Actualizar diagnóstico'})).toBeEnabled();
});
it('reports a global pause separately from incomplete configuration',async()=>{
 const data=report();data.notifications_enabled=false;data.providers.forEach(p=>p.state='paused');get.mockResolvedValue(data);
 render(<NotificationProviderDiagnosticsPanel/>);consult();expect(await screen.findByText('Notificaciones externas pausadas')).toBeInTheDocument();expect(screen.getAllByText('Canal pausado')).toHaveLength(3);
});
it('keeps the last report and uses a central error modal without echoing private details',async()=>{
 render(<NotificationProviderDiagnosticsPanel/>);consult();await screen.findByRole('button',{name:'Actualizar diagnóstico'});
 get.mockRejectedValue({response:{data:{detail:'PRIVATE_SERVER_PASSWORD'}}});fireEvent.click(screen.getByRole('button',{name:'Actualizar diagnóstico'}));
 expect(await screen.findByRole('dialog',{name:'No se pudo consultar la configuración'})).toBeInTheDocument();
 expect(screen.getByRole('alert')).toHaveTextContent('Se conservan los últimos datos');expect(screen.queryByText(/PRIVATE_SERVER_PASSWORD/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Volver'}));await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());expect(screen.getAllByRole('article')).toHaveLength(3);
});
it('retries by GET only and does not treat an error as a successful report',async()=>{
 get.mockRejectedValueOnce(new Error('PRIVATE_INTERNAL_DETAIL')).mockResolvedValue(report());render(<NotificationProviderDiagnosticsPanel/>);consult();
 await screen.findByRole('dialog');expect(toast.success).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Reintentar diagnóstico'}));
 await screen.findByRole('button',{name:'Actualizar diagnóstico'});expect(get).toHaveBeenCalledTimes(2);expect(api.post).not.toHaveBeenCalled();
});
it('drops delayed diagnostics and feedback when credentials change',async()=>{
 const request=deferred<any>();get.mockReturnValue(request.promise);render(<NotificationProviderDiagnosticsPanel/>);consult();
 await act(async()=>{storeTokens({access_token:'diagnostics-b',refresh_token:'refresh-b'});request.resolve(report());});
 expect(screen.queryByRole('article')).not.toBeInTheDocument();expect(toast.success).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'Consultar configuración'})).toBeEnabled();
});
it('does not update after unmount',async()=>{
 const request=deferred<any>();get.mockReturnValue(request.promise);const view=render(<NotificationProviderDiagnosticsPanel/>);consult();view.unmount();await act(async()=>request.resolve(report()));expect(toast.success).not.toHaveBeenCalled();
});

it.each(['version','scope','external','date','channels','vendor','state','codes','check_state','private_field','ready','pause','provider_paused','empty_incomplete'])('rejects malformed or contradictory %s data',async fault=>{
 const data:any=report();
 if(fault==='version')data.version=2;if(fault==='scope')data.scope='external';if(fault==='external')data.external_delivery_verified=true;if(fault==='date')data.checked_at='bad';
 if(fault==='channels')data.providers[1]=data.providers[0];if(fault==='vendor')data.providers[0].provider='FCM';if(fault==='state')data.providers[0].state='delivered';
 if(fault==='codes')data.providers[0].checks[1].code='mail_enabled';if(fault==='check_state')data.providers[0].checks[0].state='sent';if(fault==='private_field')data.password='PRIVATE';
 if(fault==='ready')data.providers[0].checks[0].state='missing';if(fault==='pause')data.notifications_enabled=false;
 if(fault==='provider_paused')data.providers[1].state='paused';if(fault==='empty_incomplete')data.providers[0].state='incomplete';
 get.mockResolvedValue(data);await expect(readProviderDiagnostics()).rejects.toThrow();expect(api.post).not.toHaveBeenCalled();
});
it('never hands a response to the caller from a former credential generation',async()=>{
 const request=deferred<any>();get.mockReturnValue(request.promise);const read=readProviderDiagnostics();const assertion=expect(read).rejects.toThrow();
 storeTokens({access_token:'diagnostics-new',refresh_token:'refresh-new'});request.resolve(report());await assertion;
});
