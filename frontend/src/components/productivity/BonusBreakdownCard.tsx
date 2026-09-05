/**
 * Componente para mostrar el desglose detallado del bono de una entrega.
 * Muestra exactamente cómo se calculó el pago total:
 * - Bono base
 * - Multiplicador de zona
 * - Multiplicador de tier/nivel
 * - Total final
 * 
 * Ejemplo visual:
 * "Pago Total: $4125 | Base: $2500 + Zona (1.5x): $1250 + Nivel Oro (10%): $375"
 */

import React from 'react';
import { Info, DollarSign, MapPin, Award } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatCurrency } from '@/lib/formatters';

interface BonusBreakdownProps {
  /** Objeto con el desglose del bono desde el backend */
  breakdown: {
    base: number | null;
    zone_multiplier: number | null;
    tier_multiplier: number | null;
    tier_level: string | null;
    total: number;
  } | null;
  
  /** Fallback: valores individuales si no hay objeto breakdown */
  locked_bonus_base?: number | string | null;
  locked_bonus_zone_multiplier?: number | string | null;
  locked_bonus_tier_multiplier?: number | string | null;
  locked_bonus_tier_level?: string | null;
  locked_bonus_amount?: number | string | null;
  
  /** Mostrar solo si hay datos disponibles */
  hideIfEmpty?: boolean;
  
  /** Tamaño compacto para listas */
  compact?: boolean;
}

export function BonusBreakdownCard({
  breakdown,
  locked_bonus_base,
  locked_bonus_zone_multiplier,
  locked_bonus_tier_multiplier,
  locked_bonus_tier_level,
  locked_bonus_amount,
  hideIfEmpty = true,
  compact = false,
}: BonusBreakdownProps) {
  // Determinar qué datos usar (priorizar breakdown object)
  const base = breakdown?.base ?? (locked_bonus_base ? Number(locked_bonus_base) : null);
  const zoneMultiplier = breakdown?.zone_multiplier ?? (locked_bonus_zone_multiplier ? Number(locked_bonus_zone_multiplier) : null);
  const tierMultiplier = breakdown?.tier_multiplier ?? (locked_bonus_tier_multiplier ? Number(locked_bonus_tier_multiplier) : null);
  const tierLevel = breakdown?.tier_level ?? locked_bonus_tier_level;
  const total = breakdown?.total ?? (locked_bonus_amount ? Number(locked_bonus_amount) : null);

  // Si no hay datos y hideIfEmpty es true, no renderizar nada
  if (hideIfEmpty && !base && !total) {
    return null;
  }

  // Calcular montos parciales para el desglose visual
  // Fórmula: Total = Base × Zone × Tier
  // Zona bonus = (Base × Zone) - Base
  // Tier bonus = Total - (Base × Zone)
  
  const baseAmount = base ?? 0;
  const zoneAmount = base && zoneMultiplier ? (base * zoneMultiplier) - base : 0;
  const tierAmount = total !== null && base !== null && zoneMultiplier !== null 
    ? total - (base * zoneMultiplier) 
    : 0;

  // Formatear nivel del rider para display
  const getTierBadgeVariant = (level: string | null) => {
    switch (level?.toUpperCase()) {
      case 'PLATINO': return 'default'; // dark/purple
      case 'ORO': return 'secondary'; // yellow/gold
      case 'PLATA': return 'outline'; // silver
      default: return 'outline'; // bronce/default
    }
  };

  const getTierLabel = (level: string | null) => {
    if (!level) return 'Bronce';
    return level.charAt(0).toUpperCase() + level.slice(1).toLowerCase();
  };

  if (compact) {
    return (
      <div className="text-xs text-muted-foreground space-y-1">
        {base !== null && (
          <div className="flex justify-between">
            <span>Base:</span>
            <span className="font-medium">{formatCurrency(baseAmount)}</span>
          </div>
        )}
        {zoneMultiplier && zoneMultiplier > 1 && (
          <div className="flex justify-between">
            <span>Zona ({zoneMultiplier}x):</span>
            <span className="font-medium">+{formatCurrency(zoneAmount)}</span>
          </div>
        )}
        {tierMultiplier && tierMultiplier > 1 && (
          <div className="flex justify-between">
            <span>{getTierLabel(tierLevel)} ({((tierMultiplier - 1) * 100).toFixed(0)}%):</span>
            <span className="font-medium">+{formatCurrency(tierAmount)}</span>
          </div>
        )}
        {total !== null && (
          <div className="flex justify-between font-bold text-primary pt-1 border-t">
            <span>Total:</span>
            <span>{formatCurrency(total)}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <Card className="border-green-200 bg-gradient-to-br from-green-50 to-emerald-50/50">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <DollarSign className="w-4 h-4 text-green-600" />
          <h4 className="text-sm font-semibold text-green-900">Desglose del Bono</h4>
          <Badge variant="outline" className="ml-auto text-xs">
            {formatCurrency(total ?? 0)}
          </Badge>
        </div>

        <div className="space-y-3">
          {/* Bono Base */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-sm">
                <DollarSign className="w-4 h-4 text-blue-600" />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-600">Bono Base</p>
                <p className="text-sm font-bold text-gray-900">{formatCurrency(baseAmount)}</p>
              </div>
            </div>
          </div>

          {/* Multiplicador de Zona */}
          {zoneMultiplier !== null && zoneMultiplier !== undefined && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-sm">
                  <MapPin className="w-4 h-4 text-purple-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600">
                    Zona ({zoneMultiplier}x)
                  </p>
                  <p className="text-sm font-bold text-green-700">+{formatCurrency(zoneAmount)}</p>
                </div>
              </div>
            </div>
          )}

          {/* Multiplicador de Tier */}
          {tierMultiplier !== null && tierMultiplier !== undefined && tierMultiplier > 1 && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center shadow-sm">
                  <Award className="w-4 h-4 text-yellow-600" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-600 flex items-center gap-1">
                    Nivel{' '}
                    <Badge variant={getTierBadgeVariant(tierLevel)} className="text-xs px-1 py-0">
                      {getTierLabel(tierLevel)}
                    </Badge>
                    {' '}({((tierMultiplier - 1) * 100).toFixed(0)}%)
                  </p>
                  <p className="text-sm font-bold text-green-700">+{formatCurrency(tierAmount)}</p>
                </div>
              </div>
            </div>
          )}

          {/* Separador y Total */}
          <div className="pt-2 mt-2 border-t border-green-200">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-700">Total Bono</span>
              <span className="text-lg font-bold text-green-700">
                {formatCurrency(total ?? 0)}
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Fórmula: ${baseAmount} × {zoneMultiplier ?? 1.0} × {tierMultiplier ?? 1.0} = ${total?.toFixed(2) ?? '0.00'}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default BonusBreakdownCard;
