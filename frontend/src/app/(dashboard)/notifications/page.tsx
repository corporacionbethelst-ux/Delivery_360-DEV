/**
 * Fase 9 - Inbox de Notificaciones Omnicanal (todos los roles).
 *
 * - Paginación server-side: GET /notifications/inbox?page=&size=
 * - Filtros por canal (PUSH/SMS/EMAIL/IN_APP) y estado (PENDIENTE/ENVIADO/ENTREGADO/FALLIDO/LEIDO)
 *   => el filtro de listado es client-side sobre la página cargada; el backend ya filtra
 *      IN_APP por defecto (include_all_channels=true para ver todos los canales).
 * - Marcar leído: PATCH /notifications/{id}/read con optimistic update (vía useNotifications)
 * - Eliminar: DELETE /notifications/{id} (borrado lógico, solo dueño)
 * - Gate: NEXT_PUBLIC_FEATURE_NOTIFICATIONS=false oculta la página (enlaza a login-safe empty state)
 */
'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, Trash2, Loader2, AlertCircle, RefreshCw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useNotifications, InboxNotification } from '@/hooks/useNotifications';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
const CHANNELS = ['IN_APP', 'PUSH', 'EMAIL', 'SMS'] as const;
const STATUSES = ['PENDIENTE', 'ENVIADO', 'ENTREGADO', 'FALLIDO', 'LEIDO'] as const;

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

export default function NotificationsInboxPage() {
  const featureEnabled = process.env.NEXT_PUBLIC_FEATURE_NOTIFICATIONS !== 'false';
  const [page, setPage] = useState(1);
  const [size] = useState(10);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [rows, setRows] = useState<InboxNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [channelFilter, setChannelFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // WS en vivo + badge global (campana e inbox comparten UNA sola conexión lógica del hook)
  const { markRead, refreshInbox } = useNotifications({ enabled: true });

  const loadPage = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/notifications/inbox?page=${p}&size=${size}&include_all_channels=true`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRows((data.items ?? []) as InboxNotification[]);
      setTotal(Number(data.total ?? 0));
      setTotalPages(Number(data.pages ?? 1) || 1);
    } catch (e) {
      console.error('inbox:', e);
    } finally {
      setLoading(false);
    }
  }, [size]);

  useEffect(() => {
    if (featureEnabled) loadPage(page);
  }, [featureEnabled, page, loadPage]);

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (!channelFilter || r.channel === channelFilter) &&
          (!statusFilter || r.status === statusFilter)
      ),
    [rows, channelFilter, statusFilter]
  );

  const handleDelete = async (id: string) => {
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/notifications/${id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows((prev) => prev.filter((r) => r.id !== id));
      setDeleteError(null);
      refreshInbox();
    } catch (e) {
      setDeleteError('No se pudo eliminar la notificación');
    }
  };

  if (!featureEnabled) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6 text-center text-gray-500">
            Las notificaciones están deshabilitadas en este entorno.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Bell className="w-5 h-5" /> Notificaciones
        </h1>
        <Button variant="outline" size="sm" onClick={() => loadPage(page)} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Actualizar
        </Button>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap gap-2">
        <select
          className="border rounded-md px-3 py-1.5 text-sm bg-white"
          value={channelFilter}
          onChange={(e) => setChannelFilter(e.target.value)}
          aria-label="Filtrar por canal"
        >
          <option value="">Todos los canales</option>
          {CHANNELS.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select
          className="border rounded-md px-3 py-1.5 text-sm bg-white"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filtrar por estado"
        >
          <option value="">Todos los estados</option>
          {STATUSES.map((s) => (<option key={s} value={s}>{s}</option>))}
        </select>
        <Link href="/notifications/preferences" className="ml-auto">
          <Button variant="ghost" size="sm">Preferencias</Button>
        </Link>
      </div>

      {deleteError && (
        <div className="text-sm text-red-600 flex items-center gap-1">
          <AlertCircle className="w-4 h-4" /> {deleteError}
        </div>
      )}

      {/* Lista */}
      <div className="space-y-2">
        {filtered.length === 0 && !loading && (
          <Card><CardContent className="p-8 text-center text-gray-500">
            Sin notificaciones para mostrar.
          </CardContent></Card>
        )}
        {filtered.map((n) => (
          <Card key={n.id} className={n.status === 'LEIDO' ? 'opacity-70' : ''}>
            <CardContent className="p-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium truncate">{n.title || n.template_code || 'Notificación'}</span>
                  <Badge variant="secondary" className="text-xs">{n.channel}</Badge>
                  <Badge
                    variant={n.status === 'FALLIDO' ? 'destructive' : n.status === 'LEIDO' ? 'outline' : 'default'}
                    className="text-xs"
                  >{n.status}</Badge>
                </div>
                <p className="text-sm text-gray-600 mt-1 line-clamp-2">{n.body}</p>
                {n.created_at && (
                  <p className="text-xs text-gray-400 mt-1">
                    {new Date(n.created_at).toLocaleString('es')}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1 shrink-0">
                {n.status !== 'LEIDO' && (
                  <Button variant="ghost" size="sm" title="Marcar leído" onClick={() => markRead(n.id)}>
                    <CheckCheck className="w-4 h-4" />
                  </Button>
                )}
                <Button variant="ghost" size="sm" title="Eliminar" onClick={() => handleDelete(n.id)}>
                  <Trash2 className="w-4 h-4 text-red-500" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {loading && (
          <div className="flex justify-center p-4"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
        )}
      </div>

      {/* Paginación */}
      <div className="flex items-center justify-between text-sm text-gray-600">
        <span>{total} notificaciones · página {page} de {totalPages}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
            Anterior
          </Button>
          <Button variant="outline" size="sm" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
            Siguiente
          </Button>
        </div>
      </div>
    </div>
  );
}
