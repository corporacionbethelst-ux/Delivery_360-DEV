// src/hooks/geolocation.ts
"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface GeoPosition {
  latitude: number;
  longitude: number;
  accuracy: number;
  altitude: number | null;
  heading: number | null;
  speed: number | null;
  timestamp: Date;
}

export interface GeoError {
  code: number;
  message: string;
}

export interface UseGeolocationOptions {
  enableHighAccuracy?: boolean;
  timeout?: number;
  maximumAge?: number;
  watchPosition?: boolean;
  autoStart?: boolean;
}

const defaultOptions: Required<UseGeolocationOptions> = {
  enableHighAccuracy: true,
  timeout: 15000, // Aumentado ligeramente para móviles con GPS lento
  maximumAge: 5000, // Permitir caché muy reciente para velocidad
  watchPosition: true,
  autoStart: true,
};

export const useGeolocation = (options: UseGeolocationOptions = {}) => {
  const { autoStart, watchPosition, enableHighAccuracy, timeout, maximumAge } =
    { ...defaultOptions, ...options };
  const [position, setPosition] = useState<GeoPosition | null>(null),
    [error, setError] = useState<GeoError | null>(null),
    [loading, setLoading] = useState(false),
    [isSupported, setIsSupported] = useState(true);
  const alive = useRef(false),
    sequence = useRef(0),
    watchId = useRef<number | null>(null),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null),
    callbackRef = useRef<((position: GeoPosition) => void) | null>(null);
  const cancel = useCallback(() => {
    sequence.current++;
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (watchId.current !== null) {
      navigator.geolocation?.clearWatch(watchId.current);
      watchId.current = null;
    }
  }, []);
  const startWatching = useCallback(() => {
    cancel();
    if (!alive.current) return;
    const geo =
      typeof navigator === "undefined" ? undefined : navigator.geolocation;
    if (!geo) {
      setIsSupported(false);
      setError({
        code: 0,
        message:
          "La geolocalización no es soportada por este navegador/dispositivo.",
      });
      setLoading(false);
      return;
    }
    setIsSupported(true);
    setLoading(true);
    setError(null);
    const ticket = sequence.current,
      current = () => alive.current && ticket === sequence.current;
    const fail = (code: number, message: string) => {
      if (current()) {
        setError({ code, message });
        setLoading(false);
      }
    };
    const success = (value: GeolocationPosition) => {
      if (!current()) return;
      const coords = value.coords;
      if (
        !Number.isFinite(coords.latitude) ||
        Math.abs(coords.latitude) > 90 ||
        !Number.isFinite(coords.longitude) ||
        Math.abs(coords.longitude) > 180 ||
        !Number.isFinite(coords.accuracy) ||
        coords.accuracy < 0 ||
        !Number.isFinite(new Date(value.timestamp).getTime())
      ) {
        fail(0, "Coordenadas GPS inválidas.");
        return;
      }
      const optional = (number: number | null) =>
        number !== null && Number.isFinite(number) ? number : null;
      const result: GeoPosition = {
        latitude: coords.latitude,
        longitude: coords.longitude,
        accuracy: coords.accuracy,
        altitude: optional(coords.altitude),
        heading:
          coords.heading !== null &&
          coords.heading >= 0 &&
          coords.heading <= 360
            ? optional(coords.heading)
            : null,
        speed:
          coords.speed !== null && coords.speed >= 0
            ? optional(coords.speed)
            : null,
        timestamp: new Date(value.timestamp),
      };
      setPosition(result);
      setError(null);
      setLoading(false);
      try {
        callbackRef.current?.(result);
      } catch {
        console.error("Error en callback de geolocalización");
      }
    };
    const failure = (value: GeolocationPositionError) => {
      const messages: Record<number, string> = {
        1: "Permiso denegado. Por favor habilita el acceso a la ubicación.",
        2: "Ubicación no disponible. Verifica tu conexión GPS/Internet.",
        3: "Tiempo de espera agotado al obtener ubicación.",
      };
      fail(
        value.code,
        messages[value.code] ?? "Error desconocido de geolocalización.",
      );
    };
    try {
      const config = { enableHighAccuracy, timeout, maximumAge };
      if (watchPosition)
        watchId.current = geo.watchPosition(success, failure, config);
      else geo.getCurrentPosition(success, failure, config);
    } catch {
      fail(0, "No se pudo iniciar la geolocalización.");
    }
  }, [cancel, enableHighAccuracy, timeout, maximumAge, watchPosition]);
  useEffect(() => {
    alive.current = true;
    setIsSupported(typeof navigator !== "undefined" && !!navigator.geolocation);
    return () => {
      alive.current = false;
      cancel();
    };
  }, [cancel]);
  useEffect(() => {
    if (autoStart) startWatching();
    return cancel;
  }, [autoStart, startWatching, cancel]);
  const stopWatching = useCallback(() => {
    cancel();
    if (alive.current) setLoading(false);
  }, [cancel]);
  const refreshPosition = useCallback(() => {
    stopWatching();
    timer.current = setTimeout(() => {
      timer.current = null;
      startWatching();
    }, 200);
  }, [stopWatching, startWatching]);
  const setCallback = useCallback(
    (callback: (position: GeoPosition) => void) => {
      callbackRef.current = callback;
    },
    [],
  );
  const calculateDistance = useCallback(
    (latitude: number, longitude: number) => {
      if (
        !position ||
        !Number.isFinite(latitude) ||
        Math.abs(latitude) > 90 ||
        !Number.isFinite(longitude) ||
        Math.abs(longitude) > 180
      )
        return -1;
      const radians = (value: number) => (value * Math.PI) / 180;
      const a =
        Math.sin(radians(latitude - position.latitude) / 2) ** 2 +
        Math.cos(radians(position.latitude)) *
          Math.cos(radians(latitude)) *
          Math.sin(radians(longitude - position.longitude) / 2) ** 2;
      const bounded = Math.max(0, Math.min(1, a));
      return (
        6371000 * 2 * Math.atan2(Math.sqrt(bounded), Math.sqrt(1 - bounded))
      );
    },
    [position],
  );
  const getBearing = useCallback(() => position?.heading ?? null, [position]);
  return {
    position,
    error,
    loading,
    isSupported,
    startWatching,
    stopWatching,
    refreshPosition,
    setCallback,
    calculateDistance,
    getBearing,
    latitude: position?.latitude ?? null,
    longitude: position?.longitude ?? null,
    accuracy: position?.accuracy ?? null,
    speed: position?.speed ?? null,
    heading: position?.heading ?? null,
  };
};
export default useGeolocation;
