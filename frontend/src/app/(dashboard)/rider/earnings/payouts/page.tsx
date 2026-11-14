'use client';

import { PayoutSessionBoundary } from '@/components/financial/PayoutSessionBoundary';
import { usePayoutPages, PAYOUT_FILTER_STATUSES } from '@/hooks/usePayoutPages';
import { PayoutPageControls } from '@/components/financial/PayoutPageControls';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { payoutDateLabel, payoutAmountLabel } from '@/lib/payout-contract';
import { PayoutMethod, PayoutStatus } from '@/services/payout.service';
import { formatDate } from '@/lib/formatters';
import { ArrowLeft, Clock, CheckCircle, XCircle, Ban, Wallet, Loader2, AlertCircle, FileText } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

const STATUS_CONFIG: Record<PayoutStatus, { label: string; color: string; icon: any; bg: string }> = {
  APROBADO: { label: 'Aprobado', color: 'text-blue-700', icon: Clock, bg: 'bg-blue-100' },
  EN_PROCESO: { label: 'En proceso', color: 'text-blue-700', icon: Loader2, bg: 'bg-blue-100' },
  COMPLETADO: { label: 'Completado', color: 'text-emerald-700', icon: CheckCircle, bg: 'bg-emerald-100' },
  FALLIDO: { label: 'Fallido', color: 'text-red-700', icon: AlertCircle, bg: 'bg-red-100' },
  PENDIENTE: { label: 'Pendiente', color: 'text-amber-700', icon: Clock, bg: 'bg-amber-100' },
  PROCESADO: { label: 'Procesado', color: 'text-emerald-700', icon: CheckCircle, bg: 'bg-emerald-100' },
  RECHAZADO: { label: 'Rechazado', color: 'text-red-700', icon: XCircle, bg: 'bg-red-100' },
  CANCELADO: { label: 'Cancelado', color: 'text-gray-700', icon: Ban, bg: 'bg-gray-100' },
};

const METHOD_LABELS: Record<PayoutMethod, string> = {
  TRANSFERENCIA: 'Transferencia Bancaria',
  EFECTIVO: 'Efectivo',
  BILLETERA_DIGITAL: 'Billetera Digital',
};

export default function RiderPayoutsPage() {
  return <PayoutSessionBoundary><PayoutContent /></PayoutSessionBoundary>;
}

function PayoutContent() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  const [isMounted, setIsMounted] = useState(false);
  const page = usePayoutPages(isMounted && isAuthenticated && user?.role === 'REPARTIDOR');
  const payouts = page.rows;
  useEffect(() => { setIsMounted(true); }, []);
  useEffect(() => {
    if (isMounted && isAuthenticated && user && user.role !== 'REPARTIDOR') router.push('/rider');
  }, [isMounted, isAuthenticated, user, router]);

  if (!isMounted || !isAuthenticated || !user || (!page.loaded && page.isLoading)) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-10 w-10 text-blue-600 mb-4" />
        <p className="text-gray-500 font-medium">Cargando historial...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <Button variant="ghost" size="icon" onClick={() => router.back()} className="hover:bg-white hover:shadow-sm rounded-full">
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <FileText className="w-6 h-6 text-blue-600" />
              Historial de Retiros
            </h1>
            <p className="text-gray-500 text-sm">Consulta tus retiros por estado y navega entre las páginas del historial.</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 items-center">
          <label htmlFor="payout-status">Estado del retiro</label>
          <select id="payout-status" className="rounded border p-2" value={page.selectedStatus} onChange={event => { void page.setStatus(event.target.value); }}>
            <option value="ALL">Todos los estados</option>
            {PAYOUT_FILTER_STATUSES.map(status => <option key={status} value={status}>{STATUS_CONFIG[status].label}</option>)}
          </select>
          <Button variant="outline" onClick={() => { void page.refresh(); }} disabled={page.isLoading}>Actualizar historial</Button>
        </div>
        <PayoutPageControls page={page} />

        {/* Lista */}
        <div className="space-y-4">
          {payouts.length === 0 ? (
            <Card className="border-dashed border-2 border-gray-300 bg-white">
              <CardContent className="py-16 text-center flex flex-col items-center">
                <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
                  <Wallet className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-bold text-gray-900">{!page.loaded ? 'No se pudo comprobar el historial' : 'Sin retiros en esta página'}</h3>
                <p className="text-gray-500 max-w-sm mt-2 mb-6">{page.loaded ? 'Puedes consultar otro estado o volver al inicio del historial.' : 'Vuelve a consultar antes de crear otra solicitud.'}</p>
                {page.loaded && !page.error && page.offset === 0 && page.status === 'ALL' && <Button onClick={() => router.push('/rider/earnings/withdraw')} className="bg-blue-600 hover:bg-blue-700 shadow-md">
                  Solicitar retiro
                </Button>}
              </CardContent>
            </Card>
          ) : (
            payouts.map((payout) => {
              const config = STATUS_CONFIG[payout.status];
              const Icon = config.icon;
              
              return (
                <Card key={payout.id} className="hover:shadow-md transition-all duration-200 border-l-4 border-l-transparent hover:border-l-blue-500 bg-white overflow-hidden">
                  <CardContent className="p-0">
                    <div className="p-5 flex flex-col md:flex-row gap-5">
                      {/* Icono Estado */}
                      <div className={`w-12 h-12 rounded-full flex items-center justify-center shrink-0 ${config.bg}`}>
                        <Icon className={`w-6 h-6 ${config.color}`} />
                      </div>

                      {/* Info Principal */}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-3 mb-2">
                          <h3 className="text-xl font-bold text-gray-900">{payoutAmountLabel(payout.amount, payout.currency)}</h3>
                          <Badge className={`${config.bg} ${config.color} border-transparent font-semibold text-xs px-2.5 py-0.5`}>
                            {config.label}
                          </Badge>
                          <span className="text-xs text-gray-400 font-mono hidden sm:inline-block">#{payout.id.slice(0, 8)}</span>
                        </div>

                        <div className="space-y-1.5">
                          <p className="text-sm text-gray-600 flex items-center gap-2">
                            <Clock className="w-3.5 h-3.5 text-gray-400" />
                            Solicitado el <span className="font-medium text-gray-900">{payoutDateLabel(payout.requested_at)}</span>
                          </p>
                          
                          {payout.bank_account_last4 && (
                            <p className="text-xs text-gray-500 bg-gray-50 inline-block px-2 py-1 rounded border border-gray-100">
                              Destino: **** {payout.bank_account_last4}
                            </p>
                          )}

                          {payout.rejection_reason && (
                            <div className="mt-3 text-xs text-red-700 bg-red-50 p-3 rounded-lg border border-red-100 flex items-start gap-2">
                              <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
                              <span><strong>Motivo:</strong> {payout.rejection_reason}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Columna Derecha */}
                      <div className="md:text-right border-t md:border-t-0 pt-4 md:pt-0 border-gray-100 flex flex-row md:flex-col justify-between items-center md:items-end gap-2">
                        <div>
                          <p className="text-[10px] text-gray-400 uppercase font-bold tracking-wider mb-1">Método</p>
                          <p className="font-semibold text-gray-700 text-sm">{METHOD_LABELS[payout.method]}</p>
                        </div>
                        
                        {payout.processed_at ? (
                          <div className="flex flex-col items-center md:items-end">
                            <span className="text-xs text-gray-600 font-bold flex items-center gap-1 bg-gray-50 px-2 py-1 rounded-full">
                              <Clock className="w-3 h-3" /> Gestión registrada
                            </span>
                            <span className="text-[10px] text-gray-400 mt-1">{formatDate(payout.processed_at)}</span>
                          </div>
                        ) : payout.status === 'PENDIENTE' ? (
                          <span className="text-xs text-amber-600 font-bold flex items-center gap-1 bg-amber-50 px-2 py-1 rounded-full">
                            <Clock className="w-3 h-3" /> En cola
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}