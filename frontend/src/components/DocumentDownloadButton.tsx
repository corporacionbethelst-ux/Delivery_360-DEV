'use client';

import { useEffect, useRef, useState } from 'react';
import { riderService } from '@/services/rider.service';

export function DocumentDownloadButton({ documentId, className }: {
  documentId: string; className?: string;
}) {
  const request = useRef<AbortController | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    setPending(false);
    setError(false);
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [documentId]);

  const download = async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError(false);
    try {
      const blob = await riderService.getDocumentFile(documentId, controller.signal);
      if (controller.signal.aborted) return;
      if (!(blob instanceof Blob) || !blob.size) throw new Error('Respuesta inválida');
      const extension = ({ 'application/pdf': 'pdf', 'image/png': 'png', 'image/jpeg': 'jpg' } as Record<string, string>)[blob.type] || 'bin';
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      try {
        link.href = url;
        link.download = `documento-${documentId}.${extension}`;
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  };

  return <div className="relative z-10">
    <button type="button" className={className} onClick={download} disabled={pending}>
      {pending ? 'Descargando…' : 'Descargar documento'}
    </button>
    {error && <span role="alert">No fue posible descargar el documento. Intenta nuevamente.</span>}
  </div>;
}
