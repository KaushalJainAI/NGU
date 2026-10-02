import { readEnv } from "@/config/runtimeEnv";

// Runtime override (window.APP_CONFIG.API_URL) wins over the build-time value.
const envApiUrl = readEnv("VITE_API_URL");
export const API_BASE_URL = (envApiUrl && envApiUrl.trim() !== "") ? envApiUrl : "/api";

// A relative "/api" is the intended production config: the frontend container
// proxies /api/ to the backend, so requests always resolve against whichever
// domain the user is on. That keeps them same-origin, which is what lets the
// SameSite=Lax auth cookies ride along. One image serves several domains, so an
// absolute URL would pin every one of them to a single API host and silently
// break auth everywhere else.
if (import.meta.env.PROD && /^https?:\/\//.test(API_BASE_URL)) {
  console.warn(
    `API_BASE_URL is absolute (${API_BASE_URL}). Requests from any other domain ` +
    `are cross-site, so SameSite=Lax auth cookies will not be sent.`,
  );
}


/** Shape of the JSON body DRF returns on error responses (all fields optional). */
interface ApiErrorBody {
  error?: string;
  detail?: string;
  message?: string;
  non_field_errors?: string[];
  /**
   * The custom exception handler wraps DRF's real payload:
   *   { success: false, error: "Validation error", details: { ... } }
   * `error` is only ever the generic label, so it must NOT win over `details`.
   */
  details?: Record<string, unknown> | string;
  [key: string]: unknown;
}

/**
 * Pull the most specific human-readable message out of a DRF error payload:
 * a bare string, `{error|detail|message}`, `non_field_errors`, or the first
 * field's first error rendered as "Field: message".
 */
const extractMessage = (body: unknown): string | null => {
  if (typeof body === 'string') return body;
  if (!body || typeof body !== 'object') return null;
  const b = body as ApiErrorBody;

  // A nested {"error": "..."} inside details carries the real reason (e.g.
  // "You have already reviewed this product") — prefer it over the label.
  if (typeof b.error === 'string' && b.error !== 'Validation error') return b.error;
  if (typeof b.detail === 'string') return b.detail;
  if (Array.isArray(b.non_field_errors) && b.non_field_errors.length > 0) {
    return String(b.non_field_errors[0]);
  }
  if (typeof b.message === 'string') return b.message;

  for (const [key, value] of Object.entries(b)) {
    if (key === 'success' || key === 'error' || key === 'details') continue;
    if (Array.isArray(value) && value.length > 0) {
      // e.g. "Title: This field is required."
      const label = key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' ');
      return `${label}: ${value[0]}`;
    }
    if (typeof value === 'string') return value;
  }
  // Nothing more specific than the generic label.
  return typeof b.error === 'string' ? b.error : null;
};

/**
 * Some endpoints wrap their payload in a `{ data: ... }` envelope while others
 * return it directly. `unwrap` normalizes both into the bare payload `T`.
 */
export interface ApiEnvelope<T> {
  data: T;
}

/** Standard DRF paginated list response. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export const unwrap = <T>(res: ApiEnvelope<T> | T): T =>
  res && typeof res === 'object' && 'data' in res
    ? (res as ApiEnvelope<T>).data
    : (res as T);

export class APIError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, statusText: string, data: unknown) {
    // Look INSIDE `details` first. The backend's exception handler returns
    // {success:false, error:"Validation error", details:{...}}, so reading
    // `error` first reduced every field error and every business rule
    // ("You have already reviewed this product") to a useless "Validation error".
    const body = (data && typeof data === 'object' ? data : null) as ApiErrorBody | null;
    const errorMessage =
      (body?.details ? extractMessage(body.details) : null) ??
      extractMessage(data) ??
      statusText;

    super(errorMessage);
    this.status = status;
    this.data = data;
  }
}

/**
 * Definitively end the client session: clear the cached login state and notify
 * the app (AuthContext listens for `auth:unauthorized` and resets `user`). This
 * is the single choke point for logging a user out on an unrecoverable 401 —
 * every terminal-unauthorized path must route through here so the React state
 * and the localStorage cache can never drift apart. Idempotent.
 */
export const forceLogout = (): void => {
  try {
    localStorage.removeItem("user");
  } catch {
    /* storage unavailable — the event below still resets in-memory state */
  }
  window.dispatchEvent(new Event("auth:unauthorized"));
};

let refreshPromise: Promise<boolean> | null = null;

export const refreshAccessToken = async (): Promise<boolean> => {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error("Token refresh failed");
      return true;
    } catch (error) {
      // Refresh token is missing/expired/invalid — the session is over.
      forceLogout();
      throw error;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
};

const getCookie = (name: string): string | null => {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop()?.split(";").shift() || null;
  return null;
};


// config.ts - implementation with HTTPOnly cookies for tokens
// Active storefront language, read from the same localStorage key react-i18next
// uses. Sent as X-Language so backend modeltranslation returns translated
// product/category content (falls back to English when no translation exists).
const getLangHeader = (): Record<string, string> => {
  try {
    const lang = localStorage.getItem("site_lang");
    return lang ? { "X-Language": lang } : {};
  } catch {
    return {};
  }
};

/** A request that never settles leaves the UI spinning forever. */
export const REQUEST_TIMEOUT_MS = 20000;

/**
 * fetch() with a hard timeout. Without one, a stalled connection hangs the
 * promise indefinitely and the calling page shows its loading spinner forever
 * instead of surfacing an error the user can act on.
 */
export const fetchWithTimeout = async (
  url: string,
  options: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<Response> => {
  // Respect a caller-supplied signal by racing it alongside our timeout.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const callerSignal = options.signal;
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError" && !callerSignal?.aborted) {
      throw new Error("The request timed out. Please check your connection and try again.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
};

export const authFetch = async <T = unknown>(url: string, options: RequestInit = {}): Promise<T> => {
  const csrfToken = getCookie("csrftoken");
  const headersObj: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getLangHeader(),
  };
  if (csrfToken) {
    headersObj['X-CSRFToken'] = csrfToken;
  }

  const optionHeaders = options.headers as Record<string, string> | undefined;

  let response = await fetchWithTimeout(url, {
    ...options,
    credentials: "include",
    headers: {
      ...headersObj,
      ...optionHeaders,
    },
  });

  // Handle token expiration
  if (response.status === 401) {
    try {
      await refreshAccessToken();
      const freshCsrfToken = getCookie("csrftoken");
      if (freshCsrfToken) {
        headersObj['X-CSRFToken'] = freshCsrfToken;
      }

      // Retry with new token cookies automatically included
      response = await fetchWithTimeout(url, {
        ...options,
        credentials: "include",
        headers: {
          ...headersObj,
          ...optionHeaders,
        },
      });
    } catch (error) {
      // If refresh fails, refreshAccessToken handles the logout and redirect
    }
  }

  if (!response.ok) {
    // A 401 that survived the refresh-and-retry above is unrecoverable: the
    // session is dead, so log the user out (clears cache AND React state).
    // (403 is "authenticated but forbidden" under our JWT cookie auth — a
    // permission/CSRF denial, not an expired session — so it must NOT log out.)
    if (response.status === 401) {
      forceLogout();
    }
    const errorData = await response.json().catch(() => ({}));
    throw new APIError(response.status, response.statusText, errorData);
  }

  if (response.status === 204) return null as T;

  // Return parsed JSON directly
  return response.json() as Promise<T>;
};


/**
 * Authenticated multipart/form-data POST (e.g. audio upload for voice
 * transcription). Unlike `authFetch`, it does NOT set Content-Type — the browser
 * must set the multipart boundary itself. Mirrors authFetch's CSRF handling and
 * one-shot 401 refresh-and-retry.
 */
/** Uploads (e.g. audio) can legitimately take longer than a JSON call. */
export const UPLOAD_TIMEOUT_MS = 60000;

export const authFetchForm = async <T = unknown>(url: string, form: FormData): Promise<T> => {
  const send = () => {
    const csrfToken = getCookie("csrftoken");
    const headers: Record<string, string> = { ...getLangHeader() };
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
    // Route through fetchWithTimeout so a stalled upload rejects instead of
    // hanging the UI forever (the JSON paths already have this guarantee).
    return fetchWithTimeout(url, { method: "POST", body: form, credentials: "include", headers }, UPLOAD_TIMEOUT_MS);
  };

  let response = await send();
  if (response.status === 401) {
    try {
      await refreshAccessToken();
      response = await send();
    } catch {
      // refreshAccessToken handles logout + redirect on failure.
    }
  }

  if (!response.ok) {
    // Terminal 401 after refresh-and-retry → session is dead, force logout.
    // 403 is a permission/CSRF denial under our JWT cookie auth, not an expired
    // session, so it must not log the user out.
    if (response.status === 401) forceLogout();
    const errorData = await response.json().catch(() => ({}));
    throw new APIError(response.status, response.statusText, errorData);
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
};


export const publicFetch = async <T = unknown>(url: string, options: RequestInit = {}): Promise<T> => {
  const csrfToken = getCookie("csrftoken");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...getLangHeader(),
    ...(csrfToken && { 'X-CSRFToken': csrfToken }),
    ...options.headers,
  };
  const response = await fetchWithTimeout(url, { ...options, headers, credentials: "include" });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new APIError(response.status, response.statusText, errorData);
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
};
