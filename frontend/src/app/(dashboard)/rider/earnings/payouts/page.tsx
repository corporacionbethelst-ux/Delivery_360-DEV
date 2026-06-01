'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore'; // ✅ CORRECCIÓN: Usar Zustand
// import { payoutService, Payout } from '@/services/payout.service'; // Descomentar cuando exista el servicio real
import { formatCurrency, formatDate } from '@/lib/formatters';
import { ArrowLeft, Download, Clock, CheckCircle, XCircle, AlertCircle, Wallet } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2 } from 'lucide-react';

// Interfaz local (Mover a types/user.ts o services/payout.service.ts cuando se cree el archivo)
interface Payout {
  id: string;
  amount: number;
  status: 'PENDIENTE' | 'PROCESADO' | 'RECHAZADO';
  requested_at: string;
  processed_at?: string;
  method: string;
  rejection_reason?: string;
  reference_code?: string;
}

export default function RiderPayoutsPage() {
  const router = useRouter();
  
  // ✅ CORRECCIÓN: Obtener estado del store
  const { user, isAuthenticated } = useAuthStore();
  
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [loadingData, setLoadingData] = useState(true);
  const [isMounted, setIsMounted] = useState(false);

  // Efecto para evitar hidratación incorrecta
  useEffect(() => {
    setIsMounted(true);
  }, []);

  // ✅ Seguridad: Protección de ruta y verificación de rol
  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;

    if (user.role !== 'REPARTIDOR') {
      router.push('/rider'); // Redirigir al dashboard si no es repartidor
      return;
    }
    
    loadPayouts();
  }, [isAuthenticated, user, router, isMounted]);

  const loadPayouts = async () => {
    setLoadingData(true);
    try {
      // 🔴 TODO: Descomentar cuando el servicio esté implementado en backend/frontend
      // const data = await payoutService.getAll({ limit: 50 });
      // setPayouts(data);

      // 🟡 MOCK DATA (Simulación para desarrollo visual)
      await new Promise(r => setTimeout(r, 800));
      setPayouts([
        {
          id: '1',
          amount: 150.00,
          status: 'PROCESADO',
          requested_at: new Date(Date.now() - 86400000 * 5).toISOString(),
          processed_at: new Date(Date.now() - 86400000 * 3).toISOString(),
          method: 'TRANSFERENCIA',
          reference_code: 'TXN-998877'
        },
        {
          id: '2',
          amount: 85.50,
          status: 'PENDIENTE',
          requested_at: new Date(Date.now() - 86400000 * 1).toISOString(),
          method: 'TRANSFERENCIA'
        },
        {
          id: '3',
          amount: 40.00,
          status: 'RECHAZADO',
          requested_at: new Date(Date.now() - 86400000 * 10).toISOString(),
          method: 'TRANSFERENCIA',
          rejection_reason: 'Datos bancarios incorrectos o cuenta inválida'
        }
      ]);
    } catch (error) {
      console.error('Error loading payouts:', error);
      // Opcional: Mostrar toast de error
    } finally {
      setLoadingData(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch(status) {
      case 'PROCESADO': return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'RECHAZADO': return <XCircle className="w-5 h-5 text-red-600" />;
      default: return <Clock className="w-5 h-5 text-yellow-600" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch(status) {
      case 'PROCESADO': return 'bg-green-100 text-green-800 border-green-200';
      case 'RECHAZADO': return 'bg-red-100 text-red-800 border-red-200';
      case 'PENDIENTE': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  // ✅ Seguridad: Mostrar carga mientras se verifica autenticación y datos
  if (!isMounted || !isAuthenticated || !user || loadingData) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600 mb-4" />
        <p className="text-gray-600 font-medium">Cargando historial de retiros...</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <Button 
            variant="ghost" 
            size="icon" 
            onClick={() => router.back()}
            className="hover:bg-white hover:shadow-sm"
          >
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Wallet className="w-6 h-6 text-blue-600" />
              Historial de Retiros
            </h1>
            <p className="text-gray-500 text-sm mt-1">Consulta el estado de tus pagos solicitados.</p>
          </div>
        </div>

        {/* Lista de Retiros */}
        <div className="space-y-4">
          {payouts.length === 0 ? (
            <Card className="border-dashed border-2">
              <CardContent className="py-16 text-center text-gray-500 flex flex-col items-center">
                <div className="bg-gray-100 p-4 rounded-full mb-4">
                  <AlertCircle className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">Sin retiros registrados</h3>
                <p className="max-w-md mb-6">Aún no has solicitado ningún retiro. Cuando tengas saldo disponible, podrás transferirlo a tu cuenta.</p>
                <Button 
                  onClick={() => router.push('/rider/earnings/withdraw')}
                  className="bg-blue-600 hover:bg-blue-700 text-white"
                >
                  Solicitar tu primer retiro
                </Button>
              </CardContent>
            </Card>
          ) : (
            payouts.map(payout => (
              <Card key={payout.id} className="hover:shadow-md transition-shadow border-l-4 border-l-transparent hover:border-l-blue-500">
                <CardContent className="p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-5">
                  {/* Icono e Info Principal */}
                  <div className="flex items-start gap-4 flex-1">
                    <div className={`p-3 rounded-full shrink-0 ${
                      payout.status === 'PROCESADO' ? 'bg-green-100' : 
                      payout.status === 'RECHAZADO' ? 'bg-red-100' : 'bg-yellow-100'
                    }`}>
                      {getStatusIcon(payout.status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <h3 className="font-bold text-xl text-gray-900">{formatCurrency(payout.amount)}</h3>
                        <Badge className={`${getStatusColor(payout.status)} border text-xs px-2 py-0.5`}>
                          {payout.status}
                        </Badge>
                      </div>
                      
                      <p className="text-sm text-gray-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        Solicitado el {formatDate(payout.requested_at)}
                      </p>

                      {/* Motivo de Rechazo (Solo si aplica) */}
                      {payout.rejection_reason && (
                        <div className="mt-2 text-xs text-red-700 bg-red-50 p-3 rounded border border-red-100 flex items-start gap-2">
                          <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
                          <span><strong>Motivo:</strong> {payout.rejection_reason}</span>
                        </div>
                      )}

                      {/* Código de Referencia (Solo si aplica) */}
                      {payout.reference_code && (
                        <p className="text-xs text-gray-400 mt-2 font-mono bg-gray-100 px-2 py-1 rounded inline-block">
                          Ref: {payout.reference_code}
                        </p>
                      )}
                    </div>
                  </div>
                  
                  {/* Columna Derecha: Detalles */}
                  <div className="text-right min-w-[140px] w-full md:w-auto border-t md:border-t-0 pt-4 md:pt-0 border-gray-100">
                    <p className="text-xs text-gray-500 uppercase font-semibold mb-1">Método de Pago</p>
                    <p className="font-medium text-gray-900 text-sm mb-3">{payout.method.replace('_', ' ')}</p>
                    
                    {payout.processed_at ? (
                      <div className="flex flex-col items-end">
                        <span className="text-xs text-green-600 font-semibold flex items-center gap-1 bg-green-50 px-2 py-1 rounded">
                          <CheckCircle className="w-3 h-3" />
                          Procesado
                        </span>
                        <span className="text-[10px] text-gray-400 mt-1">{formatDate(payout.processed_at)}</span>
                      </div>
                    ) : payout.status === 'PENDIENTE' ? (
                      <span className="text-xs text-yellow-600 font-medium flex items-center gap-1 bg-yellow-50 px-2 py-1 rounded">
                        <Clock className="w-3 h-3" />
                        En proceso
                      </span>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}