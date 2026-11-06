'use client';

import React, { useState, useEffect, useRef, useSyncExternalStore } from 'react';
import { capturePrivateTask } from '@/lib/private-task';
import { getCredentialGeneration, onCredentialsChanged } from '@/lib/auth-session';
import { confirmWithdrawal, payoutAmountLabel } from '@/lib/payout-contract';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/authStore';
import { payoutService, PayoutBalance, createPayoutIdempotencyKey, payoutHttpStatus } from '@/services/payout.service';
import { ArrowLeft, AlertCircle, CheckCircle, Info, Loader2, Banknote, ShieldCheck, CreditCard } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { WithdrawalIntent, loadWithdrawalIntent, saveWithdrawalIntent, clearWithdrawalIntent } from '@/lib/withdrawal-intent';
import { Alert, AlertDescription } from '@/components/ui/alert';

export default function WithdrawPage() {
  const generation = useSyncExternalStore(onCredentialsChanged, getCredentialGeneration, () => 0);
  const { user } = useAuthStore();
  return <SessionWithdrawPage key={JSON.stringify([generation, user?.id, user?.role])} />;
}

function SessionWithdrawPage() {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();
  
  const alive = useRef(false), submitLock = useRef(false), lookupLock = useRef(false), balanceSequence = useRef(0);
  const [initializing, setInitializing] = useState(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const requestIntent = useRef<WithdrawalIntent | null>(null);
  const [checkingRequest, setCheckingRequest] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const [requestStatus, setRequestStatus] = useState<string | null>(null);
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
    let active = true;
    void (async () => {
      try {
        // Recover first: a failed balance read must not lose an uncertain request.
        const saved = loadWithdrawalIntent(user.id);
        if (saved) {
          requestIntent.current = saved;
          setAmount((saved.amountCents / 100).toFixed(2));
          setBankAccountLast4(saved.bankLast4);
          setUnconfirmed(true);
        }
        await loadBalance();
        if (active && saved) await checkRequest(saved, () => active);
      } catch {
        if (active) {
          setUnconfirmed(true);
          setError('No se puede recuperar la solicitud. Revisa tu historial de retiros antes de crear otra.');
        }
      } finally {
        if (active) setInitializing(false);
      }
    })();
    return () => { active = false; };
  }, [user, isAuthenticated, router, isMounted]);

  const loadBalance = async () => {
    const sequence = ++balanceSequence.current;
    let task: ReturnType<typeof capturePrivateTask> | undefined;
    const current = () => alive.current && (!task || task.isCurrent()) && sequence === balanceSequence.current;
    setLoadingBalance(true);
    try {
      task = capturePrivateTask();
      const data = await payoutService.getAvailableBalance();
      task.assertCurrent();
      if (current()) setBalance(data);
    } catch {
      if (current()) {
        setBalance(null);
        setError('No se pudo cargar tu saldo disponible. Puedes volver a consultarlo.');
      }
    } finally {
      if (current()) setLoadingBalance(false);
    }
  };

  const checkRequest = async (saved: WithdrawalIntent, active = () => true) => {
    if (lookupLock.current || submitLock.current) return;
    lookupLock.current = true;
    const task = capturePrivateTask();
    const current = () => alive.current && active() && task.isCurrent();
    setCheckingRequest(true);
    try {
      const payout = await payoutService.findRequestByKey(saved.key);
      task.assertCurrent();
      if (!current()) return;
      if (payout) {
        const confirmed = confirmWithdrawal(payout, saved);
        try { clearWithdrawalIntent(saved.userId, saved.key); } catch { /* Server confirmation remains authoritative. */ }
        setSubmittedAmount(confirmed.amount);
        setRequestStatus(confirmed.status);
        setRecovered(true);
        setSuccess(true);
        setUnconfirmed(false);
      } else {
        setError('La solicitud aún no aparece registrada. Puedes consultar de nuevo o reintentar la misma solicitud.');
      }
    } catch {
      if (current()) setError('No se pudo confirmar la solicitud. Conservamos sus datos para reintentar sin crear otra.');
    } finally {
      lookupLock.current = false;
      if (current()) setCheckingRequest(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user || user.role !== 'REPARTIDOR' || initializing || loadingBalance || isSubmitting || checkingRequest || submitLock.current || lookupLock.current) return;
    const task = capturePrivateTask();
    const current = () => alive.current && task.isCurrent();
    setError(null);
    
    const numAmount = parseFloat(amount);
    const available = balance?.available;

    if (isNaN(numAmount) || numAmount <= 0) { setError('Ingresa un monto válido.'); return; }
    if (!unconfirmed && available === undefined) { setError('Consulta el saldo disponible antes de crear un retiro.'); return; }
    if (!unconfirmed && available !== undefined && numAmount > available) { setError('Monto superior al disponible.'); return; }
    if (numAmount < 10) { setError('El monto mínimo de retiro es 10.00.'); return; }

    if (bankAccountLast4 && !/^[0-9]{4}$/.test(bankAccountLast4)) { setError('Ingresa los cuatro dígitos completos de la cuenta.'); return; }
    if (!/^\d+(?:\.\d{1,2})?$/.test(amount.trim())) { setError('Usa un monto con hasta dos decimales.'); return; }
    if (unconfirmed && !requestIntent.current) return;
    if (!unconfirmed && requestIntent.current && (
      requestIntent.current.userId !== user.id || requestIntent.current.amountCents !== Math.round(numAmount * 100) ||
      requestIntent.current.bankLast4 !== bankAccountLast4.trim()
    )) requestIntent.current = null;
    if (!requestIntent.current) {
      requestIntent.current = { version: 1, userId: user.id, key: createPayoutIdempotencyKey(),
        amountCents: Math.round(numAmount * 100), bankLast4: bankAccountLast4.trim() };
    }
    const intent = requestIntent.current;
    try { saveWithdrawalIntent(intent); } catch {
      setError('El navegador no pudo conservar la solicitud. Revisa tu historial y la configuración del navegador antes de continuar.');
      return;
    }
    submitLock.current = true;
    setIsSubmitting(true);
    try {
      const payout = await payoutService.requestPayout({
        amount: intent.amountCents / 100,
        method: 'TRANSFERENCIA',
        bank_account_last4: intent.bankLast4 || undefined,
        idempotency_key: intent.key,
      });
      task.assertCurrent();
      if (!current()) return;
      const confirmed = confirmWithdrawal(payout, intent);
      try { clearWithdrawalIntent(intent.userId, intent.key); } catch { /* Retry lookup remains safe. */ }
      setSubmittedAmount(confirmed.amount);
      setRequestStatus(confirmed.status);
      setRecovered(unconfirmed);
      setSuccess(true);
      setUnconfirmed(false);
      void loadBalance();
    } catch (err: unknown) {
      if (!current()) return;
      const status = payoutHttpStatus(err);
      if (!unconfirmed && (status === 400 || status === 422)) {
        try { clearWithdrawalIntent(intent.userId, intent.key); } catch { /* Keep server confirmation checks available on reload. */ }
        requestIntent.current = null;
        setUnconfirmed(false);
      } else {
        setUnconfirmed(true);
      }
      setError('Error al procesar. Intenta más tarde.');
    } finally {
      submitLock.current = false;
      if (current()) setIsSubmitting(false);
    }
  };

  if (!isMounted || !isAuthenticated || !user || (!success && (initializing || loadingBalance || checkingRequest))) {
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
            {recovered ? <Info className="w-10 h-10 text-blue-600" /> : <CheckCircle className="w-10 h-10 text-green-600" />}
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-2">{recovered ? 'Solicitud encontrada' : '¡Solicitud Enviada!'}</h2>
          <p className="text-gray-600 mb-8 leading-relaxed">
            {recovered ? 'Encontramos tu solicitud de' : 'Hemos recibido tu solicitud de'} <strong className="text-gray-900 text-lg">{payoutAmountLabel(submittedAmount!, balance?.currency)}</strong>.
            <br/>
            <span className="text-sm text-gray-500">Puedes consultar el estado de la solicitud en tu historial de retiros.</span>
          </p>
          <p className="mb-4">Estado actual: {requestStatus?.replace(/_/g, ' ')}</p>
          <Button onClick={() => router.push('/rider/earnings')} className="w-full h-12 bg-green-600 hover:bg-green-700 shadow-lg shadow-green-200">
            Volver a Ganancias
          </Button>
        </Card>
      </div>
    );
  }

  const available = balance?.available;
  const canWithdraw = unconfirmed ? requestIntent.current !== null : available !== undefined && available >= 10;

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-2xl mx-auto space-y-6">
        <Button variant="ghost" onClick={() => router.back()} className="pl-0 hover:bg-transparent hover:text-gray-600 font-medium">
          <ArrowLeft className="mr-2 h-4 w-4" /> Volver
        </Button>

        <div>
          <h1 className="text-2xl font-bold text-gray-900">Solicitar Retiro</h1>
          <p className="text-gray-500">Solicita el retiro de tus ganancias disponibles.</p>
        </div>

        {/* Saldo Card */}
        <Card className="border-green-200 bg-gradient-to-br from-green-50 to-white shadow-md overflow-hidden relative">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <Banknote className="w-32 h-32 text-green-600" />
          </div>
          <CardContent className="p-6 flex items-center justify-between relative z-10">
            <div>
              <p className="text-sm font-bold text-green-800 uppercase tracking-wide">Saldo Disponible</p>
              <p className="text-4xl font-extrabold text-green-900 mt-1">{available === undefined ? 'No disponible' : payoutAmountLabel(available, balance?.currency)}</p>
            </div>
            <div className="p-4 bg-white rounded-full shadow-lg border border-green-100">
              <Banknote className="w-8 h-8 text-green-600" />
            </div>
          </CardContent>
        </Card>

        {!balance && <Button type="button" onClick={() => { setError(null); void loadBalance(); }}>Volver a consultar saldo</Button>}
        {unconfirmed && (
          <Alert><AlertDescription>
            Hay una solicitud pendiente de confirmar. Conservaremos sus datos al reintentar.
            {requestIntent.current && <Button type="button" onClick={() => { if (requestIntent.current) void checkRequest(requestIntent.current); }}>Consultar solicitud pendiente</Button>}
            <Button type="button" onClick={() => router.push('/rider/earnings/payouts')}>Ver historial de retiros</Button>
          </AlertDescription></Alert>
        )}
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
                  La solicitud requiere revisión. Consulta su estado en el historial de retiros.
                </AlertDescription>
              </Alert>

              <div className="space-y-2">
                <Label htmlFor="amount" className="font-bold text-gray-700">Monto a Retirar</Label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500 font-bold text-sm">{balance?.currency ?? '—'}</span>
                  <Input
                    id="amount"
                    type="number"
                    step="0.01"
                    min="10"
                    max={unconfirmed ? undefined : available}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="pl-14 text-lg font-bold h-14 focus-visible:ring-2 focus-visible:ring-green-500 focus-visible:border-green-500"
                    placeholder="0.00"
                    disabled={isSubmitting || unconfirmed || !canWithdraw}
                  />
                </div>
                <div className="flex justify-between text-xs font-medium text-gray-500 px-1">
                  <span>Mín: {payoutAmountLabel(10, balance?.currency)}</span>
                  <span>Max: {available === undefined ? 'No disponible' : payoutAmountLabel(available, balance?.currency)}</span>
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
                      <p className="text-xs text-gray-500">Cuenta de destino</p>
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
                  disabled={isSubmitting || unconfirmed}
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
                  <>{unconfirmed ? 'Reintentar misma solicitud' : 'Enviar solicitud de retiro'}</>
                )}
              </Button>
              
              {!canWithdraw && available !== undefined && (
                <p className="text-xs text-center text-red-500 font-bold bg-red-50 p-2 rounded">
                  Necesitas al menos {payoutAmountLabel(10, balance?.currency)} para retirar.
                </p>
              )}
            </CardContent>
          </Card>
        </form>
      </div>
    </div>
  );
}