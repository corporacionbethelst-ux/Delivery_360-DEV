"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/authStore";
import {
  captureAuthSession,
  getCredentialGeneration,
  isCurrentAuthSession,
  onCredentialsChanged,
} from "@/lib/auth-session";
import { RequestScope } from "@/lib/request-scope";
import {
  DashboardMode,
  DashboardSnapshot,
  getOperationalDashboard,
} from "@/services/operational-dashboard.service";

type State = {
  key: string;
  data: DashboardSnapshot | null;
  loading: boolean;
  error: string | null;
};

export function useOperationalDashboard(mode: DashboardMode, days: number) {
  const { user, isAuthenticated, sessionRevision } = useAuthStore();
  const generation = useSyncExternalStore(
    onCredentialsChanged,
    getCredentialGeneration,
    () => 0,
  );
  const allowed =
    isAuthenticated &&
    !!user &&
    (user.role === "SUPERADMIN" ||
      user.role === "GERENTE" ||
      (mode === "operator" && user.role === "OPERADOR"));
  const key = `${isAuthenticated}:${user?.id}:${user?.role}:${sessionRevision}:${generation}:${mode}:${days}`;
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<State>({
    key: "",
    data: null,
    loading: false,
    error: null,
  });
  const refresh = useCallback(() => setReload((value) => value + 1), []);

  useEffect(() => {
    const scope = new RequestScope();
    let active = true;
    setState({ key, data: null, loading: allowed, error: null });
    if (allowed) {
      const session = captureAuthSession();
      if (!session.accessToken) {
        setState({
          key,
          data: null,
          loading: false,
          error: "La sesión no está disponible. Vuelve a iniciar sesión.",
        });
      } else {
        void scope
          .run((signal) => getOperationalDashboard(mode, days, signal))
          .then(
            (data) => {
              if (active && isCurrentAuthSession(session))
                setState({ key, data, loading: false, error: null });
            },
            () => {
              if (active && isCurrentAuthSession(session))
                setState({
                  key,
                  data: null,
                  loading: false,
                  error:
                    "No se pudieron consultar las métricas. Intenta actualizar.",
                });
            },
          );
      }
    }
    return () => {
      active = false;
      scope.cancelAll();
    };
  }, [key, allowed, mode, days, reload]);

  return {
    allowed,
    refresh,
    data: allowed && state.key === key ? state.data : null,
    loading: allowed && (state.key !== key || state.loading),
    error: allowed && state.key === key ? state.error : null,
  };
}
