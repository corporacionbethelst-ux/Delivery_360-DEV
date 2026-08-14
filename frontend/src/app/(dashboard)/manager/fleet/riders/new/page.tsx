'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import RiderRegistrationForm from '@/components/riders/RiderRegistrationForm';
import { Button } from '@/components/ui/button';
import { ArrowLeft, UserPlus } from 'lucide-react';

/**
 * Página de creación de repartidores.
 * Utiliza el componente compartido RiderRegistrationForm que soporta:
 * - Vehículo Propio: Ingresa placa/modelo manualmente
 * - Vehículo de Empresa: Selecciona de dropdown de flota disponible
 */
export default function ManagerCreateRiderPage() {
  const router = useRouter();

  const handleSuccess = () => {
    // Redirigir a la lista de repartidores después de un éxito
    setTimeout(() => {
      router.push('/manager/fleet/riders');
    }, 1000);
  };

  const handleCancel = () => {
    router.back();
  };

  return (
    <div className="p-6 bg-slate-50/50 min-h-screen">
      <div className="max-w-3xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="flex flex-col gap-2">
          <Button 
            variant="ghost" 
            onClick={handleCancel} 
            className="w-fit -ml-2 text-slate-500 hover:text-slate-900"
          >
            <ArrowLeft className="mr-2 h-4 w-4" /> Volver
          </Button>
          
          <div className="flex items-center gap-3 pb-2">
            <div className="p-2.5 bg-blue-600 rounded-xl shadow-sm">
              <UserPlus className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Nuevo Repartidor</h1>
              <p className="text-slate-500 text-sm">Registra un nuevo miembro a la flota operativa</p>
            </div>
          </div>
        </div>

        {/* Formulario Compartido */}
        <RiderRegistrationForm 
          onSuccess={handleSuccess} 
          onCancel={handleCancel} 
        />
      </div>
    </div>
  );
}
