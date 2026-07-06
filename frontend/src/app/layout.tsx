import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Toaster } from 'sonner'; // Importar desde sonner

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Delivery360 - Sistema de Gestión de Deliveries',
  description: 'Plataforma enterprise para gestión de deliveries, repartidores y órdenes en tiempo real',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className={inter.className}>
        {children}
        
        {/* 
          ✅ SOLUCIÓN: Toaster Global con zIndex explícito mayor que el header (z-50 = 50).
          position: top-right para mejor visibilidad en móviles y desktop.
        */}
        <Toaster 
          richColors 
          position="top-right" 
          toastOptions={{
            style: {
              zIndex: 9999, // Fuerza que esté por encima de todo
            },
          }}
        />
      </body>
    </html>
  );
}