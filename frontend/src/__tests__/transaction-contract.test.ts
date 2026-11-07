import { api } from '@/lib/api';
import { transactionService } from '@/services/transaction.service';
import { normalizeTransaction, normalizeTransactionPage, prepareTransactionQuery, TRANSACTION_TYPES, TRANSACTION_RESPONSE_STATUSES, transactionCsv } from '@/lib/transaction-contract';
import { clearStoredTokens, storeTokens, SessionChangedError } from '@/lib/auth-session';
import { transactionResponse } from '../../test-fixtures/transactions';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());

it.each(TRANSACTION_TYPES)('accepts real backend type %s without deriving a credit/debit sign', type => {
  expect(normalizeTransaction(transactionResponse('t', { transaction_type: type, type, amount: 20 }))).toMatchObject({ type, amount: 20 });
});
it.each(TRANSACTION_RESPONSE_STATUSES)('retains the informed status %s without relabeling it as bank success', status => {
  expect(normalizeTransaction(transactionResponse('t', { status })).status).toBe(status);
});
it('retains genuine zeros, missing snapshots/currency/dates and explicit audit fields', () => {
  const row = normalizeTransaction(transactionResponse('t', { amount: 0, balance_before: 0, balance_after: null, created_at: null, updated_at: undefined, description: null }));
  expect(row).toMatchObject({ amount: 0, balance_before: 0, balance_after: null, currency: null, created_at: null, updated_at: null, processed_at: null, source_id: 'order-1' });
  expect(row).not.toHaveProperty('user_id'); expect(row).not.toHaveProperty('metadata');
});
it('normalizes naive server timestamps as UTC and preserves explicit currency only', () => {
  expect(normalizeTransaction(transactionResponse('t', { currency: 'COP', processed_at: '2026-11-07T08:00:00-04:00' }))).toMatchObject({ currency: 'COP', created_at: '2026-11-07T12:00:00Z', processed_at: '2026-11-07T08:00:00-04:00' });
});
it.each([
  { id: '' }, { rider_id: false }, { type: 'RETIRO' }, { transaction_type: 'FUTURE', type: 'FUTURE' },
  { status: 'PAID' }, { amount: false }, { amount: '' }, { amount: '1.001' }, { amount: Infinity },
  { amount: '90071992547410' }, { balance_before: true }, { balance_after: 'NaN' }, { currency: 'usd' },
  { description: [] }, { created_at: '2026-02-30T12:00:00' }, { processed_at: false }, { created_by_user_id: '' },
])('rejects contradictory/malformed financial data (%j)', changes => {
  expect(() => normalizeTransaction(transactionResponse('t', changes))).toThrow();
});
it('accepts the documented type alias only when the canonical value is absent', () => {
  expect(normalizeTransaction(transactionResponse('t', { transaction_type: null, type: 'RETIRO' })).type).toBe('RETIRO');
  expect(() => normalizeTransaction(transactionResponse('t', { transaction_type: '' }))).toThrow();
});
it.each([{}, null, { items: [] }])('requires an array rather than pretending malformed data is an empty ledger (%j)', response => {
  expect(() => normalizeTransactionPage(response, prepareTransactionQuery())).toThrow();
});
it('rejects duplicated identities and pages beyond the limit', () => {
  const row = transactionResponse();
  expect(() => normalizeTransactionPage([row, row], prepareTransactionQuery())).toThrow();
  expect(() => normalizeTransactionPage([row, transactionResponse('two')], prepareTransactionQuery({ limit: 1 }))).toThrow();
});
it.each([
  { type: 'RETIRO' }, { status: 'PENDIENTE' }, { rider_id: 'another-rider' },
  { date_from: '2026-11-08' }, { date_to: '2026-11-07' },
])('rejects server results outside an applied filter (%j)', params => {
  expect(() => normalizeTransactionPage([transactionResponse()], prepareTransactionQuery(params as never))).toThrow();
});
it('requires a measured creation date when checking timestamp filters', () => {
  expect(() => normalizeTransactionPage([transactionResponse('t', { created_at: null })], prepareTransactionQuery({ date_from: '2026-11-01' }))).toThrow();
});
it.each([
  { type: 'future' }, { status: 'APROBADA' }, { status: 'PROCESANDO' }, { rider_id: ' ' }, { date_from: '' },
  { date_to: '2026-11-31' }, { date_from: '2026-11-08', date_to: '2026-11-07' }, { page: 0 }, { page: 1.5 },
  { offset: -1 }, { offset: Number.MAX_SAFE_INTEGER + 1 }, { offset: 0, page: 1 }, { limit: 500, page: Number.MAX_SAFE_INTEGER }, { statuses: ['PAGADO'] },
])('rejects ignored/unsupported filters and unsafe pagination before HTTP (%j)', async params => {
  await expect(transactionService.getAll(params as never)).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
it('uses every backend type in filters, derives page offsets with the default limit and normalizes timestamp offsets', () => {
  expect(prepareTransactionQuery({ type: 'BANK_TRANSFER', page: 2, date_from: '2026-11-07T08:00:00-04:00' })).toMatchObject({ type: 'BANK_TRANSFER', limit: 100, offset: 100, date_from: '2026-11-07T12:00:00.000Z' });
  expect(prepareTransactionQuery({ limit: 999, offset: 2.7 })).toMatchObject({ limit: 500, offset: 2 });
});
it('keeps the transaction endpoint date-only end at midnight, rather than borrowing report end-of-day semantics', () => {
  const query = prepareTransactionQuery({ date_to: '2026-11-07' });
  expect(() => normalizeTransactionPage([transactionResponse()], query)).toThrow();
  expect(normalizeTransactionPage([transactionResponse('midnight', { created_at: '2026-11-07T00:00:00' })], query)).toHaveLength(1);
});
it('checks the exact detail identity and encodes the requested route segment', async () => {
  get.mockResolvedValueOnce(transactionResponse('other')); await expect(transactionService.getById('requested')).rejects.toThrow();
  get.mockResolvedValueOnce(transactionResponse('a/b?c')); expect((await transactionService.getById('a/b?c')).id).toBe('a/b?c');
  expect(get).toHaveBeenLastCalledWith('/financial/transactions/a%2Fb%3Fc');
});
it.each(['ABCDEF0123456789ABCDEF0123456789', 'ABCDEF01-2345-6789-ABCD-EF0123456789'])('recognizes the same UUID in another accepted textual form (%s)', async requested => {
  const id = 'abcdef01-2345-6789-abcd-ef0123456789'; get.mockResolvedValue(transactionResponse(id));
  expect((await transactionService.getById(requested)).id).toBe(id); expect(get).toHaveBeenCalledWith(`/financial/transactions/${id}`);
});
it('captures the query sent before the caller can mutate its object', async () => {
  let resolve!: (value: unknown) => void; get.mockReturnValue(new Promise(done => { resolve = done; }));
  const query = { type: 'INGRESO' as const, rider_id: 'rider-1', limit: 1 };
  const pending = transactionService.getAll(query); Object.assign(query, { type: 'RETIRO', rider_id: 'other', limit: 500 });
  resolve([transactionResponse()]); expect((await pending)[0].type).toBe('INGRESO');
});
it.each(['list-success', 'list-failure', 'detail-success', 'detail-failure'])('retires a response or error from a previous account (%s)', async kind => {
  let resolve!: (value: unknown) => void, reject!: (error: Error) => void;
  get.mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
  const work = kind.startsWith('list') ? transactionService.getAll() : transactionService.getById('tx-1');
  storeTokens({ access_token: 'b', refresh_token: 'rb' });
  if (kind.endsWith('failure')) reject(new Error('retired')); else resolve(kind.startsWith('list') ? [transactionResponse()] : transactionResponse());
  await expect(work).rejects.toBeInstanceOf(SessionChangedError);
});
it('exports only the selected page rows with their original sign, unknown fields and declared scope', () => {
  const rows = [normalizeTransaction(transactionResponse('withdrawal', { type: 'RETIRO', transaction_type: 'RETIRO', amount: 20, description: null, balance_before: 0, balance_after: null, created_at: null }))];
  expect(transactionCsv(rows, { type: 'RETIRO', status: 'ALL', offset: 50, search: 'withdrawal' })[0]).toMatchObject({ id: 'withdrawal', importe_registrado: 20, moneda: '', descripcion: '', saldo_anterior: 0, saldo_posterior: null, fecha_creacion_utc: '', filtro_tipo: 'RETIRO', desplazamiento_consulta: 50, busqueda_local: 'withdrawal' });
});
