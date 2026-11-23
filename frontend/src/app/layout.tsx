import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { FeedbackHost } from '@/components/layout/FeedbackHost';

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
        
        <FeedbackHost />
      </body>
    </html>
  );
}
