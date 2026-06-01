'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Download, Calendar, DollarSign, Package, Users, AlertCircle, Loader2 } from 'lucide-react';
import { downloadCSV } from '@/lib/csv-export'; 
import { orderService, Order } from '@/services/order.service';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { formatCurrency } from '@/lib/formatters';

export default function ReportsPage() {
  const router = useRouter();
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ totalRevenue: 0, completedOrders: 0, activeCustomers: 0 });

  // Cargar estadísticas iniciales (Simulado para este ejemplo, idealmente vendría del backend)
  React.useEffect(() => {
    // Aquí podrías llamar a un endpoint de dashboard para obtener los números reales
    setStats({
      totalRevenue: 12450000, // Ejemplo en pesos
      completedOrders: 450,
      activeCustomers: 320
    });
  }, []);

  const handleExportOrders = async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Obtener datos reales del backend
      // Nota: Si tu backend soporta filtros ?start_date=...&end_date=..., úsalos aquí
      const allOrders = await orderService.getAll({ limit: 1000 }); 

      if (allOrders.length === 0) {
        setError('No hay órdenes disponibles para exportar en este rango.');
        setLoading(false);
        return;
      }

      // 2. Transformar datos complejos a formato plano para CSV
      const csvData = allOrders.map((order: Order) => ({
        id_orden: order.external_id || order.id,
        fecha: order.created_at ? new Date(order.created_at).toLocaleDateString() : 'N/A',
        cliente: order.customer_name,
        telefono: order.customer_phone,
        direccion_entrega: order.delivery_address,
        estado: order.status,
        total: order.total || 0,
        repartidor: order.rider ? `${order.rider.first_name} ${order.rider.last_name}` : 'No asignado',
        metodo_pago: order.payment_method || 'No especificado',
      }));

      // 3. Generar nombre de archivo con fecha
      const today = new Date().toISOString().split('T')[0];
      const filename = `reporte_ordenes_${today}`;

      // 4. Descargar
      downloadCSV(csvData, filename);
      
    } catch (err: any) {
      console.error('Error al exportar:', err);
      setError(err.message || 'No se pudo generar el reporte. Intente nuevamente.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Reportes y Exportación</h1>
            <p className="text-gray-500">Genera informes de rendimiento y descárgalos en CSV.</p>
          </div>
        </div>

        {/* Tarjetas de Estadísticas Rápidas */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Ingresos Totales</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(stats.totalRevenue)}</div>
              <p className="text-xs text-muted-foreground">Acumulado histórico</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Órdenes Completadas</CardTitle>
              <Package className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.completedOrders}</div>
              <p className="text-xs text-muted-foreground">Total exitosas</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Clientes Únicos</CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.activeCustomers}</div>
              <p className="text-xs text-muted-foreground">En la base de datos</p>
            </CardContent>
          </Card>
        </div>

        {/* Sección de Exportación */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Calendar className="w-5 h-5" /> Generar Reporte de Órdenes
            </CardTitle>
            <CardDescription>
              Descarga un detalle de todas las órdenes en formato CSV compatible con Excel.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            
            {error && (
              <Alert variant="destructive" className="bg-red-50 border-red-200">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-white p-4 rounded-lg border">
              <div>
                <label className="text-sm font-medium mb-1 block text-gray-700">Fecha Inicio</label>
                <input 
                  type="date" 
                  className="w-full border rounded-md p-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  value={dateRange.start}
                  onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block text-gray-700">Fecha Fin</label>
                <input 
                  type="date" 
                  className="w-full border rounded-md p-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  value={dateRange.end}
                  onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
                />
              </div>
              <div className="flex items-end">
                <Button 
                  onClick={handleExportOrders} 
                  disabled={loading} 
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Procesando...
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4 mr-2" /> Exportar CSV
                    </>
                  )}
                </Button>
              </div>
            </div>
            
            <p className="text-xs text-gray-500 mt-2">
              * El reporte incluirá: ID, Cliente, Dirección, Estado, Total y Repartidor asignado.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}