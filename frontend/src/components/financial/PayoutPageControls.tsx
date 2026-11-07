'use client';

import { Button } from '@/components/ui/button';
import { PAYOUT_PAGE_SIZE, type PayoutPages } from '@/hooks/usePayoutPages';

export function PayoutPageControls({ page }: { page: PayoutPages }) {
  return <div className="space-y-3">
    {page.error && <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 space-y-2">
      <p>{page.error}</p>
      {page.loaded && <p>Se muestra la página {page.offset / PAYOUT_PAGE_SIZE + 1} de la última consulta confirmada.</p>}
      <Button variant="outline" onClick={() => { void page.retry(); }} disabled={page.isLoading}>Reintentar consulta</Button>
    </div>}
    <nav aria-label="Paginación de retiros" className="flex flex-wrap items-center gap-3 text-sm">
      <Button variant="outline" onClick={() => { void page.first(); }} disabled={page.isLoading || (!page.loaded && !page.error) || (page.offset === 0 && !page.error)}>Volver al inicio</Button>
      <Button variant="outline" onClick={() => { void page.previous(); }} disabled={page.isLoading || page.offset === 0}>Anterior</Button>
      <span aria-live="polite">Página {page.offset / PAYOUT_PAGE_SIZE + 1}</span>
      <Button variant="outline" onClick={() => { void page.next(); }} disabled={page.isLoading || !page.hasNext}>Siguiente</Button>
      {page.loaded && <span>{page.rows.length ? `${page.rows.length} ${page.rows.length === 1 ? 'registro' : 'registros'} en esta página` : 'Sin registros en esta página'}</span>}
      {page.isLoading && <span role="status">Actualizando historial…</span>}
    </nav>
    <p className="text-xs text-muted-foreground">El historial puede cambiar mientras lo consultas. Vuelve al inicio para ver los retiros más recientes.</p>
  </div>;
}
