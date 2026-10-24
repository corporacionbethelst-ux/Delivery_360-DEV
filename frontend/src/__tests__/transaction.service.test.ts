import { api } from '@/lib/api';
import { transactionService } from '@/services/transaction.service';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
const row = { id: 'tx-1', rider_id: 'rider-1', amount: '10.25', transaction_type: 'INGRESO', status: 'PROCESADO', created_at: '2026-10-24T10:00:00', balance_after: '100.25' };
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
  jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});
afterEach(() => jest.restoreAllMocks());
it('normalizes real amounts and snapshots without inventing a zero', async () => {
  get.mockResolvedValueOnce([row]);
  expect((await transactionService.getAll())[0]).toMatchObject({ id: 'tx-1', amount: 10.25, balance_after: 100.25, type: 'INGRESO', transaction_type: 'INGRESO', rider_id: 'rider-1' });
});
it.each([NaN, Infinity, -Infinity, null, true, '', ' ', 'not-money'])('rejects malformed monetary amounts: %s', async (amount) => {
  get.mockResolvedValueOnce([{ ...row, amount }]);
  await expect(transactionService.getAll()).rejects.toThrow('Importe financiero inválido');
});
it('keeps signed adjustments and tolerates genuinely absent snapshots', async () => {
  get.mockResolvedValueOnce([{ ...row, amount: -5.5, transaction_type: 'AJUSTE', balance_after: null }]);
  expect((await transactionService.getAll())[0]).toMatchObject({ amount: -5.5, balance_after: null });
});
it('rejects non-finite snapshots', async () => {
  get.mockResolvedValueOnce([{ ...row, balance_after: 'Infinity' }]);
  await expect(transactionService.getAll()).rejects.toThrow();
});
it.each([{ id: '' }, { transaction_type: undefined, type: undefined }])('rejects incomplete transaction identities: %j', async (invalid) => {
  get.mockResolvedValueOnce([{ ...row, ...invalid }]);
  await expect(transactionService.getAll()).rejects.toThrow('Identidad');
});
it('keeps legacy type aliases without changing amount direction', async () => {
  get.mockResolvedValueOnce([{ ...row, transaction_type: undefined, type: 'RETIRO', amount: 20 }]);
  expect((await transactionService.getAll())[0]).toMatchObject({ type: 'RETIRO', amount: 20 });
});
it('forwards filters, clamps limits and derives pagination offset', async () => {
  get.mockResolvedValueOnce([]);
  await transactionService.getAll({ type: 'INGRESO', status: 'PROCESADO', rider_id: ' rider-1 ', date_from: ' 2026-10-01 ', date_to: '2026-10-24', limit: 999, page: 3 });
  expect(get).toHaveBeenCalledWith('/financial/transactions?type=INGRESO&status=PROCESADO&rider_id=rider-1&date_from=2026-10-01&date_to=2026-10-24&limit=500&offset=1000');
});
it('omits ALL filters and invalid pagination', async () => {
  get.mockResolvedValueOnce([]);
  await transactionService.getAll({ type: 'ALL', status: 'ALL', limit: NaN, offset: -1 });
  expect(get).toHaveBeenCalledWith('/financial/transactions');
});
it('validates the identifier and retrieves detail at the expected route', async () => {
  await expect(transactionService.getById(' ')).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
  get.mockResolvedValueOnce(row);
  expect((await transactionService.getById(' tx-1 ')).id).toBe('tx-1');
  expect(get).toHaveBeenCalledWith('/financial/transactions/tx-1');
});
it('propagates server errors rather than returning an empty successful ledger', async () => {
  const failure = new Error('Unavailable');
  get.mockRejectedValue(failure);
  await expect(transactionService.getAll()).rejects.toBe(failure);
  await expect(transactionService.getById('tx-1')).rejects.toBe(failure);
});
