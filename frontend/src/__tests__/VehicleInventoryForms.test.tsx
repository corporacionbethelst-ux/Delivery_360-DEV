import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import EditPage from '@/app/(dashboard)/manager/fleet/vehicles/[id]/page';
import ListPage from '@/app/(dashboard)/manager/fleet/vehicles/page';
import { vehicleService, type Vehicle } from '@/services/vehicle.service';
jest.mock('@/services/vehicle.service', () => ({ vehicleService:{ getById:jest.fn(), getAll:jest.fn(), update:jest.fn(), deactivate:jest.fn() } }));
const mockRouter = { push:jest.fn(), back:jest.fn() };
let mockId = '123e4567-e89b-42d3-a456-426614174000';
jest.mock('next/navigation', () => ({ useRouter:()=>mockRouter, useParams:()=>({ id:mockId }) }));
jest.mock('sonner', () => ({ toast:{ success:jest.fn(), error:jest.fn() } }));
jest.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu:({ children }: any)=><>{children}</>, DropdownMenuTrigger:()=>null,
  DropdownMenuContent:({ children }: any)=><>{children}</>,
  DropdownMenuItem:({ children, onClick, disabled }: any)=><button disabled={disabled} onClick={onClick}>{children}</button>, DropdownMenuSeparator:()=>null,
}));
const service = jest.mocked(vehicleService);
const revision = 'a'.repeat(64), nextRevision = 'b'.repeat(64);
const row = { id:mockId, revision:'c'.repeat(64), edit_revision:revision, plate:'TEST-123', type:'MOTO', model:'Test model', color:'Black', year:2025, status:'ACTIVO', notes:'Original note', insurance_expiry:null, created_at:'2026-01-01' } as Vehicle;
beforeEach(()=>{ jest.clearAllMocks(); mockId=row.id; service.getById.mockResolvedValue(row); service.getAll.mockResolvedValue([row]); service.update.mockResolvedValue(row); service.deactivate.mockResolvedValue(row); });

it('editor sends its loaded edit revision and explicit nulls when fields are cleared', async () => {
  render(<EditPage />);
  fireEvent.change(await screen.findByDisplayValue('Original note'), { target:{ value:'' } });
  fireEvent.click(screen.getByRole('button',{ name:'Guardar Cambios' }));
  await waitFor(()=>expect(service.update).toHaveBeenCalledWith(row.id,expect.objectContaining({ notes:null, insurance_expiry:null }),revision));
});

it('editor remains blocked after conflict until an explicit reload replaces the draft', async () => {
  service.update.mockRejectedValueOnce(Object.assign(new Error('Changed'),{ status:409 }));
  render(<EditPage />);
  fireEvent.change(await screen.findByDisplayValue('Original note'),{ target:{ value:'Old edit' } });
  fireEvent.click(screen.getByRole('button',{ name:'Guardar Cambios' }));
  await waitFor(()=>expect(screen.getByRole('button',{ name:'Guardar Cambios' })).toBeDisabled());
  expect(service.getById).toHaveBeenCalledTimes(1);
  service.getById.mockResolvedValueOnce({ ...row, edit_revision:nextRevision, notes:'Current note' });
  fireEvent.click(screen.getByRole('button',{ name:'Recargar ficha' }));
  await screen.findByDisplayValue('Current note');
  fireEvent.click(screen.getByRole('button',{ name:'Guardar Cambios' }));
  await waitFor(()=>expect(service.update).toHaveBeenLastCalledWith(row.id,expect.objectContaining({ notes:'Current note' }),nextRevision));
});

it('ignores an obsolete fetch after navigating to another vehicle', async () => {
  let finish!: (value:Vehicle)=>void;
  service.getById.mockReturnValueOnce(new Promise(resolve=>{ finish=resolve; }));
  const { rerender } = render(<EditPage />);
  mockId='123e4567-e89b-42d3-a456-426614174001';
  service.getById.mockResolvedValueOnce({ ...row, id:mockId, edit_revision:nextRevision, notes:'Second vehicle' });
  rerender(<EditPage />);
  await screen.findByDisplayValue('Second vehicle');
  await act(async()=>finish(row));
  expect(screen.queryByDisplayValue('Original note')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{ name:'Guardar Cambios' }));
  await waitFor(()=>expect(service.update).toHaveBeenCalledWith(mockId,expect.objectContaining({ notes:'Second vehicle' }),nextRevision));
});

it('deactivation keeps the confirmation snapshot when the list refreshes', async () => {
  render(<ListPage />);
  await screen.findByRole('button',{ name:/Dar de baja/i });
  fireEvent.change(screen.getByPlaceholderText('Buscar por placa, modelo o repartidor...'), { target:{ value:'TEST' } });
  fireEvent.click(screen.getByRole('button',{ name:/Dar de baja/i }));
  const dialog = screen.getByRole('dialog');
  service.getAll.mockResolvedValueOnce([{ ...row, edit_revision:nextRevision, plate:'NEWER' }]);
  await waitFor(()=>expect(service.getAll).toHaveBeenCalledTimes(2));
  fireEvent.click(within(dialog).getByRole('button',{ name:/Sí, dar de baja/ }));
  await waitFor(()=>expect(service.deactivate).toHaveBeenCalledWith(row.id,revision));
});

it('deactivation conflict requires closing/reloading rather than retrying', async () => {
  service.deactivate.mockRejectedValueOnce(Object.assign(new Error('Changed'),{ status:409 }));
  render(<ListPage />);
  fireEvent.click(await screen.findByRole('button',{ name:/Dar de baja/i }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, dar de baja/ }));
  const reload = await screen.findByRole('button',{ name:'Cerrar y actualizar' });
  expect(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, dar de baja/ })).toBeDisabled();
  expect(service.deactivate).toHaveBeenCalledTimes(1);
  fireEvent.click(reload);
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(service.deactivate).toHaveBeenCalledTimes(1);
});
