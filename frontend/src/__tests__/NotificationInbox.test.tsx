import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/notifications/page';
import { notificationInbox, InboxRow } from '@/services/notification-inbox.service';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens, getCredentialGeneration } from '@/lib/auth-session';
import {
  notificationInboxChanged,
  onNotificationInboxChanged,
} from '@/lib/notification-inbox-events';
import { toast } from '@/lib/feedback';

let mockUser: { id: string; role: string } | null = { id: 'owner', role: 'GERENTE' };
jest.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ user: mockUser, sessionRevision: 1 }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/feedback', () => ({ toast: { success: jest.fn() } }));
jest.mock('@/components/notifications/NotificationProviderDiagnosticsPanel', () => ({
  NotificationProviderDiagnosticsPanel: () => null,
}));
jest.mock('@/components/notifications/TerminalDispatchReviewPanel', () => ({
  TerminalDispatchReviewPanel: () => null,
}));
const get = jest.mocked(api.get),
  patch = jest.mocked(api.patch),
  remove = jest.mocked(api.delete);
const id = '123e4567-e89b-42d3-a456-000000000801';
function row(extra: Partial<InboxRow> = {}): InboxRow {
  return {
    id,
    title: 'Aviso de prueba',
    body: 'Contenido privado del dueño',
    channel: 'IN_APP',
    status: 'PENDIENTE',
    template_code: null,
    created_at: '2026-11-27T12:00:00+00:00',
    read_at: null,
    ...extra,
  };
}
function page(items = [row()], number = 1, total = items.length) {
  return { items, page: number, size: 10, total, pages: Math.ceil(total / 10), unread_count: 1 };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  jest.resetAllMocks();
  mockUser = { id: 'owner', role: 'GERENTE' };
  storeTokens({ access_token: 'inbox-a', refresh_token: 'refresh-a' });
  get.mockResolvedValue(page());
  patch.mockResolvedValue({ status: 'ok', id });
  remove.mockResolvedValue({ status: 'deleted' });
});
afterEach(() => {
  clearStoredTokens();
  delete process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS;
});
async function mount() {
  const result = render(<Page />);
  await screen.findByRole('article', { name: 'Aviso de prueba' });
  return result;
}

it('uses the canonical private client and labels the scope of counts and filters', async () => {
  await mount();
  expect(get).toHaveBeenCalledWith('/notifications/inbox?page=1&size=10&include_all_channels=true');
  expect(screen.getByText(/solo a avisos internos/)).toBeInTheDocument();
  expect(screen.getByText(/Caracas/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filtrar por canal'), { target: { value: 'EMAIL' } });
  expect(screen.getByText('No hay avisos que coincidan en esta página.')).toBeInTheDocument();
  expect(screen.queryByText('Tu bandeja está vacía.')).not.toBeInTheDocument();
});
it.each(['disabled', 'anonymous'])('does not mount private loads when %s', (fault) => {
  if (fault === 'disabled') process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS = 'false';
  else mockUser = null;
  render(<Page />);
  expect(get).not.toHaveBeenCalled();
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
it('distinguishes a failed initial query from a confirmed empty inbox', async () => {
  get.mockRejectedValueOnce(new Error('PRIVATE_PASSWORD')).mockResolvedValue(page([], 1, 0));
  render(<Page />);
  const modal = await screen.findByRole('dialog', { name: 'No se pudo cargar la bandeja' });
  expect(modal).toHaveTextContent('Esto no significa que tu bandeja esté vacía');
  expect(screen.queryByText(/PRIVATE_PASSWORD/)).not.toBeInTheDocument();
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  expect(await screen.findByText('Tu bandeja está vacía.')).toBeInTheDocument();
  expect(screen.getByText(/Página 1 de 1/)).toBeInTheDocument();
  expect(toast.success).toHaveBeenCalledWith('Bandeja actualizada');
});
it('preserves the last page and disables actions when refresh fails', async () => {
  const view = await mount();
  get.mockRejectedValue(new Error('PRIVATE_DETAIL'));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar bandeja' }));
  await screen.findByRole('dialog');
  expect(view.container.querySelectorAll('article')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Volver' }));
  expect(screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Eliminar: Aviso de prueba' })).toBeDisabled();
  expect(screen.queryByText(/PRIVATE_DETAIL/)).not.toBeInTheDocument();
});
it('does not change the confirmed page index when next-page loading fails', async () => {
  get.mockResolvedValueOnce(page([row()], 1, 11)).mockRejectedValue(new Error('unavailable'));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: 'Volver' }));
  expect(screen.getByText(/Página 1 de 2/)).toBeInTheDocument();
  expect(get).toHaveBeenLastCalledWith(
    '/notifications/inbox?page=2&size=10&include_all_channels=true',
  );
});
it('only updates read status after the matching acknowledgement and prevents double clicks', async () => {
  const response = deferred<unknown>();
  patch.mockReturnValue(response.promise);
  await mount();
  const button = screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(patch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('article')).toHaveTextContent('PENDIENTE');
  expect(toast.success).not.toHaveBeenCalled();
  get.mockResolvedValue(page([row({ status: 'LEIDO' })]));
  await act(async () => response.resolve({ status: 'ok', id }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: /Marcar leído:/ })).not.toBeInTheDocument(),
  );
  expect(toast.success).toHaveBeenCalledWith('Notificación marcada como leída');
});
it('requires a centered confirmation before deleting and allows canceling', async () => {
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Eliminar: Aviso de prueba' }));
  const modal = screen.getByRole('dialog', { name: 'Eliminar notificación' });
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(within(modal).getByRole('button', { name: 'Volver' }));
  expect(remove).not.toHaveBeenCalled();
  expect(screen.getByRole('article')).toBeInTheDocument();
});
it('recovers a lost delete response by GET without repeating DELETE', async () => {
  remove.mockRejectedValue(new Error('PRIVATE_SERVER_DATA'));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Eliminar: Aviso de prueba' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar eliminación' }));
  const modal = await screen.findByRole('dialog', { name: 'No se pudo confirmar la acción' });
  expect(modal).toHaveTextContent('podría haberse aplicado');
  expect(toast.success).not.toHaveBeenCalled();
  get.mockResolvedValue(page([], 1, 0));
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await screen.findByText('Tu bandeja está vacía.');
  expect(remove).toHaveBeenCalledTimes(1);
  expect(patch).not.toHaveBeenCalled();
  expect(screen.queryByText(/PRIVATE_SERVER_DATA/)).not.toBeInTheDocument();
});
it('keeps a confirmed write separate from a failed follow-up query', async () => {
  await mount();
  get.mockRejectedValue(new Error('query unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' }));
  await screen.findByRole('dialog', { name: 'Acción confirmada; consulta pendiente' });
  expect(patch).toHaveBeenCalledTimes(1);
  expect(toast.success).toHaveBeenCalledWith('Notificación marcada como leída');
  get.mockResolvedValue(page([row({ status: 'LEIDO' })]));
  fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(patch).toHaveBeenCalledTimes(1);
});
it('moves to the previous valid page after deleting the last item', async () => {
  get.mockResolvedValueOnce(page([row()], 1, 11)).mockResolvedValueOnce(page([row()], 2, 11));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByText(/Página 2 de 2/);
  get
    .mockResolvedValueOnce(page([], 2, 10))
    .mockResolvedValueOnce(page([row({ title: 'Aviso anterior' })], 1, 10));
  fireEvent.click(screen.getByRole('button', { name: 'Eliminar: Aviso de prueba' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirmar eliminación' }));
  await screen.findByRole('article', { name: 'Aviso anterior' });
  expect(screen.getByText(/Página 1 de 1/)).toBeInTheDocument();
  expect(remove).toHaveBeenCalledTimes(1);
});
it.each([
  'entrega_completada',
  'entrega_fallida',
  'orden_cancelada',
  'nuevo_pedido_asignado',
  'payout_solicitado',
  'payout_aprobado',
  'payout_rechazado',
])('preserves the external history of %s', async (code) => {
  get.mockResolvedValue(page([row({ channel: 'EMAIL', template_code: code })]));
  await mount();
  expect(screen.getByText('Seguimiento externo')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Eliminar:/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Marcar leído:/ })).not.toBeInTheDocument();
  await expect(
    notificationInbox.act(row({ channel: 'SMS', template_code: code }), 'delete'),
  ).rejects.toThrow();
  expect(remove).not.toHaveBeenCalled();
});
it('discards a late page from the previous credentials and clears its text', async () => {
  const old = deferred<unknown>();
  get.mockReturnValueOnce(old.promise);
  render(<Page />);
  get.mockResolvedValue(page([row({ title: 'Sesión nueva', body: 'Datos nuevos' })]));
  await act(async () => storeTokens({ access_token: 'inbox-b', refresh_token: 'refresh-b' }));
  await screen.findByRole('article', { name: 'Sesión nueva' });
  await act(async () => old.resolve(page([row({ title: 'Sesión anterior' })])));
  expect(screen.queryByText('Sesión anterior')).not.toBeInTheDocument();
  expect(screen.getByRole('article', { name: 'Sesión nueva' })).toBeInTheDocument();
});
it('does not publish success or repaint old content after session changes during a write', async () => {
  const response = deferred<unknown>();
  patch.mockReturnValue(response.promise);
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' }));
  get.mockResolvedValue(page([], 1, 0));
  await act(async () => storeTokens({ access_token: 'other', refresh_token: 'other-refresh' }));
  await screen.findByText('Tu bandeja está vacía.');
  await act(async () => response.resolve({ status: 'ok', id }));
  expect(toast.success).not.toHaveBeenCalled();
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
it('clears rows on unmount without publishing delayed feedback', async () => {
  const response = deferred<unknown>();
  patch.mockReturnValue(response.promise);
  const view = await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' }));
  view.unmount();
  await act(async () => response.resolve({ status: 'ok', id }));
  expect(toast.success).not.toHaveBeenCalled();
});
it.each([
  'page',
  'size',
  'total',
  'pages',
  'unread',
  'items',
  'duplicate',
  'id',
  'channel',
  'status',
  'date',
  'text',
])('rejects malformed %s data instead of showing an empty inbox', async (fault) => {
  const data: any = page();
  if (fault === 'page') data.page = 2;
  if (fault === 'size') data.size = 50;
  if (fault === 'total') data.total = '1';
  if (fault === 'pages') data.pages = 0;
  if (fault === 'unread') data.unread_count = -1;
  if (fault === 'items') data.items = {};
  if (fault === 'duplicate') data.items.push(data.items[0]);
  if (fault === 'id') data.items[0].id = 'invalid';
  if (fault === 'channel') data.items[0].channel = 'OTHER';
  if (fault === 'status') data.items[0].status = 'UNKNOWN';
  if (fault === 'date') data.items[0].created_at = 'bad';
  if (fault === 'text') data.items[0].body = { password: 'private' };
  get.mockResolvedValue(data);
  await expect(notificationInbox.page()).rejects.toThrow();
});
it('strips unlisted server fields from the public row', async () => {
  get.mockResolvedValue(page([{ ...row(), device_token: 'PRIVATE_DEVICE' } as InboxRow]));
  const data = await notificationInbox.page();
  expect(JSON.stringify(data)).not.toContain('PRIVATE_DEVICE');
});
it.each([{ status: 'ok', id: '123e4567-e89b-42d3-a456-000000000999' }, { status: 'deleted' }, {}])(
  'does not accept a contradictory read receipt %j',
  async (receipt) => {
    patch.mockResolvedValue(receipt);
    await expect(notificationInbox.act(row(), 'read')).rejects.toThrow();
  },
);
it('invalidates subscribers only after a confirmed current-session write', async () => {
  const listener = jest.fn();
  const off = onNotificationInboxChanged(listener);
  try {
    await notificationInbox.act(row(), 'read');
    expect(listener).toHaveBeenCalledWith(getCredentialGeneration());
    remove.mockResolvedValue({ status: 'ok' });
    await expect(notificationInbox.act(row(), 'delete')).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
  } finally {
    off();
  }
  notificationInboxChanged(getCredentialGeneration());
  expect(listener).toHaveBeenCalledTimes(1);
});

it.each(['confirmed', 'uncertain'])(
  'preserves a %s write outcome across repeated failed recovery reads',
  async (mode) => {
    await mount();
    if (mode === 'uncertain') patch.mockRejectedValue(new Error('lost acknowledgement'));
    get.mockRejectedValue(new Error('unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Marcar leído: Aviso de prueba' }));
    const title =
      mode === 'confirmed'
        ? 'Acción confirmada; consulta pendiente'
        : 'No se pudo confirmar la acción';
    await screen.findByRole('dialog', { name: title });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3 - (mode === 'uncertain' ? 1 : 0)));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Consultar de nuevo' })).toBeEnabled(),
    );
    expect(screen.getByRole('dialog', { name: title })).toBeInTheDocument();
    expect(patch).toHaveBeenCalledTimes(1);
  },
);

it('bounds correction when concurrent deletion shrinks two successive pages', async () => {
  get.mockResolvedValueOnce(page([row()], 1, 21)).mockResolvedValueOnce(page([row()], 2, 21));
  await mount();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByText(/Página 2 de 3/);
  get.mockResolvedValueOnce(page([], 3, 11)).mockResolvedValueOnce(page([], 2, 1));
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByRole('dialog', { name: 'No se pudo cargar la bandeja' });
  expect(get).toHaveBeenCalledTimes(4);
  fireEvent.click(screen.getByRole('button', { name: 'Volver' }));
  expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument();
});

it.each(['read', 'delete'])(
  'does not submit an old %s selection when raw storage changes before React observes the session',
  async (action) => {
    await mount();
    if (action === 'delete')
      fireEvent.click(screen.getByRole('button', { name: 'Eliminar: Aviso de prueba' }));
    get.mockResolvedValue(page([], 1, 0));
    localStorage.setItem('access_token', 'raw-new-owner');
    localStorage.setItem('refresh_token', 'raw-new-refresh');
    fireEvent.click(
      screen.getByRole('button', {
        name: action === 'read' ? 'Marcar leído: Aviso de prueba' : 'Confirmar eliminación',
      }),
    );
    await screen.findByText('Tu bandeja está vacía.');
    expect(patch).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  },
);
