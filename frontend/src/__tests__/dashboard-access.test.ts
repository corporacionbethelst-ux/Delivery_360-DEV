import { canOpenDashboard } from '@/lib/dashboard-access';
import { getLoginDestination } from '@/lib/login-destination';

it.each(['SUPERADMIN', 'GERENTE', 'OPERADOR', 'REPARTIDOR', 'CLIENTE', 'AUDITOR'])('isolates dashboard sections for %s', role => {
  expect(canOpenDashboard(role, '/manager/operations/orders')).toBe(['SUPERADMIN', 'GERENTE', 'OPERADOR'].includes(role));
  expect(canOpenDashboard(role, '/operator/orders')).toBe(['SUPERADMIN', 'GERENTE', 'OPERADOR'].includes(role));
  expect(canOpenDashboard(role, '/rider/deliveries')).toBe(role === 'REPARTIDOR');
  expect(canOpenDashboard(role, '/manager-other')).toBe(false);
  expect(canOpenDashboard(role, '/access-unavailable')).toBe(true);
  expect(canOpenDashboard(role, '/notifications')).toBe(true);
  expect(canOpenDashboard(role, '/notifications/preferences')).toBe(true);
  expect(canOpenDashboard(role, '/notifications/preferences/other')).toBe(false);
  expect(canOpenDashboard(role, '/notifications-other')).toBe(false);
});
it.each(['CLIENTE', 'AUDITOR', 'UNKNOWN'])('avoids manager login loops for %s', role => {
  expect(getLoginDestination(role, '/manager')).toBe('/access-unavailable');
  expect(canOpenDashboard(role, '/manager')).toBe(false);
});
it('rejects unknown verified roles and unknown protected sections', () => {
  expect(canOpenDashboard(undefined, '/rider')).toBe(false);
  expect(canOpenDashboard('UNKNOWN', '/access-unavailable')).toBe(false);
  expect(canOpenDashboard('SUPERADMIN', '/other')).toBe(false);
  expect(canOpenDashboard(undefined, '/notifications')).toBe(false);
  expect(canOpenDashboard('UNKNOWN', '/notifications')).toBe(false);
  expect(canOpenDashboard(undefined, '/notifications/preferences')).toBe(false);
  expect(canOpenDashboard('UNKNOWN', '/notifications/preferences')).toBe(false);
});
