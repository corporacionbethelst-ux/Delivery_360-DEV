import { storeTokens, clearStoredTokens } from '@/lib/auth-session';
import { riderService } from '@/services/rider.service';
import { api } from '@/lib/api';
import { VehicleRevisionError } from '@/lib/vehicle-revision';
jest.mock('@/lib/api', () => ({ api: { get:jest.fn(), post:jest.fn(), patch:jest.fn() } }));
const post = jest.mocked(api.post), patch = jest.mocked(api.patch), get = jest.mocked(api.get);
const id = '123e4567-e89b-42d3-a456-426614174000', revision = 'a'.repeat(64), selected = 'b'.repeat(64);
const create = { email:'rider@example.test', password:'ValidPassword123!', first_name:'Test', last_name:'Rider', phone:'+584121234567', vehicle_type:'MOTO', vehicle_ownership_type:'EMPRESA' as const, assigned_vehicle_id:id };
beforeEach(() => {
  clearStoredTokens();
  storeTokens({ access_token: 'selected-vehicle-test-access', refresh_token: 'selected-vehicle-test-refresh' });
  jest.clearAllMocks();
});
afterEach(() => clearStoredTokens());
it.each([undefined, '', 'bad', 'A'.repeat(64)])('refuses an unbound candidate for creation/update: %s', async value => {
  await expect(riderService.createRider({ ...create, expected_vehicle_revision:value })).rejects.toBeInstanceOf(VehicleRevisionError);
  await expect(riderService.updateRider(id, { assigned_vehicle_id:id, expected_assignment_revision:revision, expected_vehicle_revision:value })).rejects.toBeInstanceOf(VehicleRevisionError);
  expect(post).not.toHaveBeenCalled(); expect(patch).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});
it('sends exactly the selected revision without fetching another record', async () => {
  post.mockResolvedValueOnce({ id }); patch.mockResolvedValueOnce({ id });
  await riderService.createRider({ ...create, expected_vehicle_revision:selected });
  expect(post).toHaveBeenCalledWith('/riders', { ...create, expected_vehicle_revision:selected });
  await riderService.updateRider(id, { assigned_vehicle_id:id, expected_assignment_revision:revision, expected_vehicle_revision:selected });
  expect(patch).toHaveBeenCalledWith(`/riders/${id}`, { assigned_vehicle_id:id, expected_assignment_revision:revision, expected_vehicle_revision:selected });
  expect(get).not.toHaveBeenCalled();
});

// The registration store must not bypass the precondition through its direct API path.
import { useRidersStore } from '@/stores/ridersStore';
it('store creation rejects a missing candidate before posting, then preserves the supplied snapshot', async () => {
  useRidersStore.setState({ riders:[], total:0, error:null, isLoading:false });
  const log = jest.spyOn(console, 'error').mockImplementation(() => undefined);
  await expect(useRidersStore.getState().createRider(create)).rejects.toBeInstanceOf(VehicleRevisionError);
  expect(post).not.toHaveBeenCalled();
  post.mockResolvedValueOnce({ id });
  await useRidersStore.getState().createRider({ ...create, expected_vehicle_revision:selected });
  expect(post).toHaveBeenCalledWith('/riders', { ...create, expected_vehicle_revision:selected });
  expect(useRidersStore.getState().total).toBe(1);
  log.mockRestore();
});
it('store updates use PATCH with both captured revisions', async () => {
  patch.mockResolvedValueOnce({ id });
  const data = { assigned_vehicle_id:id, vehicle_ownership_type:'EMPRESA' as const, expected_assignment_revision:revision, expected_vehicle_revision:selected };
  await useRidersStore.getState().updateRider(id, data);
  expect(patch).toHaveBeenCalledWith(`/riders/${id}`, data);
  expect(get).not.toHaveBeenCalled();
});

import { AxiosError, AxiosHeaders } from 'axios';
import { vehicleService } from '@/services/vehicle.service';
it('does not print authorization headers from vehicle errors', async () => {
  const log = jest.spyOn(console, 'error').mockImplementation(() => undefined);
  get.mockRejectedValueOnce(new AxiosError('Network error', 'ERR_NETWORK', { headers:new AxiosHeaders({ Authorization:'Bearer selected-vehicle-unit-secret' }) }));
  await expect(vehicleService.getById(id)).rejects.toThrow();
  expect(JSON.stringify(log.mock.calls)).not.toContain('selected-vehicle-unit-secret');
  log.mockRestore();
});

it('store personal updates preserve the captured profile revision', async () => {
  patch.mockResolvedValueOnce({ id });
  await useRidersStore.getState().updateRider(id, { phone:'+584121234567', expected_profile_revision:revision });
  expect(patch).toHaveBeenCalledWith(`/riders/${id}`, { phone:'+584121234567', expected_profile_revision:revision });
  expect(get).not.toHaveBeenCalled();
});
it('preserves a structured email conflict for rider registration',async()=>{
 const log=jest.spyOn(console,'error').mockImplementation(()=>undefined);
 post.mockRejectedValueOnce(new AxiosError('Conflict','ERR_BAD_REQUEST',undefined,undefined,{ status:409,statusText:'Conflict',headers:{},config:{} as any,data:{ detail:{ code:'USER_EMAIL_CONFLICT',message:'El correo ya está registrado. Use otro correo' } } }));
 await expect(riderService.createRider({ ...create, expected_vehicle_revision:selected })).rejects.toMatchObject({ status:409,code:'USER_EMAIL_CONFLICT',message:'El correo ya está registrado. Use otro correo' });
 expect(get).not.toHaveBeenCalled(); log.mockRestore();
});
