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
