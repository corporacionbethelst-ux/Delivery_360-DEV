'use client';
import { type PropsWithChildren } from 'react';
import { ManagerPageBoundary } from '@/components/layout/ManagerPageBoundary';

export function RiderAuditAccess({ children, riderId = 'catalog' }: PropsWithChildren<{ riderId?: string }>) {
  return <ManagerPageBoundary scope={`audit:${riderId}`} pending="Verificando acceso a auditoría…">{children}</ManagerPageBoundary>;
}
