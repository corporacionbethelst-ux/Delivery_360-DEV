import { api } from '@/lib/api';
import { vehicleService } from '@/services/vehicle.service';
import { VehicleEditRevisionError } from '@/lib/vehicle-revision';
jest.mock('@/lib/api', () => ({ api: { get:jest.fn(), patch:jest.fn(), delete:jest.fn() } }));
const patch = jest.mocked(api.patch), remove = jest.mocked(api.delete), get = jest.mocked(api.get);
const id = '123e4567-e89b-42d3-a456-426614174000', revision = 'a'.repeat(64);
beforeEach(() => jest.clearAllMocks());
it.each([undefined, '', 'bad', 'A'.repeat(64)])('rejects all inventory writes without a captured edit revision: %s', async value => {
  await expect(vehicleService.update(id, { notes:'Old' }, value)).rejects.toBeInstanceOf(VehicleEditRevisionError);
  await expect(vehicleService.deactivate(id, value)).rejects.toBeInstanceOf(VehicleEditRevisionError);
  await expect(vehicleService.delete(id, value)).rejects.toBeInstanceOf(VehicleEditRevisionError);
  expect(patch).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});
it('updates with a quoted precondition and preserves explicit clears', async () => {
  patch.mockResolvedValueOnce({ id });
  const data = { plate:' abc-123 ', notes:null, insurance_expiry:null };
  await vehicleService.update(id, data, revision);
  expect(patch).toHaveBeenCalledWith(`/vehicles/${id}`, { plate:'ABC-123', notes:null, insurance_expiry:null }, { headers:{ 'If-Match':`"${revision}"` } });
  expect(data.plate).toBe(' abc-123 ');
});
it('deactivates the observed state', async () => {
  patch.mockResolvedValueOnce({ id });
  await vehicleService.deactivate(id, revision);
  expect(patch).toHaveBeenCalledWith(`/vehicles/${id}`, { status:'BAJA' }, { headers:{ 'If-Match':`"${revision}"` } });
});
it('deletes conditionally', async () => {
  remove.mockResolvedValueOnce(undefined);
  await vehicleService.delete(id, revision);
  expect(remove).toHaveBeenCalledWith(`/vehicles/${id}`, { headers:{ 'If-Match':`"${revision}"` } });
});
it('does not fetch or retry with another precondition', async () => {
  const log = jest.spyOn(console,'error').mockImplementation(() => undefined);
  patch.mockRejectedValueOnce(new Error('Changed'));
  await expect(vehicleService.update(id,{ notes:'Old' },revision)).rejects.toThrow();
  expect(patch).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
  log.mockRestore();
});
