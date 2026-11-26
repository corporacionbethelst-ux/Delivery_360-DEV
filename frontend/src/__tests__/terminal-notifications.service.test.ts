import { terminalNotifications, isTerminalExternal } from '@/services/terminal-notifications.service';
import { api } from '@/lib/api';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const row = { id: '00000000-0000-4000-8000-000000000001', event: 'entrega_fallida', channel: 'EMAIL', recipient_id: '00000000-0000-4000-8000-000000000002', order_id: null, state: 'uncertain', attempt_id: '00000000-0000-4000-8000-000000000003', created_at: null, destination_hint: null };
beforeEach(() => { jest.resetAllMocks(); storeTokens({ access_token: 'review-contract', refresh_token: 'refresh' }); });
afterEach(() => clearStoredTokens());
it.each([null, { items: null, next_offset: null }, { items: [{ ...row, id: 'bad' }], next_offset: null }, { items: [{ ...row, state: 'delivered' }], next_offset: null }, { items: [{ ...row, attempt_id: null }], next_offset: null }, { items: [row,row], next_offset: null }, { items: [row], next_offset: 0 }])('rejects invalid pages without making a write', async value => {
  jest.mocked(api.get).mockResolvedValue(value); await expect(terminalNotifications.list()).rejects.toThrow(); expect(api.post).not.toHaveBeenCalled();
});
it('protects external managed event records from personal inbox mutations', () => {
  expect(isTerminalExternal({ channel: 'EMAIL', template_code: 'entrega_completada' })).toBe(true);
  expect(isTerminalExternal({ channel: 'IN_APP', template_code: 'entrega_completada' })).toBe(false);
  expect(isTerminalExternal({ channel: 'EMAIL', template_code: 'nuevo_pedido_asignado' })).toBe(true);
});

it.each(['payout_solicitado','payout_aprobado','payout_rechazado'])('protects %s external history while retaining internal read actions', code => {
  expect(isTerminalExternal({channel:'EMAIL', template_code:code})).toBe(true);
  expect(isTerminalExternal({channel:'IN_APP', template_code:code})).toBe(false);
});
it('accepts a payout reference without treating it as an order or a bank receipt', async () => {
  jest.mocked(api.get).mockResolvedValue({items:[{...row,event:'payout_aprobado',payout_id:'00000000-0000-4000-8000-000000000004'}],next_offset:null});
  const result = await terminalNotifications.list();
  expect(result.items[0].order_id).toBeNull();expect(result.items[0].payout_id).toBe('00000000-0000-4000-8000-000000000004');expect(api.post).not.toHaveBeenCalled();
});

const closedReceipt = {id:row.id,resolution_id:'00000000-0000-4000-8000-000000000009',audit_id:'00000000-0000-4000-8000-000000000010',state:'resolved',action:'close_without_resend',resolved_at:'2026-11-26T14:00:00Z',resolved_by:row.recipient_id,reference:'Caso-126',note:'Conservado'};
const technicalBody={resolution_id:closedReceipt.resolution_id,revision:'a'.repeat(64),action:'close_without_resend' as const,reference:'Caso-126',note:'Conservado'};
it.each([{revision:'bad'},{diagnostic:'provider_declined'},{delivery_id:'bad'}])('rejects malformed technical metadata', async patch=>{
  jest.mocked(api.get).mockResolvedValue({items:[{...row,state:'invalid',attempt_id:null,...patch}],next_offset:null});
  await expect(terminalNotifications.list()).rejects.toThrow();expect(api.post).not.toHaveBeenCalled();
});
it('never mixes resolved receipts into the pending view',async()=>{
  jest.mocked(api.get).mockResolvedValue({items:[{...row,state:'resolved',resolution:closedReceipt}],next_offset:null});
  await expect(terminalNotifications.list()).rejects.toThrow();
  await expect(terminalNotifications.list(0,'resolved')).resolves.toMatchObject({items:[{state:'resolved'}]});
});
it.each([{state:'accepted'},{action:'resend'},{id:row.recipient_id},{audit_id:'bad'},{reference:'Otro caso'},{note:'Distinto'},{resolution_id:row.recipient_id}])('does not accept an unrelated resolution response',async patch=>{
  jest.mocked(api.post).mockResolvedValue({...closedReceipt,...patch});
  await expect(terminalNotifications.resolve(row.id,technicalBody)).rejects.toThrow();
});
it('accepts only a receipt matching the closure request',async()=>{
  jest.mocked(api.post).mockResolvedValue(closedReceipt);
  await expect(terminalNotifications.resolve(row.id,technicalBody)).resolves.toEqual(closedReceipt);
  expect(api.post).toHaveBeenCalledWith(`/notifications/terminal-dispatch/${row.id}/resolve`,technicalBody);
});
