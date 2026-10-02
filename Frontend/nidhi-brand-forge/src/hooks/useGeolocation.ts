import { useCallback, useState } from "react";

/**
 * Thin wrapper over the browser Geolocation API.
 *
 * Requesting a position triggers the browser's native permission prompt — we
 * never ask for location silently. The hook only exposes the act of asking;
 * callers decide what to do with the coordinates (e.g. reverse-geocode them).
 */

export interface Coords {
  lat: number;
  lng: number;
  accuracy: number;
}

type GeoStatus = "idle" | "prompting" | "granted" | "denied" | "unavailable";

interface UseGeolocation {
  supported: boolean;
  status: GeoStatus;
  error: string | null;
  /** Ask the browser for the current position. Resolves null on failure. */
  request: () => Promise<Coords | null>;
}

export const useGeolocation = (): UseGeolocation => {
  const supported =
    typeof navigator !== "undefined" && "geolocation" in navigator;
  const [status, setStatus] = useState<GeoStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const request = useCallback((): Promise<Coords | null> => {
    if (!supported) {
      setStatus("unavailable");
      setError("Location is not supported on this device.");
      return Promise.resolve(null);
    }

    setStatus("prompting");
    setError(null);

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setStatus("granted");
          resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          });
        },
        (err) => {
          if (err.code === err.PERMISSION_DENIED) {
            setStatus("denied");
            setError("Location permission was denied.");
          } else {
            setStatus("unavailable");
            setError("Could not determine your location.");
          }
          resolve(null);
        },
        { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
      );
    });
  }, [supported]);

  return { supported, status, error, request };
};
