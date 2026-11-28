import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/rider/profile/page';
import { api } from '@/lib/api';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
import { toast } from '@/lib/feedback';
import { readSelfProfile, riderSelf, profileDraft } from '@/services/rider-self.service';
const owner = '123e4567-e89b-42d3-a456-426614174000',
  rider = '123e4567-e89b-42d3-a456-426614174001',
  vehicle = '123e4567-e89b-42d3-a456-426614174002';
const revision = 'a'.repeat(64),
  nextRevision = 'b'.repeat(64);
let mockUser: { id: string; role: string; vehicle_plate?: string } | null;
jest.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ user: mockUser, sessionRevision: 1 }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));
jest.mock('@/lib/feedback', () => ({ toast: { success: jest.fn() } }));
const get = jest.mocked(api.get),
  put = jest.mocked(api.put);
const original = {
  id: rider,
  user_id: owner,
  status: 'ACTIVO',
  is_online: true,
  first_name: 'Ana',
  last_name: 'Pérez',
  email: 'ana@example.test',
  phone: '+584121234567',
  vehicle_type: 'MOTO',
  vehicle_plate: 'API-123',
  vehicle_ownership_type: 'PROPIO',
  assigned_vehicle_id: null,
  profile_revision: revision,
  assignment_revision: revision,
};
let row: Record<string, unknown>;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
const save = () => screen.getByRole('button', { name: 'Guardar cambios' });
const name = () => screen.getByLabelText('Nombre');
function change(value = 'Nueva') {
  fireEvent.change(name(), { target: { value } });
}
async function mount() {
  const view = render(<Page />);
  await screen.findByDisplayValue('API-123');
  await waitFor(() => expect(name()).toBeEnabled());
  return view;
}
beforeEach(() => {
  jest.resetAllMocks();
  mockUser = { id: owner, role: 'REPARTIDOR', vehicle_plate: 'STORE-OLD' };
  storeTokens({ access_token: 'profile-a', refresh_token: 'refresh-a' });
  row = { ...original };
  get.mockImplementation(async () => row);
  put.mockImplementation(async (_url, body) => {
    const patch = { ...(body as Record<string, unknown>) };
    delete patch.expected_profile_revision;
    delete patch.expected_assignment_revision;
    row = { ...row, ...patch, profile_revision: nextRevision, assignment_revision: nextRevision };
    return row;
  });
});
afterEach(() => clearStoredTokens());
it('loads the API snapshot and preserves it when auth metadata refreshes without changing identity', async () => {
  const view = await mount();
  expect(save()).toBeDisabled();
  expect(screen.queryByDisplayValue('STORE-OLD')).not.toBeInTheDocument();
  change();
  mockUser = { id: owner, role: 'REPARTIDOR', vehicle_plate: 'NEW-STORE' };
  view.rerender(<Page />);
  expect(get).toHaveBeenCalledTimes(1);
  expect(name()).toHaveValue('Nueva');
  fireEvent.click(save());
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Perfil guardado y verificado'));
  expect(put).toHaveBeenCalledWith('/riders/me', {
    first_name: 'Nueva',
    expected_profile_revision: revision,
  });
});
it.each(['SUPERADMIN', 'GERENTE', 'OPERADOR', 'AUDITOR', 'CLIENTE', 'UNKNOWN', null])(
  'does not query a self profile for %s',
  async (role) => {
    mockUser = role ? { id: owner, role } : null;
    render(<Page />);
    expect(get).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
  },
);
it('shows a central load error and never uses stored identity as editable fallback', async () => {
  get.mockRejectedValueOnce(new Error('PRIVATE_INTERNAL_VALUE'));
  render(<Page />);
  const modal = await screen.findByRole('dialog', { name: 'No se pudo consultar el perfil' });
  expect(name()).toBeDisabled();
  expect(document.querySelector('button[type=submit]')).toBeDisabled();
  expect(screen.queryByText('PRIVATE_INTERNAL_VALUE')).not.toBeInTheDocument();
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await screen.findByDisplayValue('API-123');
  change();
  expect(save()).toBeEnabled();
});
it('sends only personal deltas with the loaded profile revision and double clicks cannot duplicate PUT', async () => {
  const gate = deferred<unknown>();
  put.mockReturnValueOnce(gate.promise);
  await mount();
  change();
  fireEvent.click(save());
  fireEvent.click(save());
  expect(put).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
  await act(async () => {
    row = { ...row, first_name: 'Nueva' };
    gate.resolve(row);
  });
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
});
it('removes a delta when toggled back to its loaded value', async () => {
  await mount();
  change();
  expect(save()).toBeEnabled();
  change('Ana');
  expect(save()).toBeDisabled();
  expect(put).not.toHaveBeenCalled();
});
it('requires explicit vehicle confirmation and preserves the assignment revision without sending unchanged personal fields', async () => {
  await mount();
  fireEvent.change(screen.getByLabelText('Placa'), { target: { value: 'NEW-132' } });
  fireEvent.click(save());
  const modal = await screen.findByRole('dialog', { name: 'Confirmar cambio de vehículo' });
  expect(put).not.toHaveBeenCalled();
  expect(within(modal).getByText(/deshabilita tu disponibilidad/)).toBeInTheDocument();
  fireEvent.click(within(modal).getByRole('button', { name: 'Confirmar cambio' }));
  await screen.findByRole('dialog', { name: 'Revisa la documentación del vehículo' });
  expect(put).toHaveBeenCalledWith('/riders/me', {
    vehicle_plate: 'NEW-132',
    expected_assignment_revision: revision,
  });
});
it('canceling vehicle confirmation preserves the draft without writing or redirecting', async () => {
  await mount();
  fireEvent.change(screen.getByLabelText('Tipo de vehículo'), { target: { value: 'PATINETA' } });
  fireEvent.click(save());
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Revisar borrador' }),
  );
  expect(put).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Tipo de vehículo')).toHaveValue('PATINETA');
});
it('company assignments stay read only while a personal update omits all fleet fields', async () => {
  row = {
    ...row,
    vehicle_ownership_type: 'EMPRESA',
    assigned_vehicle_id: vehicle,
    assigned_vehicle: { id: vehicle, revision, type: 'MOTO', plate: 'API-123' },
  };
  await mount();
  expect(screen.getByLabelText('Placa')).toBeDisabled();
  expect(screen.getByLabelText('Tipo de vehículo')).toBeDisabled();
  change();
  fireEvent.click(save());
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
  expect(put).toHaveBeenCalledWith('/riders/me', {
    first_name: 'Nueva',
    expected_profile_revision: revision,
  });
});
it('keeps an unfamiliar historical vehicle type and never replaces it during a personal save', async () => {
  row = { ...row, vehicle_type: 'HISTORICO' };
  await mount();
  expect(screen.getByLabelText('Tipo de vehículo')).toHaveValue('HISTORICO');
  change();
  fireEvent.click(save());
  await waitFor(() => expect(put).toHaveBeenCalled());
  expect(put).toHaveBeenCalledWith('/riders/me', {
    first_name: 'Nueva',
    expected_profile_revision: revision,
  });
});
it('recovers a committed PUT whose reply was lost by GET, without another PUT or premature success', async () => {
  put.mockImplementationOnce(async () => {
    row = { ...row, first_name: 'Nueva' };
    throw new Error('lost');
  });
  await mount();
  change();
  fireEvent.click(save());
  let modal = await screen.findByRole('dialog', { name: 'No se pudo confirmar el guardado' });
  expect(toast.success).not.toHaveBeenCalled();
  expect(name()).toBeDisabled();
  get.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() =>
    expect(within(modal).getByRole('button', { name: 'Consultar de nuevo' })).toBeEnabled(),
  );
  expect(modal).toHaveAccessibleName('No se pudo confirmar el guardado');
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Estado actual verificado'));
  expect(put).toHaveBeenCalledTimes(1);
  expect(save()).toBeDisabled();
});
it('retains confirmed outcome when repeated post-save reads fail and waits for verification before success', async () => {
  await mount();
  change();
  get.mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(save());
  const modal = await screen.findByRole('dialog', {
    name: 'Guardado confirmado; consulta pendiente',
  });
  expect(toast.success).not.toHaveBeenCalled();
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() =>
    expect(within(modal).getByRole('button', { name: 'Consultar de nuevo' })).toBeEnabled(),
  );
  expect(modal).toHaveAccessibleName('Guardado confirmado; consulta pendiente');
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Perfil guardado y verificado'));
  expect(put).toHaveBeenCalledTimes(1);
});
it('a 409 never refreshes and retries automatically; explicit recovery rebases only touched fields for review', async () => {
  put.mockRejectedValueOnce(Object.assign(new Error('conflict'), { status: 409 }));
  await mount();
  change();
  fireEvent.click(save());
  const modal = await screen.findByRole('dialog', { name: 'El perfil cambió' });
  expect(get).toHaveBeenCalledTimes(1);
  row = { ...row, first_name: 'Otra', phone: 'NEW-PHONE', profile_revision: nextRevision };
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  const review = await screen.findByRole('dialog', { name: 'Revisa el perfil actual' });
  expect(name()).toHaveValue('Nueva');
  expect(screen.getByLabelText('Teléfono / WhatsApp')).toHaveValue('NEW-PHONE');
  expect(put).toHaveBeenCalledTimes(1);
  fireEvent.click(within(review).getByRole('button', { name: 'Revisar borrador' }));
  fireEvent.click(save());
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
  expect(put).toHaveBeenLastCalledWith('/riders/me', {
    first_name: 'Nueva',
    expected_profile_revision: nextRevision,
  });
});
it('an incompatible successful receipt is uncertain; current values can be adopted without writing', async () => {
  put.mockResolvedValueOnce({ ...original, first_name: 'OTHER' });
  await mount();
  change();
  fireEvent.click(save());
  const modal = await screen.findByRole('dialog', { name: 'No se pudo confirmar el guardado' });
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  const review = await screen.findByRole('dialog', { name: 'Revisa el perfil actual' });
  fireEvent.click(within(review).getByRole('button', { name: 'Usar valores actuales' }));
  expect(name()).toHaveValue('Ana');
  expect(save()).toBeDisabled();
  expect(put).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
});
it('requires dirty reload confirmation and retains the draft read-only if that reload fails', async () => {
  await mount();
  change();
  fireEvent.click(screen.getByRole('button', { name: 'Recargar perfil' }));
  let modal = await screen.findByRole('dialog', { name: 'Revisar cambios sin guardar' });
  fireEvent.click(within(modal).getByRole('button', { name: 'Conservar borrador' }));
  expect(name()).toHaveValue('Nueva');
  expect(get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Recargar perfil' }));
  get.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Descartar y consultar' }),
  );
  await screen.findByRole('dialog', { name: 'No se pudo consultar el perfil' });
  expect(name()).toHaveValue('Nueva');
  expect(name()).toBeDisabled();
  expect(put).not.toHaveBeenCalled();
});
it('blocks an old draft before raw credential storage changes are observed by React', async () => {
  await mount();
  change();
  localStorage.setItem('access_token', 'raw-next-owner');
  localStorage.setItem('refresh_token', 'raw-next-refresh');
  fireEvent.click(save());
  expect(put).not.toHaveBeenCalled();
});
it('a late save after unmount never shows success or starts a recovery query', async () => {
  const gate = deferred<unknown>();
  put.mockReturnValueOnce(gate.promise);
  const view = await mount();
  change();
  fireEvent.click(save());
  view.unmount();
  await act(async () => gate.resolve({ ...original, first_name: 'Nueva' }));
  expect(toast.success).not.toHaveBeenCalled();
  expect(get).toHaveBeenCalledTimes(1);
});
it('a credential change during a pending read cannot mount the old profile', async () => {
  const gate = deferred<unknown>();
  get.mockReturnValueOnce(gate.promise);
  render(<Page />);
  await act(async () => {
    storeTokens({ access_token: 'new-owner', refresh_token: 'new-refresh' });
    mockUser = null;
    gate.resolve(original);
  });
  expect(screen.queryByDisplayValue('API-123')).not.toBeInTheDocument();
  expect(toast.success).not.toHaveBeenCalled();
});
it.each([
  { user_id: vehicle },
  { id: 'bad' },
  { profile_revision: undefined },
  { assignment_revision: 'bad' },
  { first_name: null },
  { phone: false },
  { vehicle_ownership_type: 'OTHER' },
  { assigned_vehicle_id: vehicle },
  { assigned_vehicle: { id: vehicle } },
  { vehicle_ownership_type: 'EMPRESA', assigned_vehicle_id: vehicle },
  {
    vehicle_ownership_type: 'EMPRESA',
    assigned_vehicle_id: vehicle,
    assigned_vehicle: { id: vehicle, revision, type: 'AUTO', plate: 'API-123' },
  },
])('rejects an invalid or contradictory profile DTO %#', (patch) => {
  expect(() => readSelfProfile({ ...original, ...patch }, owner)).toThrow();
});
it('projects only needed fields and validates the stable rider identity independently from its user id', () => {
  const p = readSelfProfile(
    { ...original, wallet_balance: 999, notes: 'PRIVATE', password: 'PRIVATE' },
    owner,
  );
  expect(p.id).not.toBe(p.user_id);
  expect(p).not.toHaveProperty('wallet_balance');
  expect(p).not.toHaveProperty('notes');
  expect(() => readSelfProfile({ ...original, id: vehicle }, owner, rider)).toThrow();
});
it('never sends fields outside the explicit editable projection', async () => {
  const base = readSelfProfile(original, owner);
  await riderSelf.save(
    base,
    { ...profileDraft(base), first_name: 'Nueva', tier: 'ORO', is_online: true } as never,
    owner,
  );
  expect(put).toHaveBeenCalledWith('/riders/me', {
    first_name: 'Nueva',
    expected_profile_revision: revision,
  });
});
it.each(['empty', 'company', 'type', 'owner'])(
  'rejects an invalid command %s before HTTP',
  async (mode) => {
    const company = {
      ...original,
      vehicle_ownership_type: 'EMPRESA',
      assigned_vehicle_id: vehicle,
      assigned_vehicle: { id: vehicle, revision, type: 'MOTO', plate: 'API-123' },
    };
    const base = readSelfProfile(mode === 'company' ? company : original, owner);
    const draft = {
      ...profileDraft(base),
      ...(mode === 'empty'
        ? {}
        : mode === 'company'
          ? { vehicle_plate: 'X' }
          : mode === 'type'
            ? { vehicle_type: 'INVALID' }
            : { first_name: 'Nueva' }),
    };
    await expect(riderSelf.save(base, draft, mode === 'owner' ? vehicle : owner)).rejects.toThrow();
    expect(put).not.toHaveBeenCalled();
  },
);

it.each([
  { first_name: 'x'.repeat(101) },
  { last_name: 'x'.repeat(101) },
  { phone: 'x'.repeat(21) },
  { vehicle_plate: 'x'.repeat(21) },
  { first_name: '   ' },
])('rejects invalid field lengths or blank names before HTTP %#', async (patch) => {
  const base = readSelfProfile(original, owner);
  await expect(riderSelf.save(base, { ...profileDraft(base), ...patch }, owner)).rejects.toThrow();
  expect(put).not.toHaveBeenCalled();
});

it('a historical vehicle type must be selected explicitly before changing its plate', async () => {
  row = { ...row, vehicle_type: 'HISTORICO' };
  await mount();
  fireEvent.change(screen.getByLabelText('Placa'), { target: { value: 'NEW' } });
  expect(save()).toBeDisabled();
  expect(screen.getByText(/Revisa el tipo de vehículo o adopta/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Tipo de vehículo'), { target: { value: 'MOTO' } });
  expect(save()).toBeEnabled();
  fireEvent.click(save());
  await screen.findByRole('dialog', { name: 'Confirmar cambio de vehículo' });
  expect(put).not.toHaveBeenCalled();
});
it('a concurrently assigned company vehicle cannot be overwritten by an old vehicle draft', async () => {
  put.mockRejectedValueOnce(Object.assign(new Error('conflict'), { status: 409 }));
  await mount();
  fireEvent.change(screen.getByLabelText('Placa'), { target: { value: 'OWN-NEW' } });
  fireEvent.click(save());
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirmar cambio' }),
  );
  await screen.findByRole('dialog', { name: 'El perfil cambió' });
  row = {
    ...row,
    vehicle_ownership_type: 'EMPRESA',
    vehicle_plate: 'COMPANY',
    assigned_vehicle_id: vehicle,
    assigned_vehicle: { id: vehicle, revision, type: 'MOTO', plate: 'COMPANY' },
  };
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Consultar de nuevo' }),
  );
  await screen.findByRole('dialog', { name: 'Revisa el perfil actual' });
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Revisar borrador' }),
  );
  expect(save()).toBeDisabled();
  expect(screen.getByLabelText('Placa')).toBeDisabled();
  expect(put).toHaveBeenCalledTimes(1);
});

it('a confirmed pending/offline receipt followed by 403 preserves the account restriction without claiming a verified read or repeating PUT', async () => {
  await mount();
  fireEvent.change(screen.getByLabelText('Placa'), { target: { value: 'PENDING-132' } });
  put.mockImplementationOnce(async () => {
    row = { ...row, vehicle_plate: 'PENDING-132', status: 'PENDIENTE', is_online: false };
    return row;
  });
  get
    .mockRejectedValueOnce(Object.assign(new Error('restricted'), { status: 403 }))
    .mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(save());
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirmar cambio' }),
  );
  let modal = await screen.findByRole('dialog', {
    name: 'Cambios confirmados; acceso restringido',
  });
  expect(toast.success).not.toHaveBeenCalled();
  expect(screen.queryByRole('link', { name: 'Gestionar documentos' })).not.toBeInTheDocument();
  fireEvent.click(within(modal).getByRole('button', { name: 'Consultar de nuevo' }));
  await waitFor(() =>
    expect(within(modal).getByRole('button', { name: 'Consultar de nuevo' })).toBeEnabled(),
  );
  expect(modal).toHaveAccessibleName('Cambios confirmados; acceso restringido');
  expect(put).toHaveBeenCalledTimes(1);
  fireEvent.click(within(modal).getByRole('button', { name: 'Volver' }));
  expect(save()).toBeDisabled();
  expect(
    screen.getByText('Guardado confirmado · cuenta pendiente de revisión'),
  ).toBeInTheDocument();
  row = { ...row, status: 'ACTIVO', is_online: false };
  fireEvent.click(screen.getByRole('button', { name: 'Recargar perfil' }));
  await screen.findByRole('dialog', { name: 'Revisa la documentación del vehículo' });
  expect(toast.success).toHaveBeenCalledWith('Perfil guardado y verificado');
  expect(put).toHaveBeenCalledTimes(1);
});
it('a generic 403 after a receipt that did not report pending/offline is not presented as documentary restriction', async () => {
  await mount();
  change();
  get.mockRejectedValueOnce(Object.assign(new Error('forbidden'), { status: 403 }));
  fireEvent.click(save());
  await screen.findByRole('dialog', { name: 'Guardado confirmado; consulta pendiente' });
  expect(screen.queryByText('Cambios confirmados; acceso restringido')).not.toBeInTheDocument();
  expect(toast.success).not.toHaveBeenCalled();
});
it.each([{ status: 'UNKNOWN' }, { is_online: 'false' }])(
  'rejects malformed availability facts %#',
  (patch) => expect(() => readSelfProfile({ ...original, ...patch }, owner)).toThrow(),
);
