import { api } from '@/lib/api';
import { financialService } from '@/services/financial.service';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
beforeEach(() => {
  jest.resetAllMocks();
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => jest.restoreAllMocks());

it.each([[0, 1], [-2, 1], [2.9, 2], [999, 500], [NaN, 20], [Infinity, 20]])('bounds transaction pagination %s to %s', async (limit, expected) => {
  get.mockResolvedValueOnce([]);
  await financialService.getTransactions(limit);
  expect(get).toHaveBeenCalledWith(`/financial/transactions?limit=${expected}`);
});
it('keeps the real summary response and date filters', async () => {
  const response = { total_revenue: 42, total_costs: 7 };
  get.mockResolvedValueOnce(response);
  expect(await financialService.getSummary({ period: 'month', start_date: '2026-10-01', end_date: '2026-10-24' })).toBe(response);
  expect(get).toHaveBeenCalledWith('/financial/summary?period=month&start_date=2026-10-01&end_date=2026-10-24');
});
it('distinguishes personal earnings from filtered administrative earnings', async () => {
  get.mockResolvedValueOnce({ rider_id: 'me' }).mockResolvedValueOnce([]);
  expect(await financialService.getMyEarnings()).toEqual({ rider_id: 'me' });
  await financialService.getRiderEarnings('rider 1');
  expect(get).toHaveBeenNthCalledWith(1, '/financial/riders/me');
  expect(get).toHaveBeenNthCalledWith(2, '/financial/riders?rider_id=rider%201');
});
it('bounds breakdown and order report pagination', async () => {
  get.mockResolvedValue({ items: [] });
  await financialService.getMyEarningsBreakdown({ type: 'INGRESO', date_from: '2026-10-01', date_to: '2026-10-24', limit: NaN, offset: -1 });
  expect(get).toHaveBeenLastCalledWith('/financial/riders/me/earnings?type=INGRESO&date_from=2026-10-01&date_to=2026-10-24&limit=100');
  await financialService.getOrdersReport({ limit: 99999, offset: 2.7 });
  expect(get).toHaveBeenLastCalledWith('/financial/reports/orders?limit=5000&offset=2');
  await financialService.getOrdersReport({ limit: Infinity });
  expect(get).toHaveBeenLastCalledWith('/financial/reports/orders?limit=1000');
});
it('retrieves reconciliation using date filters only', async () => {
  get.mockResolvedValueOnce({ ledger_transactions: 2 });
  expect(await financialService.getReconciliation({ date_from: '2026-10-01', date_to: '2026-10-24', limit: 20 })).toEqual({ ledger_transactions: 2 });
  expect(get).toHaveBeenCalledWith('/financial/reconciliation?date_from=2026-10-01&date_to=2026-10-24');
});
it('propagates failures without replacing data with a fake empty report', async () => {
  const error = new Error('Unavailable');
  get.mockRejectedValue(error);
  await expect(financialService.getSummary()).rejects.toBe(error);
  await expect(financialService.getMyEarnings()).rejects.toBe(error);
  await expect(financialService.getRiderEarnings()).rejects.toBe(error);
  await expect(financialService.getMyEarningsBreakdown()).rejects.toBe(error);
  await expect(financialService.getOrdersReport()).rejects.toBe(error);
  await expect(financialService.getReconciliation()).rejects.toBe(error);
  await expect(financialService.getTransactions()).rejects.toBe(error);
});
