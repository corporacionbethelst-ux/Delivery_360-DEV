import { riderService } from '@/services/rider.service';
import { api } from '@/lib/api';
import { AssignmentRevisionError, isAssignmentConflict } from '@/lib/assignment-revision';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn(), patch: jest.fn() } }));
const patch = jest.mocked(api.patch), put = jest.mocked(api.put), get = jest.mocked(api.get);
const id = '123e4567-e89b-42d3-a456-426614174000', revision = 'a'.repeat(64);
beforeEach(() => jest.clearAllMocks());

it('uses the actual PATCH route and preserves the caller payload', async () => {
  const payload = { vehicle_ownership_type: 'EMPRESA' as const, assigned_vehicle_id: id, vehicle_type: 'MOTO', vehicle_plate: 'OLD', vehicle_model: 'Old', expected_assignment_revision: revision };
  const original = { ...payload };
  patch.mockResolvedValueOnce({ id, assignment_revision: 'b'.repeat(64) });
  await riderService.updateRider(id, payload);
  expect(patch).toHaveBeenCalledWith(`/riders/${id}`, { vehicle_ownership_type: 'EMPRESA', assigned_vehicle_id: id, expected_assignment_revision: revision });
  expect(put).not.toHaveBeenCalled();
  expect(payload).toEqual(original);
});

it('sends the profile snapshot to the personal endpoint', async () => {
  put.mockResolvedValueOnce({ id });
  const data = { vehicle_plate: 'NEW', expected_assignment_revision: revision };
  await riderService.updateProfile(data);
  expect(put).toHaveBeenCalledWith('/riders/me', data);
});

it.each([undefined, '', 'bad', 'A'.repeat(64)])('refuses fleet writes without a valid captured revision: %s', async (value) => {
  await expect(riderService.updateRider(id, { assigned_vehicle_id: null, expected_assignment_revision: value })).rejects.toBeInstanceOf(AssignmentRevisionError);
  await expect(riderService.updateProfile({ vehicle_plate: 'NEW', expected_assignment_revision: value })).rejects.toBeInstanceOf(AssignmentRevisionError);
  expect(patch).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});

it('keeps nonfleet updates compatible', async () => {
  patch.mockResolvedValueOnce({ id }); put.mockResolvedValueOnce({ id });
  await riderService.updateRider(id, { phone: '+584121234567' });
  await riderService.updateProfile({ first_name: 'New' });
  expect(patch).toHaveBeenCalledWith(`/riders/${id}`, { phone: '+584121234567' });
});

it('does not fetch a fresh revision or retry a conflicted write', async () => {
  patch.mockRejectedValueOnce(Object.assign(new Error('Changed'), { status: 409 }));
  await expect(riderService.updateRider(id, { vehicle_plate: 'NEW', expected_assignment_revision: revision })).rejects.toThrow();
  expect(patch).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
});

it.each([null, { status: 403 }, new Error('network')])('does not relabel unrelated failures as assignment conflicts', error => expect(isAssignmentConflict(error)).toBe(false));
it('recognizes the local missing-revision conflict', () => expect(isAssignmentConflict(new AssignmentRevisionError())).toBe(true));
