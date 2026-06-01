'use client';

import React, { useState, useEffect } from 'react';
import { settingsService, PlatformSettings } from '@/services/settings.service';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Save, AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';

export default function SettingsPage() {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    settingsService.getSettings().then(data => {
      setSettings(data);
      setLoading(false);
    });
  }, []);

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await settingsService.updateSettings(settings);
      alert('Configuración guardada correctamente');
    } catch (error) {
      alert('Error al guardar configuración');
    } finally {
      setSaving(false);
    }
  };

  if (loading || !settings) return <div className="p-8 text-center">Cargando configuración...</div>;

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Configuración de la Plataforma</h1>

        {settings.maintenance_mode && (
          <Alert variant="destructive" className="mb-6 bg-orange-50 border-orange-200 text-orange-800">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              El modo mantenimiento está activo. Los usuarios no podrán realizar nuevos pedidos.
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Tarifas y Comisiones</CardTitle>
              <CardDescription>Configura los valores financieros base.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <Label>Tarifa Base de Envío</Label>
                <Input 
                  type="number" 
                  value={settings.delivery_fee_base} 
                  onChange={(e) => setSettings({...settings, delivery_fee_base: Number(e.target.value)})}
                  className="mt-1"
                />
              </div>
              <div>
                <Label>Comisión (%)</Label>
                <Input 
                  type="number" 
                  value={settings.commission_percentage} 
                  onChange={(e) => setSettings({...settings, commission_percentage: Number(e.target.value)})}
                  className="mt-1"
                />
              </div>
              <div>
                <Label>Pedido Mínimo</Label>
                <Input 
                  type="number" 
                  value={settings.min_order_amount} 
                  onChange={(e) => setSettings({...settings, min_order_amount: Number(e.target.value)})}
                  className="mt-1"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Estado del Sistema</CardTitle>
              <CardDescription>Controla el acceso general a la plataforma.</CardDescription>
            </CardHeader>
            <CardContent className="flex items-center justify-between">
              <div>
                <Label className="font-semibold">Modo Mantenimiento</Label>
                <p className="text-sm text-gray-500">Desactiva el acceso a clientes y repartidores.</p>
              </div>
              <Switch 
                checked={settings.maintenance_mode}
                onCheckedChange={(checked) => setSettings({...settings, maintenance_mode: checked})}
              />
            </CardContent>
          </Card>

          <div className="flex justify-end pt-4">
            <Button onClick={handleSave} disabled={saving} className="w-full md:w-auto">
              <Save className="w-4 h-4 mr-2" /> {saving ? 'Guardando...' : 'Guardar Cambios'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}