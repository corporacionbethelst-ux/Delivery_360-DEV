'use client';

import { PayoutSessionBoundary } from '@/components/financial/PayoutSessionBoundary';
import { usePayoutPages, PAYOUT_FILTER_STATUSES } from '@/hooks/usePayoutPages';
import { PayoutPageControls } from '@/components/financial/PayoutPageControls';
import { capturePrivateTask } from '@/lib/private-task';

import { useEffect, useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DollarSign,
  Search,
  Filter,
  Download,
  Eye,
  CheckCircle,
  Clock,
  XCircle,
  RefreshCw, // MODIFICACIÓN: Importar ícono de actualizar
} from 'lucide-react';
import { payoutAmountLabel, payoutCents } from '@/lib/payout-contract';
import { payoutService } from '@/services/payout.service';
import { riderService } from '@/services/rider.service';
import type { PayoutWithRider } from '@/types/payout';
import type { Rider } from '@/types/user';
import Link from 'next/link';

export default function ManagerPayoutsPage() {
  return <PayoutSessionBoundary><PayoutContent /></PayoutSessionBoundary>;
}

function PayoutContent() {
  const page = usePayoutPages();
  const payouts = page.rows;
  const [riderNames, setRiderNames] = useState<{ revision: number; data: Record<string, Rider>; missing: boolean }>({ revision: -1, data: {}, missing: false });
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    if (!page.loaded) return;
    let active = true;
    let task: ReturnType<typeof capturePrivateTask>;
    try { task = capturePrivateTask(); } catch { return; }
    const current = () => active && task.isCurrent();
    void (async () => {
      const ids = Array.from(new Set(payouts.map(p => p.rider_id)));
      const rows = await Promise.all(ids.map(async id => {
        try {
          task.assertCurrent();
          const rider = await riderService.getById(id);
          return rider?.id === id ? { id, rider } : null;
        } catch { return null; }
      }));
      if (!current()) return;
      const data: Record<string, Rider> = {};
      rows.forEach(row => { if (row) data[row.id] = row.rider; });
      setRiderNames({ revision: page.revision, data, missing: rows.some(row => row === null) });
    })();
    return () => { active = false; };
  }, [page.loaded, page.revision, payouts]);

  const ridersMap = riderNames.revision === page.revision ? riderNames.data : {};
  const metrics = useMemo(() => ({
    completedAmount: payouts.filter(p => p.status === 'COMPLETADO' && p.currency === 'USD').reduce((cents, p) => cents + payoutCents(p.amount), 0) / 100,
    pendingCount: payouts.filter(p => p.status === 'PENDIENTE').length,
    processedCount: payouts.filter(p => p.status === 'COMPLETADO').length,
    rejectedCount: payouts.filter(p => p.status === 'RECHAZADO').length,
  }), [payouts]);

  const filteredPayouts = payouts.filter((payout) => {
    const rider = ridersMap[payout.rider_id];

    const firstName = rider?.first_name || '';
    const lastName = rider?.last_name || '';
    const riderName = `${firstName} ${lastName}`.trim() || `ID: ${payout.rider_id}`;
    const riderEmail = rider?.email || '';

    const matchesSearch =
      searchTerm === '' ||
      payout.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      riderName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      riderEmail.toLowerCase().includes(searchTerm.toLowerCase());

    return matchesSearch;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'APROBADO':
        return <Badge className="bg-blue-100 text-blue-800">Aprobado</Badge>;
      case 'EN_PROCESO':
        return <Badge className="bg-blue-100 text-blue-800">En proceso</Badge>;
      case 'COMPLETADO':
        return <Badge className="bg-green-100 text-green-800">Completado</Badge>;
      case 'FALLIDO':
        return <Badge className="bg-red-100 text-red-800">Fallido</Badge>;
      case 'PROCESADO':
        return <Badge className="bg-green-100 text-green-800">Procesado</Badge>;
      case 'PENDIENTE':
        return <Badge className="bg-yellow-100 text-yellow-800">Pendiente</Badge>;
      case 'RECHAZADO':
        return <Badge className="bg-red-100 text-red-800">Rechazado</Badge>;
      case 'CANCELADO':
        return <Badge className="bg-gray-100 text-gray-800">Cancelado</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  const formatCurrency = payoutAmountLabel;

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Fecha no informada';
    return new Date(dateString).toLocaleDateString('es-CO', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (!page.loaded && page.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
          <p className="mt-4 text-muted-foreground">Cargando pagos...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PayoutPageControls page={page} />
      <p className="text-sm text-muted-foreground">El estado se aplica a todo el historial. La búsqueda y las cifras corresponden a esta página.</p>
      {riderNames.revision === page.revision && riderNames.missing && <p role="status">Algunos datos de repartidores no están disponibles; puedes revisar sus IDs en el detalle.</p>}
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Gestión de Pagos a Repartidores</h1>
          <p className="text-muted-foreground">Administra retiros y liquidaciones</p>
        </div>
        <div className="flex gap-2">
          {/* MODIFICACIÓN: Botón Actualizar agregado */}
          <Button 
            variant="outline" 
            onClick={() => { void page.refresh(); }}
            disabled={page.isLoading}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${page.isLoading ? 'animate-spin' : ''}`} />
            Actualizar
          </Button>
          <Button variant="outline" onClick={() => window.print()}>
            <Download className="w-4 h-4 mr-2" />
            Exportar Reporte
          </Button>
        </div>
      </div>

      <div className="rounded-xl border border-indigo-200 bg-gradient-to-r from-indigo-50 to-blue-50 p-4 text-sm text-indigo-950">
        <strong>Contabilidad USD</strong> · El total monetario incluye solo retiros identificados en USD.
        Los registros sin moneda se conservan para revisión y no se suman a este total.
      </div>
      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completados en esta página</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{page.loaded ? formatCurrency(metrics.completedAmount, "USD") : 'No disponible'}</div>
            <p className="text-xs text-muted-foreground">Importe de los retiros con estado completado</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pendientes</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{page.loaded ? metrics.pendingCount : 'No disponible'}</div>
            <p className="text-xs text-muted-foreground">Solicitudes por revisar</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Procesados</CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{page.loaded ? metrics.processedCount : 'No disponible'}</div>
            <p className="text-xs text-muted-foreground">Retiros completados</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Rechazados</CardTitle>
            <XCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{page.loaded ? metrics.rejectedCount : 'No disponible'}</div>
            <p className="text-xs text-muted-foreground">Con incidencias</p>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="w-5 h-5" />
            Filtros y Búsqueda
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-4 h-4" />
              <Input
                placeholder="Buscar en esta página por ID, nombre o email..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select value={page.selectedStatus} onValueChange={value => { setSearchTerm(''); void page.setStatus(value); }}>
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder="Estado" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Todos los estados</SelectItem>
                {PAYOUT_FILTER_STATUSES.map(status => <SelectItem key={status} value={status}>{status.replaceAll('_', ' ')}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Payouts Table */}
      <Card>
        <CardHeader>
          <CardTitle>Historial de Pagos</CardTitle>
        </CardHeader>
        <CardContent>
          {filteredPayouts.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <DollarSign className="w-12 h-12 mx-auto mb-4 opacity-20" />
              <p>{!page.loaded ? 'No se pudo comprobar el historial.' : searchTerm ? 'Sin coincidencias en esta página. Puedes cambiar de página o limpiar la búsqueda.' : 'No hay retiros en esta página con el estado elegido.'}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Repartidor</TableHead>
                  <TableHead>Monto Total</TableHead>
                  <TableHead>Órdenes</TableHead>
                  <TableHead>Período</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Fecha Solicitud</TableHead>
                  <TableHead>Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredPayouts.map((payout) => {
                  const rider = ridersMap[payout.rider_id];
                  
                  // ✅ Construir nombre completo correctamente
                  const firstName = rider?.first_name || '';
                  const lastName = rider?.last_name || '';
                  const riderName = `${firstName} ${lastName}`.trim() || `ID: ${payout.rider_id}`;
                  const riderInitial = riderName.charAt(0).toUpperCase();

                  return (
                    <TableRow key={payout.id}>
                      <TableCell className="font-mono text-xs">
                        {payout.id.slice(0, 8)}...
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-medium text-sm">
                            {riderInitial}
                          </div>
                          <div>
                            <div className="font-medium">{riderName}</div>
                            <div className="text-xs text-muted-foreground">
                              {rider?.email || 'Sin email'}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="font-semibold">
                        {formatCurrency(payout.amount, payout.currency)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{payout.orders_count === undefined ? 'Cantidad no informada' : `${payout.orders_count} órdenes`}</Badge>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {payout.period_start && payout.period_end
                          ? `${new Date(payout.period_start).toLocaleDateString()} - ${new Date(payout.period_end).toLocaleDateString()}`
                          : 'N/A'}
                      </TableCell>
                      <TableCell>{getStatusBadge(payout.status)}</TableCell>
                      <TableCell className="text-sm">
                        {formatDate(payout.created_at)}
                      </TableCell>
                      <TableCell>
                        <Link href={`/manager/financial/payouts/${payout.id}`}>
                          <Button variant="ghost" size="sm">
                            <Eye className="w-4 h-4" />
                          </Button>
                        </Link>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}