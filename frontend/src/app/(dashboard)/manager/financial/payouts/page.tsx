'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { payoutService, Payout } from '@/services/payout.service';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Wallet, Users, DollarSign, CheckCircle, Clock, AlertCircle, 
  Search, Filter, Eye, Download, TrendingUp, Loader2 
} from 'lucide-react';
import { formatCurrency } from '@/lib/formatters';

interface PayoutWithRider extends Payout {
  riderName?: string;
}

export default function PayoutsPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [payouts, setPayouts] = useState<PayoutWithRider[]>([]);
  const [loadingData, setLoadingData] = useState(true);
  const [filterStatus, setFilterStatus] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated) return;
    loadPayouts();
  }, [isAuthenticated, isMounted]);

  const loadPayouts = async () => {
    setLoadingData(true);
    try {
      const data = await payoutService.getAll({ limit: 100 });
      setPayouts(data);
    } catch (error) {
      console.error('Error loading payouts:', error);
    } finally {
      setLoadingData(false);
    }
  };

  const filteredPayouts = payouts.filter(p => {
    const matchesSearch = p.rider_id?.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          p.id?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = filterStatus === 'ALL' || p.status === filterStatus;
    return matchesSearch && matchesStatus;
  });

  const totalPending = payouts.filter(p => p.status === 'PENDIENTE').reduce((acc, curr) => acc + curr.amount, 0);
  const pendingCount = payouts.filter(p => p.status === 'PENDIENTE').length;

  if (!isMounted || !isAuthenticated || loadingData) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600 mr-4" />
        <p className="text-gray-600 font-medium">Cargando pagos...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Wallet className="w-6 h-6 text-green-600" />
              Pagos a Repartidores
            </h1>
            <p className="text-gray-500 mt-1">Gestiona y aprueba los pagos semanales</p>
          </div>
          <Button className="bg-green-600 hover:bg-green-700" disabled={totalPending === 0}>
            <CheckCircle className="w-4 h-4 mr-2" /> Aprobar Todos ({pendingCount})
          </Button>
        </div>

        {/* Resumen Superior */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card className="border-l-4 border-l-green-500">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-500">Por Pagar esta Semana</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-green-700">{formatCurrency(totalPending)}</div>
              <p className="text-xs text-gray-500 mt-1">{pendingCount} repartidores pendientes</p>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-blue-500">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-500">Total Pagado (Mes)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-blue-700">$2.450.000</div>
              <p className="text-xs text-gray-500 mt-1 flex items-center gap-1"><TrendingUp className="w-3 h-3" /> +12% vs mes anterior</p>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-orange-500">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-500">Observaciones</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-orange-700">{MOCK_PAYOUTS.filter(p => p.status === 'RECHAZADO').length}</div>
              <p className="text-xs text-gray-500 mt-1">Pagos rechazados o con errores</p>
            </CardContent>
          </Card>
        </div>

        {/* Filtros y Lista */}
        <Card>
          <CardHeader>
            <div className="flex flex-col md:flex-row justify-between gap-4">
              <div>
                <CardTitle>Solicitudes de Pago</CardTitle>
                <CardDescription>Revisa el detalle antes de aprobar</CardDescription>
              </div>
              <div className="flex gap-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                  <input 
                    type="text" 
                    placeholder="Buscar repartidor..." 
                    className="pl-9 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 outline-none"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                </div>
                <select 
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-green-500 outline-none"
                >
                  <option value="ALL">Todos</option>
                  <option value="PENDIENTE">Pendientes</option>
                  <option value="PROCESADO">Procesados</option>
                  <option value="RECHAZADO">Rechazados</option>
                </select>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {filteredPayouts.map((payout) => (
                <div key={payout.id} className="flex flex-col md:flex-row items-center justify-between p-4 border rounded-lg hover:shadow-md transition-shadow bg-white">
                  <div className="flex items-center gap-4 w-full md:w-auto mb-4 md:mb-0">
                    <div className="w-12 h-12 rounded-full bg-green-100 text-green-700 flex items-center justify-center font-bold text-lg">
                      {payout.riderName.charAt(0)}
                    </div>
                    <div>
                      <h3 className="font-bold text-gray-900">{payout.riderName}</h3>
                      <p className="text-sm text-gray-500">ID: {payout.riderId} • {payout.ordersCount} entregas</p>
                      <p className="text-xs text-gray-400">Periodo: {payout.period}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-6 w-full md:w-auto justify-between md:justify-end">
                    <div className="text-right">
                      <div className="text-xs text-gray-500">Monto a pagar</div>
                      <div className="text-xl font-bold text-gray-900">{formatCurrency(payout.amount)}</div>
                    </div>
                    
                    <div className="flex gap-2">
                      {payout.status === 'PENDIENTE' && (
                        <>
                          <Button variant="outline" size="sm" className="text-blue-600 border-blue-200">
                            <Eye className="w-4 h-4" />
                          </Button>
                          <Button size="sm" className="bg-green-600 hover:bg-green-700">
                            Aprobar
                          </Button>
                        </>
                      )}
                      {payout.status === 'PROCESADO' && (
                        <Badge className="bg-green-100 text-green-800 border-green-200">
                          <CheckCircle className="w-3 h-3 mr-1" /> Pagado
                        </Badge>
                      )}
                      {payout.status === 'RECHAZADO' && (
                        <Badge variant="destructive">
                          <AlertCircle className="w-3 h-3 mr-1" /> Rechazado
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}