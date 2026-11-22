'use client';

import React, { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { canOpenDashboard } from '@/lib/dashboard-access';
import { getLoginDestination } from '@/lib/login-destination';
import { useAuthStore } from '@/stores/authStore';

/** Prevent dashboard pages and their effects from mounting before verification. */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { checkAuth, forceLogout, isAuthenticated, isLoading, user } = useAuthStore();
  const allowed = !!pathname && canOpenDashboard(user?.role, pathname);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    window.addEventListener('delivery360-session-expired', forceLogout);
    return () => window.removeEventListener('delivery360-session-expired', forceLogout);
  }, [forceLogout]);
  useEffect(() => {
    let active = true;
    void checkAuth().catch(() => forceLogout()).finally(() => {
      if (active) setChecked(true);
    });
    return () => { active = false; };
  }, [checkAuth, forceLogout]);
  useEffect(() => {
    if (checked && !isLoading && !isAuthenticated) router.replace('/login');
    else if (checked && !isLoading && isAuthenticated && !allowed) router.replace(getLoginDestination(user?.role || ''));
  }, [checked, isLoading, isAuthenticated, allowed, user?.role, router]);
  if (!checked || isLoading) {
    return <div role="status" className="flex h-screen items-center justify-center">Verificando sesión…</div>;
  }
  return isAuthenticated && allowed ? <>{children}</> : null;
}
