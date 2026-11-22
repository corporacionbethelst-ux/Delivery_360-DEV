'use client';

import { SessionGate } from '@/components/layout/SessionGate';
import { useAuthStore } from '@/stores/authStore';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { ShieldCheck } from 'lucide-react';

export default function AccessUnavailable() {
  const logout = useAuthStore(state => state.logout);
  const router = useRouter();
  return <SessionGate><main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-blue-50 via-white to-violet-50 p-6">
    <section className="w-full max-w-lg rounded-2xl border border-blue-100 bg-white p-8 shadow-sm">
      <ShieldCheck className="mb-5 h-10 w-10 text-blue-600" aria-hidden="true" />
      <h1 className="text-2xl font-bold text-slate-900">Portal pendiente de habilitación</h1>
      <p className="mt-3 text-slate-600">Tu sesión está verificada, pero tu perfil aún no tiene un portal disponible. Contacta al administrador para revisar el acceso que corresponde a tu cuenta.</p>
      <Button className="mt-6 h-11 bg-blue-600" onClick={async () => { await logout(); router.replace('/login'); }}>Cerrar sesión</Button>
    </section>
  </main></SessionGate>;
}
