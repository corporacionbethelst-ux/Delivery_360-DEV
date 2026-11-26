import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TerminalDispatchReviewPanel } from '@/components/notifications/TerminalDispatchReviewPanel';
import { api } from '@/lib/api';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
import { toast } from '@/lib/feedback';
let mockUser: { id: string; role: string } | null = { id: 'staff', role: 'GERENTE' };
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/feedback', () => ({ toast: { success: jest.fn() } }));
const id = '00000000-0000-4000-8000-000000000001';
const attempt = '00000000-0000-4000-8000-000000000002';
const row = { id, event: 'entrega_completada', channel: 'EMAIL', recipient_id: '00000000-0000-4000-8000-000000000003', order_id: '00000000-0000-4000-8000-000000000004', state: 'uncertain', attempt_id: attempt, created_at: '2026-11-25T14:00:00+00:00', destination_hint: 'r***@example.com' };
const page = { items: [row], next_offset: null };
const get = jest.mocked(api.get); const post = jest.mocked(api.post);
beforeEach(() => { jest.resetAllMocks(); mockUser = { id: 'staff', role: 'GERENTE' }; storeTokens({ access_token: 'review-a', refresh_token: 'refresh-a' }); get.mockResolvedValue(page); });
afterEach(() => clearStoredTokens());
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
async function load() { fireEvent.click(screen.getByRole('button', { name: 'Consultar envíos' })); await screen.findByRole('article', { name: `Envío ${id}` }); }
async function open() { await load(); fireEvent.click(screen.getByRole('button', { name: 'Revisar resultado' })); }
function fields(decision = 'accepted') { fireEvent.change(screen.getByLabelText('Resultado de la verificación'), { target: { value: decision } }); fireEvent.change(screen.getByLabelText('Referencia de la verificación'), { target: { value: ' Caso-1234 ' } }); }
function ack(state: string) { const body = post.mock.calls[0][1] as any; return { id, review_id: body.review_id, decision: body.decision, state }; }

it.each(['OPERADOR', 'REPARTIDOR', 'AUDITOR', 'CLIENTE', null])('does not mount private review data for %s', role => {
  mockUser = role ? { id: 'other', role } : null; render(<TerminalDispatchReviewPanel />);
  expect(screen.queryByRole('region')).not.toBeInTheDocument(); expect(get).not.toHaveBeenCalled();
});
it('loads explicitly and never presents queued items as accepted or reviewable', async () => {
  get.mockResolvedValue({ items: [{ ...row, state: 'queued', attempt_id: null }], next_offset: null });
  render(<TerminalDispatchReviewPanel />); expect(get).not.toHaveBeenCalled(); await load();
  expect(screen.getByText('En cola')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Revisar resultado' })).not.toBeInTheDocument(); expect(post).not.toHaveBeenCalled();
});
it('requires an explicit decision and evidence reference', async () => {
  render(<TerminalDispatchReviewPanel />); await open();
  expect(screen.getByRole('button', { name: 'Registrar revisión' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Resultado de la verificación'), { target: { value: 'unconfirmed' } });
  fireEvent.change(screen.getByLabelText('Referencia de la verificación'), { target: { value: 'abc' } });
  expect(screen.getByRole('button', { name: 'Registrar revisión' })).toBeDisabled(); expect(post).not.toHaveBeenCalled();
});
it('confirms acceptance once, refreshes and never invokes a sending endpoint', async () => {
  const request = deferred<any>(); post.mockReturnValue(request.promise); render(<TerminalDispatchReviewPanel />); await open(); fields();
  const button = screen.getByRole('button', { name: 'Registrar revisión' }); fireEvent.click(button); fireEvent.click(button);
  expect(post).toHaveBeenCalledTimes(1); expect(post.mock.calls[0][0]).toBe(`/notifications/terminal-dispatch/${id}/review`);
  expect(post.mock.calls[0][1]).toMatchObject({ attempt_id: attempt, decision: 'accepted', reference: 'Caso-1234' });
  get.mockResolvedValue({ items: [], next_offset: null }); await act(async () => request.resolve(ack('accepted')));
  expect(await screen.findByRole('status')).toHaveTextContent('No hay envíos pendientes'); expect(toast.success).toHaveBeenCalledWith('Aceptación del proveedor registrada');
});
it('retains an unconfirmed outcome and does not claim acceptance', async () => {
  post.mockImplementation(async () => ack('uncertain')); render(<TerminalDispatchReviewPanel />); await open(); fields('unconfirmed');
  fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByText('Resultado sin confirmar')).toBeInTheDocument(); expect(toast.success).toHaveBeenCalledWith('Revisión registrada; el envío sigue sin confirmación');
});
it('retries an ambiguous response with the same frozen review key and payload', async () => {
  post.mockRejectedValueOnce(new Error('Respuesta perdida')).mockImplementation(async () => ack('accepted'));
  render(<TerminalDispatchReviewPanel />); await open(); fields(); fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Respuesta perdida'); expect(screen.getByLabelText('Referencia de la verificación')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar revisión' }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2)); expect(post.mock.calls[1][1]).toEqual(post.mock.calls[0][1]);
});
it('preserves rows on refresh failure instead of showing an empty queue', async () => {
  render(<TerminalDispatchReviewPanel />); await load(); get.mockRejectedValue(new Error('Consulta no disponible'));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar revisión' })); expect(await screen.findByRole('alert')).toHaveTextContent('Consulta no disponible');
  expect(screen.getByRole('article', { name: `Envío ${id}` })).toBeInTheDocument(); expect(screen.queryByText('No hay envíos pendientes en esta consulta.')).not.toBeInTheDocument();
});
it('discards a late queue response after credentials change', async () => {
  const request = deferred<any>(); get.mockReturnValue(request.promise); render(<TerminalDispatchReviewPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Consultar envíos' }));
  await act(async () => { storeTokens({ access_token: 'review-b', refresh_token: 'refresh-b' }); request.resolve(page); });
  expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Consultar envíos' })).toBeEnabled();
});
it('does not announce or refresh a delayed write after unmount', async () => {
  const request = deferred<any>(); post.mockReturnValue(request.promise); const view = render(<TerminalDispatchReviewPanel />); await open(); fields();
  fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión' })); view.unmount(); await act(async () => request.resolve(ack('accepted')));
  expect(toast.success).not.toHaveBeenCalled(); expect(get).toHaveBeenCalledTimes(1);
});
it('allows correction after a definitive validation rejection', async () => {
  post.mockRejectedValue({ response: { status: 422, data: { detail: 'Referencia inválida' } } });
  render(<TerminalDispatchReviewPanel />); await open(); fields(); fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Referencia inválida');
  expect(screen.getByLabelText('Referencia de la verificación')).toBeEnabled();
});
it('uses the conserved order reference and identifies the attempted clock in Caracas', async () => {
  get.mockResolvedValue({ items: [{ ...row, order_code: 'VE-CIERRE-124', attempt_started_at: '2026-11-25T14:00:00+00:00' }], next_offset: null });
  render(<TerminalDispatchReviewPanel />); await load();
  expect(screen.getByText(/Orden VE-CIERRE-124/)).toBeInTheDocument();
  expect(screen.getByText(/Intento registrado:.*Caracas/)).toBeInTheDocument();
});

it('identifies a payout as a request and keeps accounting approval separate from bank payment', async () => {
  get.mockResolvedValue({items:[{...row,event:'payout_aprobado',order_id:null,payout_id:'00000000-0000-4000-8000-000000000005'}],next_offset:null});
  render(<TerminalDispatchReviewPanel />);await load();
  expect(screen.getByText('Retiro aprobado contablemente')).toBeInTheDocument();
  expect(screen.getByText(/Solicitud de retiro 00000000/)).toBeInTheDocument();
  expect(screen.queryByText(/ID orden/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Revisar resultado'}));
  expect(screen.getByText(/La aceptación del proveedor no acredita recepción en el dispositivo ni un pago/)).toBeInTheDocument();
});

const technicalRow = { ...row, state: 'invalid', attempt_id: null, revision: 'a'.repeat(64), diagnostic: 'unverifiable_record' };
function technicalReceipt() {
  const value = post.mock.calls.at(-1)![1] as any;
  return { id, resolution_id: value.resolution_id, audit_id: '00000000-0000-4000-8000-000000000010', state: 'resolved', action: 'close_without_resend', resolved_at: '2026-11-26T14:00:00Z', resolved_by: row.recipient_id, reference: value.reference, note: value.note };
}
async function openTechnical() {
  get.mockResolvedValue({ items: [technicalRow], next_offset: null });
  render(<TerminalDispatchReviewPanel />); await load();
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar seguimiento técnico' }));
  await screen.findByRole('dialog', { name: 'Cerrar seguimiento técnico' });
}
function technicalFields() {
  fireEvent.change(screen.getByLabelText('Referencia del cierre técnico'), { target: { value: ' Caso-126 ' } });
  fireEvent.change(screen.getByLabelText('Observaciones del cierre técnico'), { target: { value: ' Revisado ' } });
  fireEvent.click(screen.getByRole('checkbox'));
}
it('requires a reference and explicit acknowledgement for technical closure', async () => {
  await openTechnical();
  expect(screen.getByRole('button',{name:'Cerrar sin reenviar'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Referencia del cierre técnico'),{target:{value:'Caso-126'}});
  expect(screen.getByRole('button',{name:'Cerrar sin reenviar'})).toBeDisabled();
  expect(screen.getByRole('checkbox')).not.toBeChecked();expect(post).not.toHaveBeenCalled();
});
it('records one closure with its frozen revision and no sending call', async () => {
  const request=deferred<any>();post.mockReturnValue(request.promise);
  await openTechnical();technicalFields();
  const button=screen.getByRole('button',{name:'Cerrar sin reenviar'});fireEvent.click(button);fireEvent.click(button);
  expect(post).toHaveBeenCalledTimes(1);expect(post.mock.calls[0][0]).toBe(`/notifications/terminal-dispatch/${id}/resolve`);
  expect(post.mock.calls[0][1]).toMatchObject({revision:technicalRow.revision,action:'close_without_resend',reference:'Caso-126',note:'Revisado'});
  get.mockResolvedValue({items:[],next_offset:null});await act(async()=>request.resolve(technicalReceipt()));
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(toast.success).toHaveBeenCalledWith('Cierre técnico registrado; no se reenviará el aviso');
});
it('repeats an ambiguous technical closure with the same key and data', async () => {
  post.mockRejectedValueOnce(new Error('Respuesta perdida')).mockImplementation(async()=>technicalReceipt());
  await openTechnical();technicalFields();fireEvent.click(screen.getByRole('button',{name:'Cerrar sin reenviar'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Respuesta perdida');
  expect(screen.getByLabelText('Referencia del cierre técnico')).toBeDisabled();expect(screen.getByRole('checkbox')).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Reintentar cierre'}));
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(post).toHaveBeenCalledTimes(2);expect(post.mock.calls[1][1]).toEqual(post.mock.calls[0][1]);
});
it('recovers a stale technical decision by GET without a second write', async () => {
  post.mockRejectedValue({response:{status:409,data:{detail:'El aviso cambió'}}});
  await openTechnical();technicalFields();fireEvent.click(screen.getByRole('button',{name:'Cerrar sin reenviar'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('El aviso cambió');
  fireEvent.click(screen.getByRole('button',{name:'Consultar estado'}));
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(post).toHaveBeenCalledTimes(1);expect(get).toHaveBeenCalledTimes(2);
});
it('allows correction after a definitive 422 and uses a new closure key', async () => {
  post.mockRejectedValueOnce({response:{status:422,data:{detail:'Referencia inválida'}}}).mockImplementation(async()=>technicalReceipt());
  await openTechnical();technicalFields();fireEvent.click(screen.getByRole('button',{name:'Cerrar sin reenviar'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Referencia inválida');
  expect(screen.getByLabelText('Referencia del cierre técnico')).toBeEnabled();
  fireEvent.change(screen.getByLabelText('Referencia del cierre técnico'),{target:{value:'Caso-126-corregido'}});
  fireEvent.click(screen.getByRole('button',{name:'Cerrar sin reenviar'}));
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect((post.mock.calls[1][1] as any).resolution_id).not.toBe((post.mock.calls[0][1] as any).resolution_id);
});
it('drops a delayed technical receipt after a credential change', async () => {
  const request=deferred<any>();post.mockReturnValue(request.promise);
  await openTechnical();technicalFields();fireEvent.click(screen.getByRole('button',{name:'Cerrar sin reenviar'}));
  const receipt=technicalReceipt();
  await act(async()=>{storeTokens({access_token:'technical-new-session',refresh_token:'technical-refresh'});request.resolve(receipt);});
  expect(toast.success).not.toHaveBeenCalled();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('shows technical history as a receipt without review or sending actions', async () => {
  const receipt={id,resolution_id:'00000000-0000-4000-8000-000000000009',audit_id:'00000000-0000-4000-8000-000000000010',state:'resolved',action:'close_without_resend',resolved_at:'2026-11-26T14:00:00Z',resolved_by:row.recipient_id,reference:'Caso-126',note:'Conservado'};
  get.mockResolvedValue({items:[{...technicalRow,state:'resolved',revision:null,resolution:receipt}],next_offset:null});
  render(<TerminalDispatchReviewPanel />);fireEvent.click(screen.getByRole('button',{name:'Cierres técnicos'}));
  expect(await screen.findByText('Cerrado sin reenvío')).toBeInTheDocument();
  expect(get.mock.calls[0][0]).toContain('view=resolved');expect(screen.getByText('Referencia: Caso-126')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Cerrar seguimiento técnico'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Revisar resultado'})).not.toBeInTheDocument();expect(post).not.toHaveBeenCalled();
});
