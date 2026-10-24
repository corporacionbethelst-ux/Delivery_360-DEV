import { clearWithdrawalIntent, loadWithdrawalIntent, saveWithdrawalIntent, WithdrawalIntent } from '@/lib/withdrawal-intent';
const intent: WithdrawalIntent = { version: 1, userId: 'user-1', key: 'key-1', amountCents: 6000, bankLast4: '1234' };
beforeEach(() => { sessionStorage.clear(); jest.restoreAllMocks(); });
it('survives reload and remains scoped to the owner', () => {
  saveWithdrawalIntent(intent);
  expect(loadWithdrawalIntent('user-1')).toEqual(intent);
  expect(loadWithdrawalIntent('other-user')).toBeNull();
});
it('does not delete a newer intent when an old response finishes', () => {
  saveWithdrawalIntent({ ...intent, key: 'key-2' });
  clearWithdrawalIntent('user-1', 'key-1');
  expect(loadWithdrawalIntent('user-1')?.key).toBe('key-2');
  clearWithdrawalIntent('user-1', 'key-2');
  expect(loadWithdrawalIntent('user-1')).toBeNull();
});
it.each([{ amountCents: NaN }, { amountCents: 0 }, { amountCents: 1000.1 }, { key: '' }, { bankLast4: 'ABCD' }])('rejects invalid metadata: %j', invalid => {
  expect(() => saveWithdrawalIntent({ ...intent, ...invalid })).toThrow();
});
it('rejects forged ownership and malformed records without erasing their key', () => {
  sessionStorage.setItem('delivery360-withdrawal-v1:user-1', JSON.stringify({ ...intent, userId: 'other-user' }));
  expect(() => loadWithdrawalIntent('user-1')).toThrow();
  expect(sessionStorage.getItem('delivery360-withdrawal-v1:user-1')).not.toBeNull();
  sessionStorage.setItem('delivery360-withdrawal-v1:user-1', '{broken');
  expect(() => loadWithdrawalIntent('user-1')).toThrow();
});
it('propagates storage failures so the caller can stop before submitting', () => {
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable'); });
  expect(() => saveWithdrawalIntent(intent)).toThrow('Storage unavailable');
});
