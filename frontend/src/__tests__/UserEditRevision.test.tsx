import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/admin/users/[id]/page';
import { userService } from '@/services/user.service';
import type { User } from '@/types/user';
jest.mock('@/services/user.service',()=>({ userService:{ getById:jest.fn(),update:jest.fn(),updatePassword:jest.fn() } }));
let mockId='123e4567-e89b-42d3-a456-426614174000';
const mockRouter={ push:jest.fn(),back:jest.fn() };
jest.mock('next/navigation',()=>({ useRouter:()=>mockRouter,useParams:()=>({ id:mockId }) }));
const service=jest.mocked(userService), revision='a'.repeat(64), next='b'.repeat(64);
const row={ id:mockId,user_revision:revision,first_name:'Original',last_name:'User',email:'user@example.test',phone:'+111111111',role:'OPERADOR',is_active:true } as User;
beforeEach(()=>{ jest.clearAllMocks(); mockId=row.id; service.getById.mockResolvedValue(row); service.update.mockResolvedValue({ ...row,user_revision:next }); });
it('sends the loaded user revision',async()=>{
 render(<Page/>); fireEvent.change(await screen.findByDisplayValue('Original'),{ target:{ value:'Edited' } });
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await waitFor(()=>expect(service.update).toHaveBeenCalledWith(row.id,expect.objectContaining({ first_name:'Edited',expected_user_revision:revision })));
});
it('requires explicit reload after a conflict and then uses the new revision',async()=>{
 service.update.mockRejectedValueOnce(Object.assign(new Error('Changed'),{ response:{ status:409 } }));
 render(<Page/>); await screen.findByDisplayValue('Original'); fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await waitFor(()=>expect(screen.getByRole('button',{ name:/Guardar/ })).toBeDisabled());
 expect(service.getById).toHaveBeenCalledTimes(1);
 service.getById.mockResolvedValueOnce({ ...row,user_revision:next,first_name:'Current' });
 fireEvent.click(screen.getByRole('button',{ name:'Recargar usuario' })); await screen.findByDisplayValue('Current');
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await waitFor(()=>expect(service.update).toHaveBeenLastCalledWith(row.id,expect.objectContaining({ expected_user_revision:next,first_name:'Current' })));
});
it('ignores a stale load after moving to another user',async()=>{
 let finish!:(value:User)=>void; service.getById.mockReturnValueOnce(new Promise(resolve=>{ finish=resolve; }));
 const { rerender }=render(<Page/>); mockId='123e4567-e89b-42d3-a456-426614174001';
 service.getById.mockResolvedValueOnce({ ...row,id:mockId,user_revision:next,first_name:'Second' });
 rerender(<Page/>); await screen.findByDisplayValue('Second'); await act(async()=>finish(row));
 expect(screen.queryByDisplayValue('Original')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await waitFor(()=>expect(service.update).toHaveBeenCalledWith(mockId,expect.objectContaining({ expected_user_revision:next })));
});
it('does not permit saving a legacy response without revision',async()=>{
 service.getById.mockResolvedValueOnce({ ...row,user_revision:undefined }); render(<Page/>);
 await screen.findByDisplayValue('Original'); expect(screen.getByRole('button',{ name:/Guardar/ })).toBeDisabled();
});
it('reports partial success if the separate password operation fails',async()=>{
 service.updatePassword.mockRejectedValueOnce(new Error('Unavailable'));
 render(<Page/>); await screen.findByDisplayValue('Original');
 fireEvent.click(screen.getAllByRole('switch')[1]);
 for (const input of screen.getAllByPlaceholderText('••••••')) fireEvent.change(input,{ target:{ value:'NewPassword123!' } });
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await screen.findByText(/Los datos se guardaron, pero no se confirmó/);
 expect(screen.getByRole('button',{ name:/Guardar/ })).toBeDisabled();
 expect(service.update).toHaveBeenCalledTimes(1); expect(service.updatePassword).toHaveBeenCalledTimes(1);
 expect(service.getById).toHaveBeenCalledTimes(1); expect(mockRouter.push).not.toHaveBeenCalled();
});
it('allows correcting a duplicate email without replacing the observed user revision',async()=>{
 service.update.mockRejectedValueOnce(Object.assign(new Error('Conflict'),{ response:{ status:409,data:{ detail:{ code:'USER_EMAIL_CONFLICT',message:'El correo ya está registrado. Use otro correo' } } } }));
 render(<Page/>); await screen.findByDisplayValue('Original');
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await screen.findByText('El correo ya está registrado. Use otro correo');
 await waitFor(()=>expect(screen.getByRole('button',{ name:/Guardar/ })).toBeEnabled());
 fireEvent.change(screen.getByDisplayValue('user@example.test'),{ target:{ value:'free@example.com' } });
 fireEvent.click(screen.getByRole('button',{ name:/Guardar/ }));
 await waitFor(()=>expect(service.update).toHaveBeenLastCalledWith(row.id,expect.objectContaining({ email:'free@example.com',expected_user_revision:revision })));
 expect(service.getById).toHaveBeenCalledTimes(1);
});
