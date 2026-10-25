import '@testing-library/jest-dom';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/admin/users/page';
import { userService } from '@/services/user.service';
import type { User } from '@/types/user';
jest.mock('@/services/user.service',()=>({ userService:{ getAll:jest.fn(),deactivate:jest.fn() } }));
const mockRouter={ push:jest.fn() };
let mockUser: { id:string;role:string;first_name?:string }={ id:'manager',role:'GERENTE' };
jest.mock('next/navigation',()=>({ useRouter:()=>mockRouter }));
jest.mock('@/stores/authStore',()=>({ useAuthStore:()=>({ user:mockUser,isAuthenticated:true }) }));
const service=jest.mocked(userService), revision='a'.repeat(64), next='b'.repeat(64);
const row={ id:'target',user_revision:revision,first_name:'Original',last_name:'User',email:'target@example.test',role:'OPERADOR',is_active:true,created_at:'2026-10-25' } as User;
beforeEach(()=>{ jest.clearAllMocks(); mockUser={ id:'manager',role:'GERENTE' }; service.getAll.mockResolvedValue([row]); service.deactivate.mockResolvedValue(undefined); });
it('deactivates with the revision in the confirmation snapshot',async()=>{
 render(<Page/>); fireEvent.click(await screen.findByTitle('Desactivar usuario'));
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, desactivar/ }));
 await waitFor(()=>expect(service.deactivate).toHaveBeenCalledWith(row.id,revision));
});
it('freezes the confirmation revision across a list refresh',async()=>{
 const { rerender }=render(<Page/>); fireEvent.click(await screen.findByTitle('Desactivar usuario'));
 service.getAll.mockResolvedValueOnce([{ ...row,user_revision:next,first_name:'Current' }]);
 mockUser={ ...mockUser,first_name:'Refreshed manager' }; rerender(<Page/>);
 await waitFor(()=>expect(service.getAll).toHaveBeenCalledTimes(2));
 expect(within(screen.getByRole('dialog')).getByText(/Original User/)).toBeInTheDocument();
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, desactivar/ }));
 await waitFor(()=>expect(service.deactivate).toHaveBeenCalledWith(row.id,revision));
});
it('blocks retries after a conflict until the confirmation is closed and reloaded',async()=>{
 service.deactivate.mockRejectedValueOnce(Object.assign(new Error('Changed'),{ response:{ status:409 } }));
 render(<Page/>); fireEvent.click(await screen.findByTitle('Desactivar usuario'));
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, desactivar/ }));
 const close=await screen.findByRole('button',{ name:'Cerrar y actualizar' });
 expect(within(screen.getByRole('dialog')).getByRole('button',{ name:/Sí, desactivar/ })).toBeDisabled();
 fireEvent.click(close); await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
 expect(service.deactivate).toHaveBeenCalledTimes(1);
});
