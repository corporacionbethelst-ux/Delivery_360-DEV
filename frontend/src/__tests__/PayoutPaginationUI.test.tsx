import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Rider from '@/app/(dashboard)/rider/earnings/payouts/page';
import Manager from '@/app/(dashboard)/manager/financial/payouts/page';
import { payoutService, type Payout, type PayoutPage } from '@/services/payout.service';
import { riderService } from '@/services/rider.service';
import { storeTokens, clearStoredTokens } from '@/lib/auth-session';

const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockUser = { id: 'a', role: 'REPARTIDOR' };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: mockUser, isAuthenticated: true }) }));
jest.mock('@/services/payout.service', () => ({ payoutService: { getPage: jest.fn() } }));
jest.mock('@/services/rider.service', () => ({ riderService: { getById: jest.fn() } }));
jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => <select value={value} onChange={e => onValueChange(e.target.value)}>{children}</select>,
  SelectTrigger: () => null, SelectValue: () => null, SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));
const rows = (start: number, count: number, status: Payout['status'] = 'PENDIENTE'): Payout[] => Array.from({ length: count }, (_, i) => ({ id: `p${start + i}`, rider_id: 'r', amount: 10 + (start + i) / 100, total_amount: 10 + (start + i) / 100, method: 'TRANSFERENCIA', status, requested_at: null, created_at: null, updated_at: null }));
const get = jest.mocked(payoutService.getPage);

const page = (items: Payout[]): PayoutPage => ({ items: items.slice(0, 50), next_cursor: items.length > 50 ? `after-${items[49].id}` : null });
function deferred() { let resolve!: (value: any) => void; const promise = new Promise<any>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  jest.resetAllMocks(); clearStoredTokens(); mockUser = { id: 'a', role: 'REPARTIDOR' }; storeTokens({ access_token: 'a', refresh_token: 'ra' });
  jest.mocked(riderService.getById).mockResolvedValue({ id: 'r', first_name: 'Ana', last_name: 'Test' });
});
afterEach(() => clearStoredTokens());

it.each(['rider', 'manager'])('reaches records after the first 50 and does not display the lookahead early (%s)', async kind => {
  get.mockResolvedValueOnce(page(rows(0, 51))).mockResolvedValueOnce(page(rows(50, 1))); render(kind === 'rider' ? <Rider /> : <Manager />);
  await screen.findByText('Página 1');
  expect(screen.getByRole('button', { name: 'Siguiente' })).toBeEnabled();
  expect(screen.queryByText(kind === 'rider' ? '#p50' : 'p50...')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByText('Página 2');
  expect(screen.getByText(kind === 'rider' ? '#p50' : 'p50...')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
  expect(get).toHaveBeenLastCalledWith({ limit: 50, cursor: 'after-p49', status: undefined });
  expect(screen.getByText('1 registro en esta página')).toBeInTheDocument();
});
it.each(['rider', 'manager'])('sends a status filter to the server rather than filtering only the initial batch (%s)', async kind => {
  get.mockResolvedValueOnce(page(rows(0, 1))).mockResolvedValueOnce(page(rows(100, 1, 'COMPLETADO'))); render(kind === 'rider' ? <Rider /> : <Manager />);
  await screen.findByText('Página 1');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'COMPLETADO' } });
  await waitFor(() => expect(get).toHaveBeenLastCalledWith({ limit: 50, cursor: null, status: 'COMPLETADO' }));
  await screen.findByText(kind === 'rider' ? '#p100' : 'p100...');
  expect(screen.queryByText(kind === 'rider' ? '#p0' : 'p0...')).not.toBeInTheDocument();
});
it('retains the page and label when a server filter fails and retries that same filter', async () => {
  get.mockResolvedValueOnce(page(rows(0, 1))).mockRejectedValueOnce(new Error('failed')).mockResolvedValueOnce(page(rows(100, 1, 'FALLIDO')));
  render(<Rider />); await screen.findByText('#p0');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'FALLIDO' } }); await screen.findByRole('alert');
  expect(screen.getByRole('combobox')).toHaveValue('ALL'); expect(screen.getByText('#p0')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar consulta' })); await screen.findByText('#p100');
  expect(screen.getByRole('combobox')).toHaveValue('FALLIDO');
});
it('allows recovering from a detected overlap by reloading the first page even when that page was retained', async () => {
  get.mockResolvedValueOnce(page(rows(0, 51))).mockResolvedValueOnce(page(rows(49, 51))).mockResolvedValueOnce(page(rows(100, 1)));
  render(<Rider />); await screen.findByText('Página 1'); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('cambió entre páginas');
  expect(screen.getByRole('button', { name: 'Volver al inicio' })).toBeEnabled(); fireEvent.click(screen.getByRole('button', { name: 'Volver al inicio' }));
  await screen.findByText('#p100'); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('does not describe a failed first read as an empty history or offer a first withdrawal', async () => {
  get.mockRejectedValue(new Error('unknown')); render(<Rider />); await screen.findByRole('alert');
  expect(screen.getByText('No se pudo comprobar el historial')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Solicitar retiro' })).not.toBeInTheDocument();
  expect(mockRouter.push).not.toHaveBeenCalled();
});
it('offers a deliberate new withdrawal only after observing an unfiltered empty first page', async () => {
  get.mockResolvedValueOnce(page([])).mockResolvedValueOnce(page([])); render(<Rider />);
  fireEvent.click(await screen.findByRole('button', { name: 'Solicitar retiro' })); expect(mockRouter.push).toHaveBeenCalledWith('/rider/earnings/withdraw');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'FALLIDO' } });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Solicitar retiro' })).not.toBeInTheDocument());
});
it('keeps local page search navigable when it finds no current-page matches', async () => {
  get.mockResolvedValueOnce(page(rows(0, 51))).mockResolvedValueOnce(page(rows(50, 1))); render(<Manager />); await screen.findByText('p0...');
  fireEvent.change(screen.getByPlaceholderText('Buscar en esta página por ID, nombre o email...'), { target: { value: 'p50' } });
  expect(screen.getByText(/Sin coincidencias en esta página/)).toBeInTheDocument();
  expect(get).toHaveBeenCalledTimes(1); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('p50...');
  expect(get).toHaveBeenCalledTimes(2);
});
it('marks unavailable/mismatched rider summaries without assigning the wrong person to a payout', async () => {
  get.mockResolvedValue(page(rows(0, 1))); jest.mocked(riderService.getById).mockResolvedValue({ id: 'another-rider', first_name: 'Wrong person' });
  render(<Manager />); await screen.findByText(/Algunos datos de repartidores no están disponibles/);
  expect(screen.queryByText('Wrong person')).not.toBeInTheDocument(); expect(screen.getByText('ID: r')).toBeInTheDocument();
});
it('does not publish old page rider names after a newer page completes', async () => {
  const old = deferred(); get.mockResolvedValueOnce(page(rows(0, 51))).mockResolvedValueOnce(page(rows(50, 1)));
  jest.mocked(riderService.getById).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ id: 'r', first_name: 'Current name' });
  render(<Manager />); await screen.findByText('p0...'); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
  await screen.findByText('Current name'); await act(async () => { old.resolve({ id: 'r', first_name: 'Retired name' }); });
  expect(screen.queryByText('Retired name')).not.toBeInTheDocument();
});
it('fetches summaries only for the visible page and deduplicates repeated rider IDs', async () => {
  get.mockResolvedValue(page(Array.from({ length: 51 }, (_, i) => ({ ...rows(i, 1)[0], rider_id: `r${i}` }))));
  jest.mocked(riderService.getById).mockImplementation(async id => ({ id })); render(<Manager />);
  await waitFor(() => expect(riderService.getById).toHaveBeenCalledTimes(50));
  expect(riderService.getById).not.toHaveBeenCalledWith('r50');
});
it('clears navigation/filter/search state when the account changes', async () => {
  get.mockResolvedValueOnce(page(rows(0, 51))).mockResolvedValueOnce(page(rows(50, 51))).mockResolvedValueOnce(page([])); render(<Manager />);
  await screen.findByText('Página 1'); fireEvent.click(screen.getByRole('button', { name: 'Siguiente' })); await screen.findByText('Página 2');
  fireEvent.change(screen.getByPlaceholderText('Buscar en esta página por ID, nombre o email...'), { target: { value: 'old search' } });
  act(() => { mockUser = { id: 'b', role: 'REPARTIDOR' }; storeTokens({ access_token: 'b', refresh_token: 'rb' }); });
  await screen.findByText('Página 1'); expect(screen.getByPlaceholderText('Buscar en esta página por ID, nombre o email...')).toHaveValue('');
  expect(get).toHaveBeenLastCalledWith({ limit: 50, cursor: null, status: undefined });
});
