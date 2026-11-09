"use client";

import dynamic from "next/dynamic";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import { riderReadRoles } from "@/lib/rider-display";

// Leaflet uses window during module evaluation; load the entire map in the browser.
const MapPageContent = dynamic(() => import("./MapPageContent"), {
  ssr: false,
  loading: () => <div role="status">Cargando mapa…</div>,
});

export default function MapPage() {
  return (
    <ManagerPageBoundary scope="rider-map" roles={riderReadRoles}>
      <MapPageContent />
    </ManagerPageBoundary>
  );
}
