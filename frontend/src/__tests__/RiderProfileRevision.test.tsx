import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/rider/profile/page';
import { riderService } from '@/services/rider.service';
import type { Rider } from '@/types/user';
jest.mock('@/services/rider.service', () => ({ riderService: { getProfile: jest.fn(), updateProfile: jest.fn() } }));
const mockRouter = { push: jest.fn() };
const identity = { id:'123e4567-e89b-42d3-a456-426614174000', first_name:'Test', last_name:'Rider', email:'test@example.test', phone:'+584121234567', role:'REPARTIDOR', vehicle_type:'MOTO', vehicle_plate:'STORE' };
let mockUser = { ...identity };
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter }));
jest.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user:mockUser, isAuthenticated:true }) }));
const service = jest.mocked(riderService);
const revision = 'a'.repeat(64), nextRevision = 'b'.repeat(64);
const row = { ...identity, vehicle_plate:'API-123', profile_revision:revision, assignment_revision:revision } as Rider;
beforeEach(() => {
  jest.clearAllMocks(); mockUser = { ...identity };
  jest.spyOn(window, 'alert').mockImplementation(() => undefined);
  service.getProfile.mockResolvedValue(row); service.updateProfile.mockResolvedValue(row);
});
afterEach(() => jest.restoreAllMocks());

it('keeps the loaded snapshot when authentication metadata refreshes', async () => {
  const { rerender } = render(<Page />);
  const save = await screen.findByRole('button', { name:/Guardar Cambios/ });
  await waitFor(() => expect(save).toBeEnabled());
  mockUser = { ...identity, vehicle_plate:'NEW-STORE' };
  rerender(<Page />);
  expect(service.getProfile).toHaveBeenCalledTimes(1);
  fireEvent.click(save);
  await waitFor(() => expect(service.updateProfile).toHaveBeenCalledWith(expect.objectContaining({ expected_profile_revision:revision, expected_assignment_revision:revision, vehicle_plate:'API-123' })));
});

it('requires an explicit reload after conflict and never retries with a new revision', async () => {
  service.updateProfile.mockRejectedValueOnce(Object.assign(new Error('Changed'), { status:409 }));
  render(<Page />);
  const save = await screen.findByRole('button', { name:/Guardar Cambios/ });
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);
  await waitFor(() => expect(save).toBeDisabled());
  expect(service.updateProfile).toHaveBeenCalledTimes(1);
  expect(service.getProfile).toHaveBeenCalledTimes(1);
  expect(mockRouter.push).not.toHaveBeenCalledWith('/rider/profile/documents');
  expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('Recarga el perfil'));
  service.getProfile.mockResolvedValueOnce({ ...row, profile_revision:nextRevision, assignment_revision:nextRevision, vehicle_plate:'CURRENT' });
  fireEvent.click(screen.getByRole('button', { name:'Recargar perfil' }));
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);
  await waitFor(() => expect(service.updateProfile).toHaveBeenLastCalledWith(expect.objectContaining({ expected_profile_revision:nextRevision, expected_assignment_revision:nextRevision, vehicle_plate:'CURRENT' })));
});

it('does not authorize a write using fallback store data without a server revision', async () => {
  service.getProfile.mockRejectedValueOnce(new Error('offline'));
  const log = jest.spyOn(console, 'error').mockImplementation(() => undefined);
  render(<Page />);
  const save = await screen.findByRole('button', { name:/Guardar Cambios/ });
  await waitFor(() => expect(service.getProfile).toHaveBeenCalled());
  expect(save).toBeDisabled();
  fireEvent.click(save);
  expect(service.updateProfile).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name:'Recargar perfil' }));
  await waitFor(() => expect(save).toBeEnabled());
  log.mockRestore();
});

it('keeps save disabled if the server profile lacks the personal revision', async () => {
  service.getProfile.mockResolvedValueOnce({ ...row, profile_revision:undefined });
  render(<Page />);
  await screen.findByDisplayValue('API-123');
  expect(screen.getByRole('button', { name:/Guardar Cambios/ })).toBeDisabled();
  expect(service.updateProfile).not.toHaveBeenCalled();
});
