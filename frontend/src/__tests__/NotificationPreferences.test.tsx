import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/notifications/preferences/page';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
import { toast } from '@/lib/feedback';
import {
  notificationPreferences,
  editablePreferenceChannels,
  preferenceEvents,
  Preference,
} from '@/services/notification-preferences.service';

let mockUser: { id: string; role: string } | null = { id: 'owner', role: 'GERENTE' };
jest.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ user: mockUser, sessionRevision: 1 }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));
jest.mock('@/lib/feedback', () => ({ toast: { success: jest.fn() } }));
const get = jest.mocked(api.get),
  put = jest.mocked(api.put);
let mockPreferences: Preference[];
let mockTemplates: unknown[];
const target = { event_code: 'payout_aprobado', channel: 'EMAIL', enabled: true } as Preference;
const checkbox = () =>
  screen.getByRole('checkbox', { name: 'Retiro aprobado contablemente: Correo' });
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (v: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  jest.resetAllMocks();
  mockUser = { id: 'owner', role: 'GERENTE' };
  storeTokens({ access_token: 'prefs-a', refresh_token: 'refresh-a' });
  mockPreferences = [
    { ...target, enabled: false },
    { event_code: 'payout_aprobado', channel: 'IN_APP', enabled: false },
  ];
  mockTemplates = [
    { code: 'payout_aprobado', channel: 'EMAIL', is_active: true },
    { code: 'orden_cancelada', channel: 'SMS', is_active: false },
  ];
  get.mockImplementation(async (url) =>
    url === '/notifications/preferences'
      ? { preferences: mockPreferences }
      : { templates: mockTemplates },
  );
  put.mockImplementation(async (_url, body) => {
    const changes = (body as { preferences: Preference[] }).preferences;
    for (const row of changes)
      mockPreferences = [
        ...mockPreferences.filter(
          (p) => p.event_code !== row.event_code || p.channel !== row.channel,
        ),
        { ...row },
      ];
    return { status: 'ok', updated: changes.length };
  });
});
afterEach(() => {
  clearStoredTokens();
  delete process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS;
});
async function mount() {
  const view = render(<Page />);
  await screen.findByRole('checkbox', { name: 'Retiro aprobado contablemente: Correo' });
  return view;
}

it('consults both authenticated endpoints and does not invent a saved time or rewrite internal rows', async () => {
  await mount();
  expect(checkbox()).not.toBeChecked();
  expect(screen.getByText(/comprobantes internos se conservan/)).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: /Bandeja interna/ })).not.toBeInTheDocument();
  expect(put).not.toHaveBeenCalled();
  expect(screen.getAllByText('Plantilla pausada').length).toBeGreaterThan(0);
  expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled();
});
it.each(['SUPERADMIN', 'GERENTE', 'OPERADOR', 'AUDITOR', 'REPARTIDOR', 'CLIENTE'])(
  'mirrors server permissions for %s, ignoring the obsolete user storage key',
  async (role) => {
    mockUser = { id: 'owner', role };
    localStorage.setItem('user', JSON.stringify({ role: 'SUPERADMIN' }));
    await mount();
    const card = screen.getByRole('article', { name: 'Retiro aprobado contablemente' });
    for (const [channel, label] of [
      ['EMAIL', 'Correo'],
      ['SMS', 'SMS'],
      ['PUSH', 'Notificación push'],
    ]) {
      const input = within(card).getByRole('checkbox', {
        name: 'Retiro aprobado contablemente: ' + label,
      });
      expect(input.hasAttribute('disabled')).toBe(
        !editablePreferenceChannels(role).includes(channel as Preference['channel']),
      );
    }
  },
);
it.each(['disabled', 'anonymous'])('does not load private preferences when %s', (fault) => {
  if (fault === 'disabled') process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS = 'false';
  else mockUser = null;
  render(<Page />);
  expect(get).not.toHaveBeenCalled();
});
it('locks editing when catalog loading fails instead of silently saving fallback defaults', async () => {
  get.mockImplementation(async (url) => {
    if (url === '/notifications/templates') throw new Error('PRIVATE_TEMPLATE_SECRET');
    return { preferences: mockPreferences };
  });
  render(<Page />);
  await screen.findByRole('dialog', { name: 'No se pudieron consultar las preferencias' });
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(put).not.toHaveBeenCalled();
  expect(screen.queryByText(/PRIVATE_TEMPLATE_SECRET/)).not.toBeInTheDocument();
});
it('sends only changed external cells and preserves legacy internal and forbidden preferences', async () => {
  mockUser = { id: 'owner', role: 'CLIENTE' };
  mockPreferences.push({ event_code: 'payout_aprobado', channel: 'PUSH', enabled: false });
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith('Preferencias guardadas y verificadas'),
  );
  expect(put).toHaveBeenCalledTimes(1);
  expect(put).toHaveBeenCalledWith('/notifications/preferences', { preferences: [target] });
  expect(mockPreferences).toContainEqual({
    event_code: 'payout_aprobado',
    channel: 'PUSH',
    enabled: false,
  });
  expect(mockPreferences).toContainEqual({
    event_code: 'payout_aprobado',
    channel: 'IN_APP',
    enabled: false,
  });
});
it('removes a reverted checkbox from the delta without a PUT', async () => {
  await mount();
  fireEvent.click(checkbox());
  expect(screen.getByText('1 cambio sin guardar')).toBeInTheDocument();
  fireEvent.click(checkbox());
  expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled();
  expect(put).not.toHaveBeenCalled();
});
it('blocks double saves and waits for a verified read before reporting success', async () => {
  const request = deferred<unknown>();
  put.mockReturnValue(request.promise);
  await mount();
  fireEvent.click(checkbox());
  const save = screen.getByRole('button', { name: 'Guardar cambios' });
  fireEvent.click(save);
  fireEvent.click(save);
  expect(put).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
  mockPreferences = [target];
  await act(async () => request.resolve({ status: 'ok', updated: 1 }));
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith('Preferencias guardadas y verificadas'),
  );
});
it('recovers a committed save whose reply was lost without repeating PUT', async () => {
  put.mockImplementation(async () => {
    mockPreferences = [target];
    throw new Error('PRIVATE_DATABASE_DETAIL');
  });
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  await screen.findByRole('dialog', { name: 'No se pudo confirmar el guardado' });
  expect(toast.success).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Estado actual verificado'));
  expect(put).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled();
  expect(screen.queryByText(/PRIVATE_DATABASE_DETAIL/)).not.toBeInTheDocument();
});
it.each(['confirmed', 'uncertain'])(
  'preserves the %s outcome through repeated failed recovery reads',
  async (mode) => {
    await mount();
    fireEvent.click(checkbox());
    if (mode === 'uncertain') put.mockRejectedValue(new Error('lost'));
    else put.mockResolvedValue({ status: 'ok', updated: 1 });
    get.mockRejectedValue(new Error('read failed'));
    fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    const title =
      mode === 'confirmed'
        ? 'Guardado confirmado; consulta pendiente'
        : 'No se pudo confirmar el guardado';
    await screen.findByRole('dialog', { name: title });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Consultar de nuevo' })).toBeEnabled(),
    );
    expect(screen.getByRole('dialog', { name: title })).toBeInTheDocument();
    expect(put).toHaveBeenCalledTimes(1);
  },
);
it('preserves a conflicting draft for review and never silently resends it', async () => {
  put.mockRejectedValue(new Error('unknown'));
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
  await screen.findByRole('dialog', { name: 'Revisa las preferencias actuales' });
  expect(screen.getByText(/borrador permitido; actual bloqueado/)).toBeInTheDocument();
  expect(put).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Revisar borrador' }));
  expect(checkbox()).toBeChecked();
  expect(screen.getByText(/Cambio pendiente · actual: bloqueado/)).toBeInTheDocument();
  expect(put).toHaveBeenCalledTimes(1);
});
it('can adopt current server values after reviewing an uncertain save', async () => {
  put.mockRejectedValue(new Error('unknown'));
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: 'Consultar de nuevo' }));
  await screen.findByRole('dialog', { name: 'Revisa las preferencias actuales' });
  fireEvent.click(screen.getByRole('button', { name: 'Usar valores actuales' }));
  expect(checkbox()).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled();
  expect(put).toHaveBeenCalledTimes(1);
});
it('requires an explicit decision before a refresh discards unsent edits', async () => {
  await mount();
  fireEvent.click(checkbox());
  const before = get.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado' }));
  await screen.findByRole('dialog', { name: 'Revisar cambios sin guardar' });
  expect(get).toHaveBeenCalledTimes(before);
  fireEvent.click(screen.getByRole('button', { name: 'Conservar borrador' }));
  expect(checkbox()).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Descartar borrador' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Descartar borrador' }),
  );
  expect(checkbox()).not.toBeChecked();
  expect(get).toHaveBeenCalledTimes(before);
  expect(put).not.toHaveBeenCalled();
});
it('retains a draft and the last consultation when a discard-and-reload query fails', async () => {
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Consultar estado' }));
  get.mockRejectedValue(new Error('read failed'));
  fireEvent.click(screen.getByRole('button', { name: 'Descartar y consultar' }));
  await screen.findByRole('dialog', { name: 'No se pudieron consultar las preferencias' });
  fireEvent.click(screen.getByRole('button', { name: 'Volver' }));
  expect(checkbox()).toBeChecked();
  expect(checkbox()).toBeDisabled();
  expect(put).not.toHaveBeenCalled();
});
it('blocks an old selection when raw storage changes before React observes it', async () => {
  await mount();
  fireEvent.click(checkbox());
  mockPreferences = [];
  localStorage.setItem('access_token', 'raw-next');
  localStorage.setItem('refresh_token', 'raw-next-refresh');
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled(),
  );
  expect(put).not.toHaveBeenCalled();
  expect(toast.success).not.toHaveBeenCalled();
});
it('drops a late save result and its feedback after changing credentials', async () => {
  const request = deferred<unknown>();
  put.mockReturnValue(request.promise);
  await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  mockPreferences = [];
  await act(async () => storeTokens({ access_token: 'prefs-b', refresh_token: 'refresh-b' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Guardar cambios' })).toBeDisabled(),
  );
  await act(async () => request.resolve({ status: 'ok', updated: 1 }));
  expect(toast.success).not.toHaveBeenCalled();
});
it('does not publish delayed save feedback after unmount', async () => {
  const request = deferred<unknown>();
  put.mockReturnValue(request.promise);
  const view = await mount();
  fireEvent.click(checkbox());
  fireEvent.click(screen.getByRole('button', { name: 'Guardar cambios' }));
  view.unmount();
  await act(async () => request.resolve({ status: 'ok', updated: 1 }));
  expect(toast.success).not.toHaveBeenCalled();
});
it('supports legacy event names safely, including prototype-like strings', async () => {
  mockPreferences.push({ event_code: '__proto__', channel: 'EMAIL', enabled: false });
  await mount();
  expect(screen.getByRole('article', { name: '__proto__' })).toBeInTheDocument();
  const data = await notificationPreferences.snapshot();
  expect(preferenceEvents(data)).toContain('__proto__');
});
it.each([
  'preferences',
  'catalog',
  'boolean',
  'code',
  'channel',
  'duplicate_preference',
  'duplicate_template',
  'active',
])('rejects malformed %s instead of inventing defaults', async (fault) => {
  let prefs: any = { preferences: mockPreferences },
    catalog: any = { templates: mockTemplates };
  if (fault === 'preferences') prefs = {};
  if (fault === 'catalog') catalog = {};
  if (fault === 'boolean') prefs.preferences[0].enabled = 'false';
  if (fault === 'code') prefs.preferences[0].event_code = '';
  if (fault === 'channel') prefs.preferences[0].channel = 'OTHER';
  if (fault === 'duplicate_preference') prefs.preferences.push(prefs.preferences[0]);
  if (fault === 'duplicate_template') catalog.templates.push(catalog.templates[0]);
  if (fault === 'active') catalog.templates[0].is_active = 'true';
  get.mockImplementation(async (url) => (url === '/notifications/preferences' ? prefs : catalog));
  await expect(notificationPreferences.snapshot()).rejects.toThrow();
});
it('projects only preference and catalog DTO fields', async () => {
  get.mockImplementation(async (url) =>
    url === '/notifications/preferences'
      ? { preferences: [{ ...target, private: 'PRIVATE_VALUE' }] }
      : {
          templates: [
            {
              code: 'payout_aprobado',
              channel: 'EMAIL',
              is_active: true,
              body_template: 'PRIVATE_TEMPLATE',
            },
          ],
        },
  );
  const data = await notificationPreferences.snapshot();
  expect(JSON.stringify(data)).not.toContain('PRIVATE_');
});
it.each([
  { status: 'ok', updated: 0 },
  { status: 'ok', updated: '1' },
  { status: 'pending', updated: 1 },
  {},
])('rejects a contradictory save receipt %j', async (receipt) => {
  put.mockResolvedValue(receipt);
  await expect(notificationPreferences.save([target], 'GERENTE')).rejects.toThrow();
});
it.each([
  ['CLIENTE', 'PUSH'],
  ['REPARTIDOR', 'EMAIL'],
  ['GERENTE', 'IN_APP'],
  ['UNKNOWN', 'EMAIL'],
])('does not send a forbidden %s/%s change', async (role, channel) => {
  await expect(
    notificationPreferences.save([{ ...target, channel: channel as Preference['channel'] }], role),
  ).rejects.toThrow();
  expect(put).not.toHaveBeenCalled();
});
it.each(['empty', 'duplicate', 'boolean'])('does not send an invalid %s batch', async (fault) => {
  const rows: any =
    fault === 'empty'
      ? []
      : fault === 'duplicate'
        ? [target, target]
        : [{ ...target, enabled: 'false' }];
  await expect(notificationPreferences.save(rows, 'GERENTE')).rejects.toThrow();
  expect(put).not.toHaveBeenCalled();
});

it('honors the server code-point length for Unicode event codes', async () => {
  const name = '🔔'.repeat(40);
  mockPreferences = [{ event_code: name, channel: 'EMAIL', enabled: false }];
  const data = await notificationPreferences.snapshot();
  expect(data.preferences[0].event_code).toBe(name);
  await notificationPreferences.save(
    [{ event_code: name, channel: 'EMAIL', enabled: true }],
    'GERENTE',
  );
  expect(put).toHaveBeenCalledTimes(1);
});
