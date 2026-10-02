import { API_BASE_URL, authFetch } from "./config";

/**
 * Location APIs: reverse-geocoding (lat/lng -> address) and coarse user-location
 * upsert. Both are backed by analytics endpoints and require auth.
 *
 * Privacy: precise coordinates are only ever sent to the reverse-geocode proxy
 * (to resolve an address). What we persist for recommendations is coarse —
 * city/state/pincode-prefix plus rounded coordinates — and only after the user
 * explicitly shares their location. See Backend analytics.UserGeo.
 */

export interface ReverseGeocodeResult {
  address_line: string;
  city: string;
  state: string;
  pincode: string;
  country: string;
}

export interface UserGeo {
  city: string;
  state: string;
  pincode_prefix: string;
  lat_coarse: string | null;
  lng_coarse: string | null;
  updated_at: string;
}

export const geoAPI = {
  /** Resolve precise coordinates to an address via the server-side proxy. */
  reverseGeocode: (lat: number, lng: number): Promise<ReverseGeocodeResult> =>
    authFetch(`${API_BASE_URL}/geocode/reverse/?lat=${lat}&lng=${lng}`),

  /** Read the stored coarse location (null if the user has none yet). */
  get: (): Promise<UserGeo | null> => authFetch(`${API_BASE_URL}/geo/`),

  /**
   * Upsert the user's coarse location for recommendations. Precise lat/lng may
   * be passed; the backend rounds them before storage.
   */
  update: (data: {
    lat?: number;
    lng?: number;
    city?: string;
    state?: string;
    pincode?: string;
  }): Promise<UserGeo> =>
    authFetch(`${API_BASE_URL}/geo/`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
};
