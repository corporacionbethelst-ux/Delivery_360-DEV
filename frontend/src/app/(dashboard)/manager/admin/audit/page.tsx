'use client';

import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { 
  History, Search, Filter, Download, ShieldAlert, User, 
  Clock, Terminal, AlertCircle, CheckCircle 
} from 'lucide-react';

interface AuditLog {
  id: string;
  action: string;
  user: string;
  role: string;
  timestamp: string;
  ip: string;
  status: 'SUCCESS' | 'FAILURE' | 'WARNING';
  details: string;
}

const MOCK_LOGS: AuditLog[] = [
  { id: '1', action: 'LOGIN', user: 'gerente@delivery.com', role: 'GERENTE', timestamp: '2024-05-14 10:30:00', ip: '192.168.1.10', status: 'SUCCESS', details: 'Inicio de sesión exitoso' },
  { id: '2', action: 'UPDATE_ORDER', user: 'operador@delivery.com', role: 'OPERADOR', timestamp: '2024-05-14 10:25:00', ip: '192.168.1.15', status: 'SUCCESS', details: 'Orden #ORD-005 actualizada a EN_RUTA' },
  { id: '3', action: 'DELETE_USER', user: 'admin@delivery.com', role: 'SUPERADMIN', timestamp: '2024-05-14 09:15:00', ip: '192.168.1.5', status: 'WARNING', details: 'Intento de eliminación de usuario protegido' },
  { id: '4', action: 'API_ERROR', user: 'SYSTEM', role: 'SYSTEM', timestamp: '2024-05-14 08:00:00', ip: '127.0.0.1', status: 'FAILURE', details: 'Timeout en conexión con pasarela de pagos' },
];

export default function AdminAuditPage() {
  const [searchTerm, setSearchTerm] = useState('');
  
  const filteredLogs = MOCK_LOGS.filter(log => 
    log.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
    log.user.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const getStatusColor = (status: string) => {
    switch(status) {
      case 'SUCCESS': return 'bg-green-100 text-green-800 border-green-200';
      case 'FAILURE': return 'bg-red-100 text-red-800 border-red-200';
      case 'WARNING': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getIcon = (action: string) => {
    if (action.includes('LOGIN')) return <User className="w-4 h-4" />;
    if (action.includes('ERROR') || action.includes('FAILURE')) return <AlertCircle className="w-4 h-4" />;
    return <Terminal className="w-4 h-4" />;
  };

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <History className="w-6 h-6 text-slate-600" />
              Auditoría del Sistema
            </h1>
            <p className="text-gray-500 mt-1">Registro inmutable de todas las acciones críticas</p>
          </div>
          <Button variant="outline">
            <Download className="w-4 h-4 mr-2" /> Exportar Logs
          </Button>
        </div>

        <Card className="mb-6">
          <CardContent className="p-4 flex gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
              <Input 
                placeholder="Buscar por acción, usuario o IP..." 
                className="pl-9"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <Button variant="outline" className="gap-2">
              <Filter className="w-4 h-4" /> Filtros
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-700 uppercase bg-gray-50 border-b">
                  <tr>
                    <th className="px-6 py-3">Estado</th>
                    <th className="px-6 py-3">Acción</th>
                    <th className="px-6 py-3">Usuario</th>
                    <th className="px-6 py-3">Fecha</th>
                    <th className="px-6 py-3">IP</th>
                    <th className="px-6 py-3">Detalles</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLogs.map((log) => (
                    <tr key={log.id} className="bg-white border-b hover:bg-gray-50 font-mono text-xs">
                      <td className="px-6 py-4">
                        <Badge className={getStatusColor(log.status)}>{log.status}</Badge>
                      </td>
                      <td className="px-6 py-4 font-bold text-gray-700 flex items-center gap-2">
                        {getIcon(log.action)}
                        {log.action}
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-semibold text-gray-900">{log.user}</div>
                        <div className="text-xs text-gray-500">{log.role}</div>
                      </td>
                      <td className="px-6 py-4 text-gray-500">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3" /> {log.timestamp}
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-gray-500">{log.ip}</td>
                      <td className="px-6 py-4 text-gray-600 max-w-xs truncate" title={log.details}>
                        {log.details}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}