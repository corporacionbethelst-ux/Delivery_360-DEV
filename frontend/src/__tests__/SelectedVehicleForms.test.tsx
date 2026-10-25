import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Modal from '@/components/riders/RiderEditModal';
import Registration from '@/components/riders/RiderRegistrationForm';
import { riderService } from '@/services/rider.service';
import { vehicleService, type Vehicle } from '@/services/vehicle.service';
import type { Rider } from '@/types/user';
const mockCreate = jest.fn();
jest.mock('@/stores/ridersStore', () => ({ useRidersStore: () => ({ createRider:mockCreate }) }));
jest.mock('@/services/rider.service', () => ({ riderService: { updateRider:jest.fn() } }));
jest.mock('@/services/vehicle.service', () => ({ vehicleService: { getAvailableCompanyVehicles:jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success:jest.fn(), error:jest.fn() } }));
jest.mock('@/components/ui/select', () => {
  const React = require('react');
  return {
    Select: ({ children, onValueChange, value, defaultValue }: any) => <select value={value} defaultValue={defaultValue} onChange={event => onValueChange(event.target.value)}>{children}</select>,
    SelectTrigger: () => null,
    SelectValue: () => null,
    SelectContent: ({ children }: any) => <>{children}</>,
    SelectItem: ({ children, value }: any) => <option value={value}>{children}</option>,
  };
});
const revision = 'a'.repeat(64), chosen = 'b'.repeat(64), newer = 'c'.repeat(64);
const row = { id:'123e4567-e89b-42d3-a456-426614174000', first_name:'Test', last_name:'Rider', email:'test@example.test', vehicle_type:'MOTO', vehicle_plate:'OWN', vehicle_ownership_type:'PROPIO', assignment_revision:revision } as Rider;
const vehicle = { id:'123e4567-e89b-42d3-a456-426614174001', revision:chosen, type:'MOTO', plate:'SELECTED', model:'Test', color:'Black', year:2025, status:'ACTIVO', created_at:'2026-01-01' } as Vehicle;
const service = jest.mocked(riderService), vehicles = jest.mocked(vehicleService);
beforeEach(() => { jest.clearAllMocks(); service.updateRider.mockResolvedValue(row); vehicles.getAvailableCompanyVehicles.mockResolvedValue([vehicle]); mockCreate.mockResolvedValue(row); });

it('keeps a candidate snapshot selected before parent catalog refresh', async () => {
  const props = { rider:row, open:true, onOpenChange:jest.fn(), onSuccess:jest.fn(), companyVehicles:[vehicle] };
  const { rerender } = render(<Modal {...props} />);
  fireEvent.change(screen.getAllByRole('combobox')[1], { target:{ value:'EMPRESA' } });
  rerender(<Modal {...props} companyVehicles={[{ ...vehicle, revision:newer, plate:'CHANGED' }]} />);
  fireEvent.click(screen.getByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ assigned_vehicle_id:vehicle.id, expected_vehicle_revision:chosen, expected_assignment_revision:revision })));
});

it('captures an explicitly chosen candidate rather than the first catalog row', async () => {
  const second = { ...vehicle, id:'123e4567-e89b-42d3-a456-426614174002', revision:newer, plate:'SECOND' };
  render(<Modal rider={row} open onOpenChange={jest.fn()} onSuccess={jest.fn()} companyVehicles={[vehicle, second]} />);
  fireEvent.change(screen.getAllByRole('combobox')[1], { target:{ value:'EMPRESA' } });
  fireEvent.change(screen.getAllByRole('combobox')[2], { target:{ value:second.id } });
  fireEvent.click(screen.getByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ assigned_vehicle_id:second.id, expected_vehicle_revision:newer })));
});

it('registration requires an explicit reload after conflict before using the new candidate revision', async () => {
  mockCreate.mockRejectedValueOnce(Object.assign(new Error('La ficha cambió'), { status:409 }));
  const { container } = render(<Registration />);
  fireEvent.change(screen.getByPlaceholderText('Ej. Juan Pérez'), { target:{ value:'Test Rider' } });
  fireEvent.change(screen.getByPlaceholderText('juan@ejemplo.com'), { target:{ value:'test@example.test' } });
  fireEvent.change(screen.getByPlaceholderText('+55 11 99999-9999'), { target:{ value:'+584121234567' } });
  fireEvent.change(screen.getByPlaceholderText('000.000.000-00'), { target:{ value:'123456789' } });
  fireEvent.change(container.querySelector('input[type=date]')!, { target:{ value:'1990-01-01' } });
  fireEvent.change(screen.getByPlaceholderText('Ej. Centro, Norte, Sur...'), { target:{ value:'Centro' } });
  fireEvent.change(screen.getByPlaceholderText('******'), { target:{ value:'ValidPassword123!' } });
  fireEvent.change(screen.getAllByRole('combobox')[0], { target:{ value:'EMPRESA' } });
  await waitFor(() => expect(vehicles.getAvailableCompanyVehicles).toHaveBeenCalledTimes(1));
  const save = screen.getByRole('button', { name:/Registrar/ });
  fireEvent.click(save);
  await waitFor(() => expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ assigned_vehicle_id:vehicle.id, expected_vehicle_revision:chosen })));
  await waitFor(() => expect(save).toBeDisabled());
  expect(mockCreate).toHaveBeenCalledTimes(1);
  vehicles.getAvailableCompanyVehicles.mockResolvedValueOnce([{ ...vehicle, revision:newer, plate:'CURRENT' }]);
  fireEvent.click(screen.getByRole('button', { name:'Recargar vehículos' }));
  await waitFor(() => expect(save).toBeEnabled());
  await waitFor(() => expect(vehicles.getAvailableCompanyVehicles).toHaveBeenCalledTimes(2));
  fireEvent.click(save);
  await waitFor(() => expect(mockCreate).toHaveBeenLastCalledWith(expect.objectContaining({ expected_vehicle_revision:newer })));
});

it('keeps the selected record visible when a refreshed catalog omits it', async () => {
  vehicles.getAvailableCompanyVehicles.mockResolvedValueOnce([]);
  const props = { rider:row, open:true, onOpenChange:jest.fn(), onSuccess:jest.fn(), companyVehicles:[vehicle] };
  const { rerender } = render(<Modal {...props} />);
  fireEvent.change(screen.getAllByRole('combobox')[1], { target:{ value:'EMPRESA' } });
  rerender(<Modal {...props} companyVehicles={[]} />);
  await waitFor(() => expect(screen.getByRole('option', { name:/SELECTED/ })).toHaveValue(vehicle.id));
  fireEvent.click(screen.getByRole('button', { name:'Guardar Cambios' }));
  await waitFor(() => expect(service.updateRider).toHaveBeenCalledWith(row.id, expect.objectContaining({ expected_vehicle_revision:chosen })));
});
