/**
 * Fase 9 - Preferencias de notificación (tabla editable evento x canal).
 *
 * - GET  /notifications/preferences  -> estado actual del usuario
 * - PUT  /notifications/preferences  -> upsert granular ({preferences:[{event_code,channel,enabled}]})
 * - Eventos disponibles = códigos de plantilla activos: GET /notifications/templates (admin list)
 *   con fallback a los 6 eventos sembrados de la Fase 9.
 * - Regla por rol espejada del backend (informativa en UI): riders solo PUSH/IN_APP;
 *   managers PUSH/EMAIL/IN_APP; clientes IN_APP/EMAIL.
 */
'use client';

import { useCallback, useEffect, useState } from 'react';
import { Loader2, Save, CheckCircle2, Bell } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// Los 6 eventos sembrados en la migración 20260915_fase9 (fallback si /templates falla)
const DEFAULT_EVENTS = [
  'payout_aprobado',
  'payout_rechazado',
  'payout_fallido',
  'nuevo_pedido_asignado',
  'alerta_desviacion_ruta',
  'resumen_diario_manager',
];

const ALL_CHANNELS = ['IN_APP', 'PUSH', 'EMAIL', 'SMS'] as const;

type PrefsMap = Record<string, Record<string, boolean>>; // event -> channel -> enabled

function getToken(): string | null {
  try {
    const raw = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed?.token || parsed?.access_token || raw;
    } catch {
      return raw;
    }
  } catch {
    return null;
  }
}

async function apiFetch(path: string, init: RequestInit = {}) {
  const token = getToken();
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
}

export default function NotificationPreferencesPage() {
  const featureEnabled = process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS !== 'false';
  const [events, setEvents] = useState<string[]>(DEFAULT_EVENTS);
  const [allowedChannels, setAllowedChannels] = useState<string[]>(['IN_APP', 'PUSH', 'EMAIL']);
  const [prefs, setPrefs] = useState<PrefsMap>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1) Plantillas activas para conocer los eventos reales
      try {
        const tRes = await apiFetch('/notifications/templates');
        if (tRes.ok) {
          const tData = await tRes.json();
          const codes: string[] = Array.from(
            new Set<string>((tData.templates ?? tData ?? []).map((t: { code?: string }) => t.code).filter(Boolean))
          );
          if (codes.length > 0) setEvents(codes);
        }
      } catch { /* usar defaults */ }

      // 2) Rol del usuario (para limitar canales editables, espejo de regla backend)
      let role = '';
      try {
        const userStr = typeof window !== 'undefined' ? localStorage.getItem('user') : null;
        role = userStr ? (JSON.parse(userStr)?.role ?? '') : '';
      } catch { /* noop */ }
      if (role === 'REPARTIDOR') setAllowedChannels(['IN_APP', 'PUSH']);
      else if (role === 'GERENTE' || role === 'SUPERADMIN') setAllowedChannels(['IN_APP', 'PUSH', 'EMAIL']);
      else setAllowedChannels(['IN_APP', 'EMAIL', 'PUSH']);

      // 3) Preferencias actuales
      const pRes = await apiFetch('/notifications/preferences');
      if (!pRes.ok) throw new Error(`HTTP ${pRes.status}`);
      const pData = await pRes.json();
      const map: PrefsMap = {};
      for (const p of pData.preferences ?? []) {
        map[p.event_code] = { ...(map[p.event_code] ?? {}), [p.channel]: !!p.enabled };
      }
      setPrefs(map);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (featureEnabled) load();
  }, [featureEnabled, load]);

  const toggle = (eventCode: string, channel: string) => {
    setSavedAt(null);
    setPrefs((prev) => ({
      ...prev,
      [eventCode]: { ...(prev[eventCode] ?? {}), [channel]: !(prev[eventCode]?.[channel] ?? true) },
    }));
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = {
        preferences: Object.entries(prefs).flatMap(([event_code, chans]) =>
          Object.entries(chans).map(([channel, enabled]) => ({ event_code, channel, enabled }))
        ),
      };
      const res = await apiFetch('/notifications/preferences', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSavedAt(new Date().toLocaleTimeString('es'));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!featureEnabled) {
    return (
      <div className="p-6">
        <Card><CardContent className="p-6 text-center text-gray-500">
          Las notificaciones están deshabilitadas en este entorno.
        </CardContent></Card>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Bell className="w-5 h-5" /> Preferencias de notificación
        </h1>
        <Button size="sm" onClick={save} disabled={saving || loading}>
          {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
          Guardar
        </Button>
      </div>

      {savedAt && (
        <div className="text-sm text-green-700 flex items-center gap-1">
          <CheckCircle2 className="w-4 h-4" /> Preferencias guardadas a las {savedAt}
        </div>
      )}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
                <th className="p-3 font-medium">Evento</th>
                {ALL_CHANNELS.filter((c) => allowedChannels.includes(c)).map((c) => (
                  <th key={c} className="p-3 font-medium text-center">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5} className="p-8 text-center"><Loader2 className="inline w-5 h-5 animate-spin" /></td></tr>
              ) : (
                events.map((ev) => (
                  <tr key={ev} className="border-b last:border-0">
                    <td className="p-3 font-mono text-xs">{ev}</td>
                    {ALL_CHANNELS.filter((c) => allowedChannels.includes(c)).map((ch) => {
                      const enabled = prefs[ev]?.[ch] ?? true; // default True como en el modelo
                      return (
                        <td key={ch} className="p-3 text-center">
                          <input
                            type="checkbox"
                            checked={enabled}
                            onChange={() => toggle(ev, ch)}
                            className="w-4 h-4 accent-blue-600 cursor-pointer"
                            aria-label={`${ev}/${ch}`}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <p className="text-xs text-gray-500">
        Los canales disponibles dependen de tu rol. Por defecto todos los eventos están habilitados.
      </p>
    </div>
  );
}
