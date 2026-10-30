"use client";

import { useCallback, useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Bell, CheckCircle, XCircle } from 'lucide-react';
import { alertService, type Alert, type AlertSeverity } from '@/services/alert.service';
import { formatAlertDate } from '@/lib/alert-date';

const severityLabels: Record<AlertSeverity, string> = {
  CRITICAL: 'Crítica', HIGH: 'Alta', MEDIUM: 'Media', LOW: 'Baja',
};
const severityColors: Record<AlertSeverity, string> = {
  CRITICAL: 'bg-red-100 text-red-800', HIGH: 'bg-orange-100 text-orange-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800', LOW: 'bg-blue-100 text-blue-800',
};

/** Personal inbox actions acknowledge reading; they do not resolve an operational SLA. */
export default function AlertPanel() {
  const [loading, setLoading] = useState(true);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState('all');
  const [showRead, setShowRead] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAlerts(await alertService.getAll({ status: showRead ? 'ALL' : 'UNREAD', limit: 100 }));
    } catch {
      setAlerts([]);
      setError('No se pudieron cargar las alertas. Intenta de nuevo.');
    } finally {
      setLoading(false);
    }
  }, [showRead]);
  useEffect(() => { void loadAlerts(); }, [loadAlerts]);

  async function act(id: string, action: 'read' | 'dismiss') {
    if (busy) return;
    setBusy(id);
    setError(null);
    try {
      if (action === 'read') await alertService.markAsRead(id);
      else await alertService.dismiss(id);
      await loadAlerts();
    } catch {
      setError('No se pudo actualizar la alerta. Intenta de nuevo.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Bell className="h-5 w-5" />Alertas</CardTitle>
        <div className="flex flex-wrap gap-2">
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-[160px]"><SelectValue placeholder="Severidad" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas las severidades</SelectItem>
              {Object.entries(severityLabels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => setShowRead(!showRead)} disabled={!!busy}>
            {showRead ? 'Solo no leídas' : 'Mostrar leídas'}
          </Button>
          <Button variant="outline" onClick={() => void loadAlerts()} disabled={loading || !!busy}>Actualizar</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        {loading ? <p>Cargando alertas...</p> : alerts.filter(a => filter === 'all' || a.severity === filter).map(alert => (
          <div key={alert.id} className={`rounded-lg border p-3 ${alert.isRead ? 'bg-muted opacity-70' : 'bg-background'}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{alert.title}</p>
                <Badge className={severityColors[alert.severity]}>{severityLabels[alert.severity]}</Badge>
                {alert.isRead && <Badge variant="secondary">Leída</Badge>}
                <p className="mt-1 text-sm text-muted-foreground">{alert.description}</p>
                <p className="mt-2 text-xs text-muted-foreground">{formatAlertDate(alert.createdAt)}</p>
              </div>
              <div className="flex gap-1">
                {!alert.isRead && <Button variant="outline" size="icon" title="Marcar como leída" disabled={!!busy} onClick={() => void act(alert.id, 'read')}><CheckCircle className="h-4 w-4" /></Button>}
                <Button variant="outline" size="icon" title="Descartar alerta" disabled={!!busy} onClick={() => void act(alert.id, 'dismiss')}><XCircle className="h-4 w-4" /></Button>
              </div>
            </div>
          </div>
        ))}
        {!loading && !error && !alerts.some(a => filter === 'all' || a.severity === filter) && <p className="text-sm text-muted-foreground">No hay alertas que mostrar.</p>}
      </CardContent>
    </Card>
  );
}
