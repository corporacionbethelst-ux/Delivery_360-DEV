"use client";
import {
  Fragment,
  useEffect,
  useSyncExternalStore,
  type PropsWithChildren,
} from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import {
  getCredentialGeneration,
  onCredentialsChanged,
} from "@/lib/auth-session";

export function ManagerPageBoundary({
  children,
  scope,
  pending = "Verificando acceso…",
  roles = ["GERENTE", "SUPERADMIN"],
}: PropsWithChildren<{
  scope: string;
  pending?: string;
  roles?: readonly string[];
}>) {
  const router = useRouter(),
    { user, isAuthenticated } = useAuthStore();
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  const allowed = isAuthenticated && !!user && roles.includes(user.role);
  useEffect(() => {
    if (!allowed) router.replace("/login");
  }, [allowed, router]);
  return allowed ? (
    <Fragment key={JSON.stringify([generation, user.id, user.role, scope])}>
      {children}
    </Fragment>
  ) : (
    <p role="status" className="p-6">
      {pending}
    </p>
  );
}
