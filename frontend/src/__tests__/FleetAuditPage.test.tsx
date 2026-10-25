import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/admin/audit/page';
import { auditService, type AuditLog } from '@/services/audit.service';
jest.mock('@/services/audit.service', () => ({ auditService: { getLogs:jest.fn(), getSummary:jest.fn(), exportCsv:jest.fn() } }));
const service = jest.mocked(auditService);
const actor = '123e4567-e89b-42d3-a456-426614174000';
const base: AuditLog = { id:'event', action:'ASSIGN', status:'SUCCESS', success:true, resource_type:'Rider', resource_id:'rider', created_at:'2026-01-01T00:00:00Z' };
beforeEach(() => { jest.clearAllMocks(); service.getSummary.mockResolvedValue({ period_start:'2026-01-01', period_days:7, total:3, by_action:{ ASSIGN:3 }, by_success:{ true:3 } }); });

it('distinguishes an identified human without email from legacy email and system events', async () => {
  service.getLogs.mockResolvedValue({ items:[
    { ...base, id:'human', user_id:actor, user_email:null, user_role:'GERENTE' },
    { ...base, id:'legacy', user_email:'legacy@example.test', user_role:'GERENTE' },
    { ...base, id:'system', user_id:null, user_email:null, user_role:null },
  ], total:3, limit:50, offset:0 });
  render(<Page />);
  const human = (await screen.findByText(`Usuario ${actor}`)).closest('tr')!;
  expect(within(human).queryByText('SYSTEM')).not.toBeInTheDocument();
  expect(screen.getByText('legacy@example.test')).toBeInTheDocument();
  const systems = screen.getAllByText('SYSTEM');
  expect(systems).toHaveLength(2);
  expect(systems[0].closest('tr')).toBe(systems[1].closest('tr'));
});

it('uses the explicit fleet UTC timestamp and preserves the legacy fallback', async () => {
  const utc = '2026-10-25T11:00:00Z';
  service.getLogs.mockResolvedValue({ items:[
    { ...base, id:'new', user_id:actor, new_values:{ event_family:'RIDER_FLEET', occurred_at_utc:utc } },
    { ...base, id:'old', user_email:'legacy@example.test' },
  ], total:2, limit:50, offset:0 });
  render(<Page />);
  expect(await screen.findByText(new Date(utc).toLocaleString())).toBeInTheDocument();
  expect(screen.getByText(new Date(base.created_at!).toLocaleString())).toBeInTheDocument();
});
