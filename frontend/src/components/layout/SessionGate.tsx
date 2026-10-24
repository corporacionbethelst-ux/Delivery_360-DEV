'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';

/** Prevent dashboard pages and their effects from mounting before verification. */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { checkAuth, forceLogout, isAuthenticated, isLoading } = useAuthStore();
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    let active = true;
    void checkAuth().catch(() => forceLogout()).finally(() => {
      if (active) setChecked(true);
    });
    return () => { active = false; };
  }, [checkAuth, forceLogout]);
  useEffect(() => {
    if (checked && !isLoading && !isAuthenticated) router.replace('/login');
  }, [checked, isLoading, isAuthenticated, router]);
  if (!checked || isLoading) {
    return <div role="status" className="flex h-screen items-center justify-center">Verificando sesión…</div>;
  }
  return isAuthenticated ? <>{children}</> : null;
}
