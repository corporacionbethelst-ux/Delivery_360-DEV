import { api } from '@/lib/api';
import { userService } from '@/services/user.service';
import { authService } from '@/services/auth.service';
import { UserRevisionError } from '@/lib/user-revision';
import { AxiosError, AxiosHeaders } from 'axios';
jest.mock('@/lib/api', () => ({ api:{ get:jest.fn(), patch:jest.fn(), put:jest.fn(), delete:jest.fn() } }));
const patch=jest.mocked(api.patch), put=jest.mocked(api.put), remove=jest.mocked(api.delete), get=jest.mocked(api.get);
const id='123e4567-e89b-42d3-a456-426614174000', revision='a'.repeat(64);
beforeEach(()=>{ jest.clearAllMocks(); jest.spyOn(console,'error').mockImplementation(()=>undefined); });
afterEach(()=>jest.restoreAllMocks());
it.each([undefined,'','bad','A'.repeat(64)])('refuses metadata/deactivation without a captured revision: %s',async value=>{
  await expect(userService.update(id,{ phone:'+111111111', expected_user_revision:value })).rejects.toBeInstanceOf(UserRevisionError);
  await expect(userService.deactivate(id,value)).rejects.toBeInstanceOf(UserRevisionError);
  await expect(userService.delete(id,value)).rejects.toBeInstanceOf(UserRevisionError);
  await expect(authService.updateProfile({ first_name:'New', expected_user_revision:value })).rejects.toBeInstanceOf(UserRevisionError);
  expect(patch).not.toHaveBeenCalled(); expect(put).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});
it('preserves the observed revision for all write routes without fetching another',async()=>{
  patch.mockResolvedValue({ id, user_revision:revision }); put.mockResolvedValue({ id, user_revision:revision });
  const data={ phone:'+111111111', expected_user_revision:revision };
  await userService.update(id,data); await userService.deactivate(id,revision); await userService.delete(id,revision); await authService.updateProfile(data);
  expect(patch).toHaveBeenCalledWith(`/users/${id}`,data);
  expect(patch).toHaveBeenCalledWith(`/users/${id}`,{ is_active:false, expected_user_revision:revision });
  expect(remove).toHaveBeenCalledWith(`/users/${id}`,{ headers:{ 'If-Match':`"${revision}"` } });
  expect(put).toHaveBeenCalledWith('/users/me',data); expect(get).not.toHaveBeenCalled();
});
it('preserves conflicts without retry or logging authorization headers',async()=>{
  const error=new AxiosError('Conflict','ERR_BAD_REQUEST',{ headers:new AxiosHeaders({ Authorization:'Bearer user-unit-secret' }) },undefined,{ status:409,statusText:'Conflict',headers:{},config:{} as any,data:{ detail:'Changed' } });
  patch.mockRejectedValueOnce(error);
  await expect(userService.update(id,{ first_name:'New', expected_user_revision:revision })).rejects.toBe(error);
  expect(patch).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
  expect(JSON.stringify(jest.mocked(console.error).mock.calls)).not.toContain('user-unit-secret');
});
