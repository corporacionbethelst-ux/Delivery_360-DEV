'use client';

import dynamic from 'next/dynamic';

// Leaflet uses window during module evaluation; load the entire map in the browser.
const MapPageContent = dynamic(() => import('./MapPageContent'), {
  ssr: false,
  loading: () => <div role="status">Cargando mapa…</div>,
});

export default function MapPage() {
  return <MapPageContent />;
}
