'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { payoutService, PayoutBalance } from '@/services/payout.service';
import { ArrowLeft, AlertCircle, CheckCircle, Info, Loader2, Banknote, ShieldCheck, CreditCard } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatCurrency } from '@/lib/formatters';
import { Alert, AlertDescription } from '@/components/ui/alert';

export default function WithdrawPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const [balance, setBalance] = useState<PayoutBalance | null>(null);
  const [amount, setAmount] = useState<string>('');
  const [bankAccountLast4, setBankAccountLast4] = useState<string>('');
  const [submittedAmount, setSubmittedAmount] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loadingBalance, setLoadingBalance] = useState(true);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => { setIsMounted(true); }, []);

  useEffect(() => {
    if (!isMounted || !isAuthenticated || !user) return;
    if (user.role !== 'REPARTIDOR') { router.push('/rider'); return; }
    loadBalance();
  }, [user, isAuthenticated, router, isMounted]);

  const loadBalance = async () => {
    setLoadingBalance(true);
    setError(null);
    try {
      const data = await payoutService.getAvailableBalance();
      setBalance(data);
    } catch (e) {
      setError('No se pudo cargar tu saldo disponible.');
    } finally {
      setLoadingBalance(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    
    const numAmount = parseFloat(amount);
    const available = Number(balance?.available ?? 0);

    if (isNaN(numAmount) || numAmount <= 0) { setError('Ingresa un monto válido.'); return; }
    if (numAmount > available) { setError('Monto superior al disponible.'); return; }
    if (numAmount < 10) { setError('Mínimo $10.00 para retirar.'); return; }

    setIsSubmitting(true);
    try {
      const payout = await payoutService.requestPayout({
        amount: numAmount,
        method: 'TRANSFERENCIA',
        bank_account_last4: bankAccountLast4.trim() || undefined,
      });
      setSubmittedAmount(payout.amount);
      setSuccess(true);
      void loadBalance();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Error al procesar. Intenta más tarde.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isMounted || !isAuthenticated || !user || loadingBalance) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="animate-spin h-12 w-12 text-blue-600" />
      </div>
    );
  }

  if (success) {
    return (
      <div className="p-6 flex items-center justify-center min-h-screen bg-gray-50">
        <Card className="max-w-md w-full text-center p-8 shadow-xl border-green-100 animate-in fade-in zoom-in duration-300">
          <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6 shadow-inner">
            <CheckCircle className="w-10 h-10 text-green-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-2">¡Solicitud Enviada!</h2>
          <p className="text-gray-600 mb-8 leading-relaxed">
            Hemos recibido tu retiro de <strong className="text-gray-900 text-lg">{formatCurrency(submittedAmount ?? 0)}</strong>.
            <br/>
            <span className="text-sm text-gray-500">Se depositará en tu cuenta en el próximo ciclo.</span>
          </p>
          <Button onClick={() => router.push('/rider/earnings')} className="w-full h-12 bg-green-600 hover:bg-green-700 shadow-lg shadow-green-200">
            Volver a Ganancias
          </Button>
        </Card>
      </div>
    );
  }

  const available = Number(balance?.available ?? 0);
  const canWithdraw = available >= 10;

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-2xl mx-auto space-y-6">
        <Button variant="ghost" onClick={() => router.back()} className="pl-0 hover:bg-transparent hover:text-gray-600 font-medium">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver
        </Button>

        <div>
          <h1 className="text-2xl font-bold text-gray-900">Solicitar Retiro</h1>
          <p className="text-gray-500">Transfiere tus ganancias de forma segura.</p>
        </div>

        {/* Saldo Card */}
        <Card className="border-green-200 bg-gradient-to-br from-green-50 to-white shadow-md overflow-hidden relative">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <Banknote className="w-32 h-32 text-green-600" />
          </div>
          <CardContent className="p-6 flex items-center justify-between relative z-10">
            <div>
              <p className="text-sm font-bold text-green-800 uppercase tracking-wide">Saldo Disponible</p>
              <p className="text-4xl font-extrabold text-green-900 mt-1">{formatCurrency(available)}</p>
            </div>
            <div className="p-4 bg-white rounded-full shadow-lg border border-green-100">
              <Banknote className="w-8 h-8 text-green-600" />
            </div>
          </CardContent>
        </Card>

        <form onSubmit={handleSubmit}>
          <Card className="shadow-lg border-gray-100">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-blue-600" />
                Detalles de la Transacción
              </CardTitle>
              <CardDescription>Ingresa el monto y confirma los datos.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {error && (
                <Alert variant="destructive" className="bg-red-50 border-red-200 text-red-800">
                  <AlertCircle className="w-4 h-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <Alert className="bg-blue-50 border-blue-200 text-blue-800">
                <Info className="w-4 h-4" />
                <AlertDescription className="text-sm font-medium">
                  Los pagos se procesan los viernes. Solicita antes del jueves 14:00.
                </AlertDescription>
              </Alert>

              <div className="space-y-2">
                <Label htmlFor="amount" className="font-bold text-gray-700">Monto a Retirar</Label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500 font-bold text-lg">$</span>
                  <Input
                    id="amount"
                    type="number"
                    step="0.01"
                    min="10"
                    max={available}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="pl-8 text-lg font-bold h-14 focus-visible:ring-2 focus-visible:ring-green-500 focus-visible:border-green-500"
                    placeholder="0.00"
                    disabled={isSubmitting || !canWithdraw}
                  />
                </div>
                <div className="flex justify-between text-xs font-medium text-gray-500 px-1">
                  <span>Mín: {formatCurrency(10)}</span>
                  <span>Max: {formatCurrency(available)}</span>
                </div>
              </div>

              <div className="pt-4 border-t">
                <Label className="font-bold text-gray-700 mb-3 block">Método de Pago</Label>
                <div className="p-4 border-2 border-blue-100 rounded-xl bg-blue-50/50 flex items-center justify-between cursor-default">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-white rounded-lg border border-blue-100 shadow-sm">
                      <CreditCard className="w-5 h-5 text-blue-600" />
                    </div>
                    <div>
                      <p className="font-bold text-sm text-gray-900">Transferencia Bancaria</p>
                      <p className="text-xs text-gray-500">A tu cuenta registrada</p>
                    </div>
                  </div>
                  <ShieldCheck className="w-5 h-5 text-blue-600" />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="bankAccountLast4" className="font-bold text-gray-700">Últimos 4 dígitos (Opcional)</Label>
                <Input
                  id="bankAccountLast4"
                  value={bankAccountLast4}
                  maxLength={4}
                  inputMode="numeric"
                  onChange={(e) => setBankAccountLast4(e.target.value.replace(/\D/g, '').slice(0, 4))}
                  placeholder="Ej. 1234"
                  disabled={isSubmitting}
                  className="h-12"
                />
                <p className="text-xs text-gray-500">Para verificar la cuenta destino.</p>
              </div>

              <Button 
                type="submit" 
                disabled={isSubmitting || !canWithdraw} 
                className="w-full h-14 text-lg font-bold bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white shadow-lg shadow-green-200 disabled:opacity-50 disabled:cursor-not-allowed transition-all transform active:scale-[0.98]"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Procesando...
                  </>
                ) : (
                  <>Confirmar Retiro Seguro</>
                )}
              </Button>
              
              {!canWithdraw && (
                <p className="text-xs text-center text-red-500 font-bold bg-red-50 p-2 rounded">
                  Necesitas al menos {formatCurrency(10)} para retirar.
                </p>
              )}
            </CardContent>
          </Card>
        </form>
      </div>
    </div>
  );
}