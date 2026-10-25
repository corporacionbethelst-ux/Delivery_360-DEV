import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import RiderEditModal from '@/components/riders/RiderEditModal';
import { riderService } from '@/services/rider.service';
import { toast } from 'sonner';
import type { Rider } from '@/types/user';
jest.mock('@/services/rider.service', () => ({ riderService: { updateRider: jest.fn(), getById: jest.fn() } }));
jest.mock('@/services/vehicle.service', () => ({ vehicleService: { getAvailableCompanyVehicles: jest.fn().mockResolvedValue([]) } }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
const service = jest.mocked(riderService);
const revision = 'a'.repeat(64), nextRevision = 'b'.repeat(64);
const row = { id:'123e4567-e89b-42d3-a456-426614174000', first_name:'Test', last_name:'Rider', email:'test@example.test', phone:'+584121234567', vehicle_type:'MOTO', vehicle_plate:'OWN-123', vehicle_ownership_type:'PROPIO', assignment_revision:revision } as Rider;
const success = jest.fn(), change = jest.fn();
const view = (rider: Rider = row, open = true) => <RiderEditModal rider={rider} open={open} onOpenChange={change} onSuccess={success} />;
beforeEach(() => { jest.clearAllMocks(); service.updateRider.mockResolvedValue(row); });

it('saves the captured snapshot and closes on success', async () => {
  render(view());
  fireEvent.change(await screen.findByPlaceholderText('ABC-1234'), { target: { value: 'EDIT-123' } });
  fireEvent.click(screen.getByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ expected_assignment_revision:revision, vehicle_plate:'EDIT-123' })));
  await waitFor(() => expect(change).toHaveBeenCalledWith(false));
  expect(success).toHaveBeenCalledTimes(1);
});

it('does not replace the draft or its revision when parent metadata refreshes', async () => {
  const { rerender } = render(view());
  fireEvent.change(await screen.findByPlaceholderText('ABC-1234'), { target: { value:'EDIT-123' } });
  rerender(view({ ...row, assignment_revision:nextRevision, vehicle_plate:'LATEST' }));
  expect(screen.getByPlaceholderText('ABC-1234')).toHaveValue('EDIT-123');
  fireEvent.click(screen.getByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ expected_assignment_revision:revision, vehicle_plate:'EDIT-123' })));
});

it('blocks further writes after conflict and offers an explicit close/reload', async () => {
  service.updateRider.mockRejectedValueOnce(Object.assign(new Error('Changed'), { status:409 }));
  const { rerender } = render(view());
  fireEvent.click(await screen.findByRole('button', { name:'Guardar Cambios' }));
  const reload = await screen.findByRole('button', { name:'Cerrar y recargar' });
  rerender(view({ ...row, assignment_revision:nextRevision }));
  expect(screen.getByRole('button', { name:'Guardar Cambios' })).toBeDisabled();
  fireEvent.click(reload);
  expect(success).toHaveBeenCalledTimes(1); expect(change).toHaveBeenCalledWith(false);
  expect(service.updateRider).toHaveBeenCalledTimes(1); expect(service.getById).not.toHaveBeenCalled();
});

it('does not submit a legacy row without revision', async () => {
  render(view({ ...row, assignment_revision:undefined }));
  fireEvent.click(await screen.findByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(service.updateRider).not.toHaveBeenCalled();
});

it('captures a fresh snapshot only after closing and reopening', async () => {
  const { rerender } = render(view());
  await screen.findByPlaceholderText('ABC-1234');
  rerender(view(row, false));
  rerender(view({ ...row, assignment_revision:nextRevision, vehicle_plate:'LATEST' }));
  fireEvent.click(await screen.findByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ expected_assignment_revision:nextRevision, vehicle_plate:'LATEST' })));
});

it('retains the current company assignment when it is absent from the free catalog', async () => {
  render(view({ ...row, vehicle_ownership_type:'EMPRESA', assigned_vehicle_id:row.id, assigned_vehicle:{ id:row.id, revision, plate:'OWN-123', type:'MOTO', model:'Test', color:'Black', year:2025 } }));
  fireEvent.click(await screen.findByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ assigned_vehicle_id:row.id, expected_assignment_revision:revision })));
});
