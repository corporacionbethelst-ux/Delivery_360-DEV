import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Page from '@/app/(dashboard)/operator/orders/page';
import { orderService } from '@/services/order.service';
import { clearStoredTokens, storeTokens } from '@/lib/auth-session';
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ isAuthenticated: true, user: mockUser }) }));
jest.mock('@/services/order.service', () => ({ orderService: { getAll: jest.fn() } }));
jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => <select value={value} onChange={e => onValueChange(e.target.value)}>{children}</select>,
  SelectTrigger: () => null, SelectValue: () => null, SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ children, value }: any) => <option value={value}>{children}</option>,
}));
const mockRouter = { push: jest.fn() }, mockUser = { id: 'operator', role: 'OPERADOR' };
const existing = { id: 'a', external_id: 'KEEP-ME', status: 'PENDIENTE', total: 0, total_amount: 99 };
beforeEach(() => { jest.resetAllMocks(); clearStoredTokens(); storeTokens({ access_token: 'a', refresh_token: 'ra' }); });
afterEach(() => clearStoredTokens());
it('keeps the complete prior list and displays a failed-refresh error', async () => {
  jest.mocked(orderService.getAll).mockResolvedValueOnce([existing] as never).mockRejectedValueOnce(new Error('later page failed'));
  render(<Page />);
  await screen.findByText('#KEEP-ME');
  expect(orderService.getAll).toHaveBeenCalledWith();
  expect(screen.queryByText(/99/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Se conservan');
  expect(screen.getByText('#KEEP-ME')).toBeInTheDocument();
});
it('discards a late caller continuation after the account changes', async () => {
  let resolve!: (v: any) => void;
  jest.mocked(orderService.getAll).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce([]);
  render(<Page />);
  await act(async () => { storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await act(async () => { resolve([existing]); });
  expect(screen.queryByText('#KEEP-ME')).not.toBeInTheDocument();
  expect(orderService.getAll).toHaveBeenCalledTimes(2);
});
it('does not begin a catalog request when credentials have been cleared', async () => {
  clearStoredTokens();
  render(<Page />);
  await act(async () => {});
  expect(orderService.getAll).not.toHaveBeenCalled();
});
