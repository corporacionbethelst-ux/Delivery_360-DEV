'use client';

import { useEffect, useState } from 'react';
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
} from 'lucide-react';
import { payoutService } from '@/services/payout.service';
import { riderService } from '@/services/rider.service';
import type { PayoutWithRider } from '@/types/payout';
import type { Rider } from '@/types/user'; // ✅ Importar desde user.ts como definiste
import Link from 'next/link';

// Tipos locales para estados derivados
interface PayoutMetrics {
  totalPaidMonth: number;
  pendingCount: number;
  approvedCount: number;
  rejectedCount: number;
}

export default function ManagerPayoutsPage() {
  const [payouts, setPayouts] = useState<PayoutWithRider[]>([]);
  const [ridersMap, setRidersMap] = useState<Record<string, Rider>>({});
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [metrics, setMetrics] = useState<PayoutMetrics>({
    totalPaidMonth: 0,
    pendingCount: 0,
    approvedCount: 0,
    rejectedCount: 0,
  });

  // Cargar datos iniciales
  useEffect(() => {
    loadPayouts();
  }, []);

  const loadPayouts = async () => {
    try {
      setLoading(true);
      const data = await payoutService.getAll();
      
      // Ahora 'data' es compatible con PayoutWithRider porque las propiedades coinciden
      const riderIds = [...new Set(data.map((p) => p.rider_id))]; 
      
      const ridersData = await Promise.all(
        riderIds.map((id) => riderService.getById(id).catch(() => null))
      );

      const ridersMapTemp: Record<string, Rider> = {};
      ridersData.forEach((rider) => {
        if (rider) {
          ridersMapTemp[rider.id] = rider;
        }
      });

      setRidersMap(ridersMapTemp);
      // Asegurar que los objetos cumplan con PayoutWithRider
      const mappedData: PayoutWithRider[] = data.map((p: any) => ({
        ...p,
        total_amount: p.total_amount ?? p.totalAmount ?? 0,
        orders_count: p.orders_count ?? p.ordersCount ?? 0,
        created_at: p.created_at ?? p.createdAt ?? new Date().toISOString(),
        updated_at: p.updated_at ?? p.updatedAt ?? new Date().toISOString(),
      }));

      setPayouts(mappedData);
      calculateMetrics(mappedData);
    } catch (error) {
      console.error('Error loading payouts:', error);
    } finally {
      setLoading(false);
    }
  };

  const calculateMetrics = (data: PayoutWithRider[]) => {
    const currentMonth = new Date().getMonth();
    const currentYear = new Date().getFullYear();

    const paidThisMonth = data
      .filter((p) => {
        const payoutDate = new Date(p.created_at);
        return (
          p.status === 'paid' &&
          payoutDate.getMonth() === currentMonth &&
          payoutDate.getFullYear() === currentYear
        );
      })
      .reduce((sum, p) => sum + (p.total_amount || 0), 0);

    setMetrics({
      totalPaidMonth: paidThisMonth,
      pendingCount: data.filter((p) => p.status === 'pending').length,
      approvedCount: data.filter((p) => p.status === 'approved').length,
      rejectedCount: data.filter((p) => p.status === 'rejected').length,
    });
  };

  const filteredPayouts = payouts.filter((payout) => {
    const rider = ridersMap[payout.rider_id];
    
    // ✅ CORRECCIÓN: Rider extiende User, no tiene propiedad 'user' anidada.
    // Usamos first_name y last_name directamente.
    const firstName = rider?.first_name || '';
    const lastName = rider?.last_name || '';
    const riderName = `${firstName} ${lastName}`.trim() || 'Desconocido';
    const riderEmail = rider?.email || '';

    const matchesSearch =
      searchTerm === '' ||
      payout.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      riderName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      riderEmail.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesStatus = statusFilter === 'all' || payout.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'paid':
        return <Badge className="bg-green-100 text-green-800">Pagado</Badge>;
      case 'pending':
        return <Badge className="bg-yellow-100 text-yellow-800">Pendiente</Badge>;
      case 'approved':
        return <Badge className="bg-blue-100 text-blue-800">Aprobado</Badge>;
      case 'rejected':
        return <Badge className="bg-red-100 text-red-800">Rechazado</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency',
      currency: 'COP',
      minimumFractionDigits: 0,
    }).format(amount);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('es-CO', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
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
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Gestión de Pagos a Repartidores</h1>
          <p className="text-muted-foreground">Administra retiros y liquidaciones</p>
        </div>
        <Button variant="outline" onClick={() => window.print()}>
          <Download className="w-4 h-4 mr-2" />
          Exportar Reporte
        </Button>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pagado este Mes</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCurrency(metrics.totalPaidMonth)}</div>
            <p className="text-xs text-muted-foreground">Total aprobado y pagado</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pendientes</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.pendingCount}</div>
            <p className="text-xs text-muted-foreground">Solicitudes por revisar</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Aprobados</CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.approvedCount}</div>
            <p className="text-xs text-muted-foreground">Listos para pago</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Rechazados</CardTitle>
            <XCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.rejectedCount}</div>
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
                placeholder="Buscar por ID, nombre o email..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder="Estado" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos los estados</SelectItem>
                <SelectItem value="pending">Pendientes</SelectItem>
                <SelectItem value="approved">Aprobados</SelectItem>
                <SelectItem value="paid">Pagados</SelectItem>
                <SelectItem value="rejected">Rechazados</SelectItem>
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
              <p>No se encontraron pagos con los filtros actuales</p>
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
                  const riderName = `${firstName} ${lastName}`.trim() || 'Desconocido';
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
                        {formatCurrency(payout.total_amount || 0)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{payout.orders_count || 0} órdenes</Badge>
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