import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
export type TerminalDispatch = {
  id: string; event: 'entrega_completada' | 'entrega_fallida' | 'orden_cancelada' | 'nuevo_pedido_asignado' | 'payout_solicitado' | 'payout_aprobado' | 'payout_rechazado';
  channel: 'PUSH' | 'SMS' | 'EMAIL'; recipient_id: string; order_id: string | null;
  payout_id?: string | null; state: 'queued' | 'uncertain' | 'invalid' | 'resolved'; attempt_id: string | null;
  delivery_id?: string | null; revision?: string | null; diagnostic?: 'policy_or_state' | 'unverifiable_record' | null;
  resolution?: TechnicalResolutionReceipt | null;
  created_at: string | null; destination_hint: string | null; order_code?: string | null; attempt_started_at?: string | null;
};
export type TechnicalResolution = { resolution_id: string; revision: string; action: 'close_without_resend'; reference: string; note: string };
export type TechnicalResolutionReceipt = { id: string; resolution_id: string; audit_id: string; action: 'close_without_resend'; state: 'resolved'; resolved_at: string; resolved_by: string; reference: string; note: string };
export type DispatchReview = { review_id: string; attempt_id: string; decision: 'accepted' | 'unconfirmed'; reference: string; note: string };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function id(value: unknown): string { if (typeof value !== 'string' || !uuid.test(value)) throw new Error('Identificador de revisión no válido'); return value; }
function record(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Respuesta de revisión no válida'); return value as Record<string, unknown>; }
export function newReviewId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const raw = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
  return `${raw.slice(0,8)}-${raw.slice(8,12)}-${raw.slice(12,16)}-${raw.slice(16,20)}-${raw.slice(20)}`;
}
export function isTerminalExternal(value: { channel: string; template_code?: string | null }): boolean {
  return ['EMAIL', 'SMS', 'PUSH'].includes(value.channel) && ['entrega_completada', 'entrega_fallida', 'orden_cancelada', 'nuevo_pedido_asignado', 'payout_solicitado', 'payout_aprobado', 'payout_rechazado'].includes(value.template_code || '');
}
function readResolution(value: unknown, notificationId: string): TechnicalResolutionReceipt {
  const receipt = record(value); id(receipt.resolution_id); id(receipt.audit_id); id(receipt.resolved_by);
  if (receipt.id !== notificationId || receipt.state !== 'resolved' || receipt.action !== 'close_without_resend' || typeof receipt.resolved_at !== 'string' || !Number.isFinite(new Date(receipt.resolved_at).getTime()) || typeof receipt.reference !== 'string' || receipt.reference.trim().length < 8 || receipt.reference.length > 200 || typeof receipt.note !== 'string' || receipt.note.length > 500) throw new Error('El comprobante no confirma este cierre; consulta el estado');
  return receipt as TechnicalResolutionReceipt;
}
export const terminalNotifications = {
  async resolve(notificationId: string, body: TechnicalResolution): Promise<TechnicalResolutionReceipt> {
    id(notificationId); id(body.resolution_id);
    const task = capturePrivateTask();
    const value = await api.post<unknown>(`/notifications/terminal-dispatch/${notificationId}/resolve`, body); task.assertCurrent();
    const receipt = readResolution(value, notificationId);
    if (receipt.resolution_id !== body.resolution_id || receipt.reference !== body.reference || receipt.note !== body.note) throw new Error('La respuesta no confirma esta resolución; consulta el estado');
    return receipt;
  },
  async list(offset = 0, view: 'pending' | 'resolved' = 'pending'): Promise<{ items: TerminalDispatch[]; next_offset: number | null }> {
    const task = capturePrivateTask();
    const data = record(await api.get<unknown>(`/notifications/terminal-dispatch/review?limit=20&offset=${offset}${view === 'resolved' ? '&view=resolved' : ''}`)); task.assertCurrent();
    if (!Array.isArray(data.items) || data.items.length > 20) throw new Error('Página de revisión no válida');
    const items = data.items.map(value => {
      const row = record(value);
      id(row.id); id(row.recipient_id); if (row.order_id !== null) id(row.order_id);
      if (row.payout_id !== undefined && row.payout_id !== null) id(row.payout_id);
      if (!['entrega_completada', 'entrega_fallida', 'orden_cancelada', 'nuevo_pedido_asignado', 'payout_solicitado', 'payout_aprobado', 'payout_rechazado'].includes(String(row.event)) || !['EMAIL', 'SMS', 'PUSH'].includes(String(row.channel)) || !['queued', 'uncertain', 'invalid', 'resolved'].includes(String(row.state))) throw new Error('Estado de revisión no válido');
      if ((view === 'resolved') !== (row.state === 'resolved')) throw new Error('La respuesta no corresponde a esta vista');
      if (row.delivery_id !== undefined && row.delivery_id !== null) id(row.delivery_id);
      if (row.revision !== undefined && row.revision !== null && (typeof row.revision !== 'string' || !/^[a-f0-9]{64}$/.test(row.revision))) throw new Error('Revisión técnica no válida');
      if (row.diagnostic !== undefined && row.diagnostic !== null && !['policy_or_state','unverifiable_record'].includes(String(row.diagnostic))) throw new Error('Diagnóstico no válido');
      if (row.state === 'resolved') readResolution(row.resolution, String(row.id));
      if (row.attempt_id !== null) id(row.attempt_id);
      if (row.state === 'uncertain' && row.attempt_id === null) throw new Error('Intento ausente');
      for (const key of ['created_at', 'destination_hint']) if (row[key] !== null && typeof row[key] !== 'string') throw new Error('Detalle de revisión no válido');
      for (const key of ['order_code', 'attempt_started_at']) if (row[key] !== undefined && row[key] !== null && typeof row[key] !== 'string') throw new Error('Referencia de revisión no válida');
      return row as TerminalDispatch;
    });
    if (new Set(items.map(row => row.id)).size !== items.length) throw new Error('Avisos duplicados en la consulta');
    const next = data.next_offset;
    if (next !== null && (typeof next !== 'number' || !Number.isSafeInteger(next) || next <= offset || next > 10000 || !items.length)) throw new Error('Paginación de revisión no válida');
    return { items, next_offset: next as number | null };
  },
  async review(notificationId: string, body: DispatchReview): Promise<{ state: 'accepted' | 'uncertain' }> {
    id(notificationId); id(body.review_id); id(body.attempt_id);
    const task = capturePrivateTask();
    const result = record(await api.post<unknown>(`/notifications/terminal-dispatch/${notificationId}/review`, body)); task.assertCurrent();
    if (result.id !== notificationId || result.review_id !== body.review_id || result.decision !== body.decision || !['accepted', 'uncertain'].includes(String(result.state))) throw new Error('La respuesta no confirma esta revisión; consulta el estado');
    return { state: result.state as 'accepted' | 'uncertain' };
  },
};
