import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
export type TerminalDispatch = {
  id: string; event: 'entrega_completada' | 'entrega_fallida' | 'orden_cancelada' | 'nuevo_pedido_asignado' | 'payout_solicitado' | 'payout_aprobado' | 'payout_rechazado';
  channel: 'PUSH' | 'SMS' | 'EMAIL'; recipient_id: string; order_id: string | null;
  payout_id?: string | null; state: 'queued' | 'uncertain' | 'invalid'; attempt_id: string | null;
  created_at: string | null; destination_hint: string | null; order_code?: string | null; attempt_started_at?: string | null;
};
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
export const terminalNotifications = {
  async list(offset = 0): Promise<{ items: TerminalDispatch[]; next_offset: number | null }> {
    const task = capturePrivateTask();
    const data = record(await api.get<unknown>(`/notifications/terminal-dispatch/review?limit=20&offset=${offset}`)); task.assertCurrent();
    if (!Array.isArray(data.items) || data.items.length > 20) throw new Error('Página de revisión no válida');
    const items = data.items.map(value => {
      const row = record(value);
      id(row.id); id(row.recipient_id); if (row.order_id !== null) id(row.order_id);
      if (row.payout_id !== undefined && row.payout_id !== null) id(row.payout_id);
      if (!['entrega_completada', 'entrega_fallida', 'orden_cancelada', 'nuevo_pedido_asignado', 'payout_solicitado', 'payout_aprobado', 'payout_rechazado'].includes(String(row.event)) || !['EMAIL', 'SMS', 'PUSH'].includes(String(row.channel)) || !['queued', 'uncertain', 'invalid'].includes(String(row.state))) throw new Error('Estado de revisión no válido');
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
