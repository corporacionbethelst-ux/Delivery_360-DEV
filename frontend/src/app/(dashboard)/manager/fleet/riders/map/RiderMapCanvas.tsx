"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import {
  OperationNotice,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { riderDate, riderName, riderVehicle } from "@/lib/rider-display";
import {
  riderMapAvailability,
  riderMapStatuses,
  riderMapTelephone,
  type RiderMapFocus,
  type RiderMapPoint,
} from "@/lib/rider-map";

type Props = {
  points: RiderMapPoint[];
  focus: RiderMapFocus | null;
  fitSequence: number;
};
const icon = (online: boolean) =>
  L.divIcon({
    className: "rider-position-marker",
    html: `<span style="display:block;width:28px;height:28px;border:4px solid white;border-radius:50%;background:${online ? "#047857" : "#64748b"};box-shadow:0 2px 6px #0f172a55"></span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
const onlineIcon = icon(true),
  neutralIcon = icon(false);
function Viewport({ points, focus, fitSequence }: Props) {
  const map = useMap(),
    initialized = useRef(false),
    previousFit = useRef(fitSequence);
  useEffect(() => {
    const fitting = previousFit.current !== fitSequence;
    previousFit.current = fitSequence;
    if (!points.length) {
      initialized.current = false;
      map.setView([0, 0], 2, { animate: false });
      return;
    }
    if (points.length && (!initialized.current || fitting)) {
      map.fitBounds(L.latLngBounds(points.map((point) => point.position)), {
        padding: [35, 35],
        maxZoom: 14,
        animate: false,
      });
      initialized.current = true;
    }
  }, [map, points, fitSequence]);
  useEffect(() => {
    if (focus) map.setView(focus.position, 15, { animate: false });
  }, [focus, map]);
  useEffect(() => {
    const observer = new ResizeObserver(() =>
      map.invalidateSize({ pan: false }),
    );
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
}
export default function RiderMapCanvas(props: Props) {
  const [tileError, setTileError] = useState(false),
    [tileGeneration, setTileGeneration] = useState(0);
  const failTile = useCallback(() => setTileError(true), []);
  return (
    <>
      {tileError && (
        <div className="p-4">
          <OperationNotice role="alert" tone="warning">
            <p>
              No se pudo cargar parte del fondo cartográfico. Las coordenadas y
              el listado siguen disponibles.
            </p>
            <button
              className={operationStyles.button}
              onClick={() => {
                setTileError(false);
                setTileGeneration((value) => value + 1);
              }}
            >
              Reintentar fondo del mapa
            </button>
          </OperationNotice>
        </div>
      )}
      <MapContainer
        center={[0, 0]}
        zoom={2}
        scrollWheelZoom={false}
        style={{ height: "clamp(360px, 65vh, 650px)", width: "100%" }}
        className="z-0"
      >
        <TileLayer
          key={tileGeneration}
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          eventHandlers={{ tileerror: failTile }}
        />
        <Viewport {...props} />
        {props.points.map(({ rider, position }) => {
          const name = riderName(rider),
            vehicle = riderVehicle(rider),
            telephone = riderMapTelephone(rider.phone);
          return (
            <Marker
              key={rider.id}
              position={position}
              icon={rider.is_online === true ? onlineIcon : neutralIcon}
              title={`${name} · ${rider.id}`}
            >
              <Popup>
                <div className="max-w-[230px] space-y-3 text-sm">
                  <h3 className="break-words font-bold text-slate-900">
                    {name}
                  </h3>
                  <div className="break-all font-mono text-xs">
                    ID: {rider.id}
                  </div>
                  <div>{riderMapAvailability(rider)}</div>
                  <div>
                    Estado:{" "}
                    {riderMapStatuses[
                      rider.status as keyof typeof riderMapStatuses
                    ] ||
                      rider.status ||
                      "No informado"}
                  </div>
                  <div className="break-all">
                    {rider.email || "Email no informado"}
                  </div>
                  <div className="break-all">
                    {vehicle.type} · {vehicle.plate}
                  </div>
                  <div>
                    Reportada: {riderDate(rider.last_location_at)} ·
                    America/Caracas
                  </div>
                  <div className="font-mono text-xs">
                    {position.map((value) => value.toFixed(6)).join(", ")}
                  </div>
                  <Link
                    className={operationStyles.link}
                    href={`/manager/fleet/riders/${encodeURIComponent(rider.id)}`}
                  >
                    Ver perfil
                  </Link>
                  {telephone && (
                    <a
                      className={operationStyles.link}
                      href={telephone}
                      aria-label={`Llamar a ${name}`}
                    >
                      Llamar al repartidor
                    </a>
                  )}
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </>
  );
}
