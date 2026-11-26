/** Verified API profile controls mounting; cookies are navigation hints only. */
export function canOpenDashboard(role: string | undefined, pathname: string): boolean {
  if (pathname === '/notifications') return !!role && ['SUPERADMIN', 'GERENTE', 'OPERADOR', 'REPARTIDOR', 'CLIENTE', 'AUDITOR'].includes(role);
  if (pathname === '/access-unavailable') return !!role && ['SUPERADMIN', 'GERENTE', 'OPERADOR', 'REPARTIDOR', 'CLIENTE', 'AUDITOR'].includes(role);
  const section = pathname.split('/')[1];
  if (section === 'manager' || section === 'operator') return ['SUPERADMIN', 'GERENTE', 'OPERADOR'].includes(role || '');
  return section === 'rider' && role === 'REPARTIDOR';
}
