import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';

export type CheckCode = 'mail_enabled' | 'host' | 'port' | 'authentication' | 'sender' | 'tls' | 'timeout' | 'account_sid' | 'auth_token' | 'sdk' | 'credentials_reference' | 'credentials_file';
export type CheckState = 'ok' | 'missing' | 'invalid' | 'disabled';
export type ProviderState = 'paused' | 'incomplete' | 'locally_configured';
export type ProviderDiagnostic = { channel: 'EMAIL' | 'SMS' | 'PUSH'; provider: 'SMTP' | 'TWILIO' | 'FCM'; state: ProviderState; checks: { code: CheckCode; state: CheckState }[] };
export type ProviderDiagnostics = { version: 1; scope: 'local_only'; external_delivery_verified: false; checked_at: string; notifications_enabled: boolean; providers: ProviderDiagnostic[] };
const layouts = {
  EMAIL: { provider: 'SMTP', codes: ['mail_enabled','host','port','authentication','sender','tls','timeout'] },
  SMS: { provider: 'TWILIO', codes: ['account_sid','auth_token','sender','sdk','timeout'] },
  PUSH: { provider: 'FCM', codes: ['credentials_reference','credentials_file','sdk','timeout'] },
};
function record(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== keys.length || Object.keys(value).some(key => !keys.includes(key))) throw new Error('Diagnóstico de proveedores no válido');
  return value as Record<string, unknown>;
}
export async function readProviderDiagnostics(): Promise<ProviderDiagnostics> {
  const task = capturePrivateTask();
  const raw = await api.get<unknown>('/notifications/providers/diagnostics'); task.assertCurrent();
  const data = record(raw, ['version','scope','external_delivery_verified','checked_at','notifications_enabled','providers']);
  if (data.version !== 1 || data.scope !== 'local_only' || data.external_delivery_verified !== false || typeof data.notifications_enabled !== 'boolean' || typeof data.checked_at !== 'string' || !Number.isFinite(new Date(data.checked_at).getTime()) || !Array.isArray(data.providers) || data.providers.length !== 3) throw new Error('Diagnóstico de proveedores no válido');
  const channels = new Set<string>();
  for (const item of data.providers) {
    const row = record(item, ['channel','provider','state','checks']);
    if (typeof row.channel !== 'string' || !Object.prototype.hasOwnProperty.call(layouts, row.channel) || channels.has(row.channel)) throw new Error('Canales de diagnóstico no válidos');
    channels.add(row.channel); const layout = layouts[row.channel as keyof typeof layouts];
    if (row.provider !== layout.provider || !['paused','incomplete','locally_configured'].includes(String(row.state)) || !Array.isArray(row.checks) || row.checks.length !== layout.codes.length) throw new Error('Proveedor de diagnóstico no válido');
    const codes = new Set<string>();
    for (const value of row.checks) {
      const check = record(value, ['code','state']);
      if (typeof check.code !== 'string' || !layout.codes.includes(check.code) || codes.has(check.code) || !['ok','missing','invalid','disabled'].includes(String(check.state))) throw new Error('Comprobación de diagnóstico no válida');
      codes.add(check.code);
    }
    const mailDisabled = row.channel === 'EMAIL' && row.checks.some(value => { const check = value as {code: string; state: string}; return check.code === 'mail_enabled' && check.state === 'disabled'; });
    const expected = !data.notifications_enabled || mailDisabled ? 'paused' : row.checks.every(value => (value as {state: string}).state === 'ok') ? 'locally_configured' : 'incomplete';
    if (row.state !== expected) throw new Error('Estado de configuración contradictorio');
  }
  return data as ProviderDiagnostics;
}
