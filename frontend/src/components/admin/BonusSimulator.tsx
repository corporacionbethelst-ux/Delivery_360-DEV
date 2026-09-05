'use client';

import React, { useState } from 'react';
import { settingsService } from '@/services/settings.service';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TrendingUp, TrendingDown, DollarSign } from 'lucide-react';

interface SimulationResult {
  current_monthly_cost: number;
  projected_monthly_cost: number;
  difference: number;
  percentage_increase: number;
  message: string;
}

export function BonusSimulator() {
  const [baseBonus, setBaseBonus] = useState<number>(2500);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSimulate = async () => {
    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await settingsService.simulateBonusImpact({
        new_base_bonus: baseBonus,
        days_projection: 30
      });
      setResult(data);
    } catch (err) {
      setError('Error al calcular el impacto. Verifica la conexión con el servidor.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency',
      currency: 'COP',
      minimumFractionDigits: 0
    }).format(value);
  };

  return (
    <Card className="w-full max-w-2xl mx-auto border-blue-100 shadow-md">
      <CardHeader className="bg-blue-50/50">
        <CardTitle className="flex items-center gap-2 text-blue-900">
          <DollarSign className="w-5 h-5" />
          Simulador de Impacto Financiero
        </CardTitle>
        <CardDescription>
          Proyecta el costo operativo mensual al modificar el bono base por entrega.
          <br />
          <span className="text-xs text-blue-600 italic">
            * Basado en el promedio de entregas de los últimos 30 días.
          </span>
        </CardDescription>
      </CardHeader>
      
      <CardContent className="pt-6 space-y-6">
        {/* Inputs */}
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="base-bonus">Nuevo Bono Base por Entrega ($)</Label>
            <div className="flex gap-2">
              <Input
                id="base-bonus"
                type="number"
                value={baseBonus}
                onChange={(e) => setBaseBonus(Number(e.target.value))}
                className="font-mono"
                placeholder="Ej: 3000"
              />
              <Button 
                onClick={handleSimulate} 
                disabled={isLoading || baseBonus <= 0}
                className="w-32 bg-blue-600 hover:bg-blue-700"
              >
                {isLoading ? 'Calculando...' : 'Simular'}
              </Button>
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4 animate-in fade-in slide-in-from-top-4 duration-500">
            <div className="h-px bg-gray-200 my-4" />
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Current Cost */}
              <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                <p className="text-sm text-gray-500 mb-1">Costo Mensual Actual</p>
                <p className="text-2xl font-bold text-gray-800">
                  {formatCurrency(result.current_monthly_cost)}
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Basado en histórico real
                </p>
              </div>

              {/* Projected Cost */}
              <div className={`p-4 rounded-lg border ${
                result.difference > 0 
                  ? 'bg-red-50 border-red-200' 
                  : 'bg-green-50 border-green-200'
              }`}>
                <p className={`text-sm mb-1 ${
                  result.difference > 0 ? 'text-red-600' : 'text-green-600'
                }`}>
                  Costo Proyectado (30 días)
                </p>
                <p className={`text-2xl font-bold ${
                  result.difference > 0 ? 'text-red-700' : 'text-green-700'
                }`}>
                  {formatCurrency(result.projected_monthly_cost)}
                </p>
                <div className="flex items-center gap-1 mt-1">
                  {result.difference > 0 ? (
                    <TrendingUp className="w-4 h-4 text-red-500" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-green-500" />
                  )}
                  <span className={`text-sm font-medium ${
                    result.difference > 0 ? 'text-red-600' : 'text-green-600'
                  }`}>
                    {result.percentage_increase > 0 ? '+' : ''}{result.percentage_increase.toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>

            {/* Difference Highlight */}
            <div className={`p-4 rounded-lg border flex justify-between items-center ${
              result.difference > 0 
                ? 'bg-red-100/50 border-red-200' 
                : 'bg-green-100/50 border-green-200'
            }`}>
              <span className="text-sm font-medium text-gray-700">
                Impacto Neto Mensual:
              </span>
              <span className={`text-xl font-bold ${
                result.difference > 0 ? 'text-red-700' : 'text-green-700'
              }`}>
                {result.difference > 0 ? '+' : ''}{formatCurrency(result.difference)}
              </span>
            </div>

            {/* Interpretation Message */}
            <Alert className={result.difference > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}>
              <AlertDescription className="text-sm">
                <strong>Interpretación:</strong> {result.message}
              </AlertDescription>
            </Alert>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
