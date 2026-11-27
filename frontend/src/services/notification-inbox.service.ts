import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';
import { notificationInboxChanged } from '@/lib/notification-inbox-events';
import { isTerminalExternal } from '@/services/terminal-notifications.service';

export const INBOX_CHANNELS = ['IN_APP', 'PUSH', 'EMAIL', 'SMS'] as const;
export const INBOX_STATUSES = ['PENDIENTE', 'ENVIADO', 'ENTREGADO', 'FALLIDO', 'LEIDO'] as const;
export type InboxRow = {
  id: string;
  template_code: string | null;
  channel: (typeof INBOX_CHANNELS)[number];
  status: (typeof INBOX_STATUSES)[number];
  title: string | null;
  body: string | null;
  created_at: string | null;
  read_at: string | null;
};
export type InboxPage = {
  items: InboxRow[];
  page: number;
  size: number;
  total: number;
  pages: number;
  unread_count: number;
};
const uuid = (value: unknown): value is string =>
  typeof value === 'string' &&
  /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Respuesta de bandeja no válida');
  return value as Record<string, unknown>;
}
function date(value: unknown): boolean {
  return (
    value === null ||
    (typeof value === 'string' &&
      /^\d{4}-\d{2}-\d{2}T/.test(value) &&
      Number.isFinite(Date.parse(value)))
  );
}
function readRow(value: unknown): InboxRow {
  const row = object(value);
  if (
    !uuid(row.id) ||
    !INBOX_CHANNELS.includes(row.channel as InboxRow['channel']) ||
    !INBOX_STATUSES.includes(row.status as InboxRow['status'])
  )
    throw new Error('Aviso de bandeja no válido');
  for (const name of ['template_code', 'title', 'body'])
    if (row[name] !== null && typeof row[name] !== 'string')
      throw new Error('Texto de bandeja no válido');
  if (!date(row.created_at) || !date(row.read_at)) throw new Error('Fecha de bandeja no válida');
  return {
    id: row.id,
    template_code: row.template_code as string | null,
    channel: row.channel as InboxRow['channel'],
    status: row.status as InboxRow['status'],
    title: row.title as string | null,
    body: row.body as string | null,
    created_at: row.created_at as string | null,
    read_at: row.read_at as string | null,
  };
}
export const notificationInbox = {
  async page(page = 1): Promise<InboxPage> {
    if (!Number.isSafeInteger(page) || page < 1) throw new Error('Página no válida');
    const task = capturePrivateTask();
    const data = object(
      await api.get<unknown>(`/notifications/inbox?page=${page}&size=10&include_all_channels=true`),
    );
    task.assertCurrent();
    if (
      data.page !== page ||
      data.size !== 10 ||
      !count(data.total) ||
      !count(data.pages) ||
      data.pages !== Math.ceil(data.total / 10) ||
      !count(data.unread_count) ||
      !Array.isArray(data.items) ||
      data.items.length > 10
    )
      throw new Error('Página de bandeja no válida');
    const items = data.items.map(readRow);
    if (new Set(items.map((row) => row.id)).size !== items.length)
      throw new Error('Avisos duplicados');
    return {
      items,
      page,
      size: 10,
      total: data.total,
      pages: data.pages,
      unread_count: data.unread_count,
    };
  },
  async act(row: InboxRow, action: 'read' | 'delete'): Promise<void> {
    if (!uuid(row.id) || isTerminalExternal(row) || !['read', 'delete'].includes(action))
      throw new Error('Este aviso no admite esa acción');
    const task = capturePrivateTask();
    const data = object(
      action === 'read'
        ? await api.patch<unknown>(`/notifications/${row.id}/read`)
        : await api.delete<unknown>(`/notifications/${row.id}`),
    );
    task.assertCurrent();
    if (action === 'read' ? data.status !== 'ok' || data.id !== row.id : data.status !== 'deleted')
      throw new Error('La respuesta no confirma la acción');
    notificationInboxChanged(task.generation);
  },
};
