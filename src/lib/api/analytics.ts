import { API_BASE_URL, authFetch } from "./config";

/**
 * Lightweight behavioral event tracker.
 *
 * Two tracks, chosen by auth state:
 *
 * - **Logged-in:** rich per-user events are buffered and flushed in batches to
 *   POST /api/events/ (interval + on tab-hide). These feed recommendations and
 *   the detailed funnel.
 * - **Logged-out (anonymous):** we never identify the visitor or store a row.
 *   Each event is a single fire-and-forget beacon to POST /api/anon-events/
 *   that only increments aggregate counters server-side. No buffering, no
 *   cookies, no session id — broad insight only, never customer-specific.
 *
 * Use {@link track} for the auth-aware dispatcher, or call trackEvent /
 * trackAnon directly when you know the context.
 */

export type TrackEventType =
  | "view"
  | "click"
  | "add_to_cart"
  | "remove_from_cart"
  | "favorite"
  | "search"
  | "purchase"
  | "page_view"
  | "checkout_started"
  | "checkout_completed"
  | "checkout_abandoned"
  // AP11 voice-ordering funnel ("say your shopping list").
  | "voice_used"
  | "voice_confirmed";

/** Aggregate metrics accepted by the anonymous counter endpoint. */
export type AnonMetric =
  | "page_view"
  | "product_view"
  | "add_to_cart"
  | "search"
  | "checkout_started"
  | "checkout_completed";

export interface TrackEventInput {
  event_type: TrackEventType;
  product_id?: number;
  combo_id?: number;
  category_id?: number;
  query?: string;
  metadata?: Record<string, unknown>;
}

const FLUSH_INTERVAL_MS = 10_000;
const MAX_BUFFER = 50;

let buffer: TrackEventInput[] = [];
let timer: ReturnType<typeof setInterval> | null = null;
let listenersBound = false;

// Auth is held in HttpOnly cookies; the cached "user" object is a cheap,
// good-enough signal for whether to bother buffering events at all.
const isLoggedIn = (): boolean => {
  try {
    return !!localStorage.getItem("user");
  } catch {
    return false;
  }
};

// DPDP Act, 2023 — behavioral analytics is non-essential processing, so it only
// runs after the visitor accepts via the cookie/consent notice. "Essential only"
// or no decision yet means we do not track.
const hasAnalyticsConsent = (): boolean => {
  try {
    return localStorage.getItem("cookie_consent") === "accepted";
  } catch {
    return false;
  }
};

const flush = (useKeepalive = false): void => {
  if (buffer.length === 0) return;
  if (!isLoggedIn()) {
    buffer = [];
    return;
  }
  const batch = buffer;
  buffer = [];
  authFetch(`${API_BASE_URL}/events/`, {
    method: "POST",
    body: JSON.stringify(batch),
    keepalive: useKeepalive,
  }).catch(() => {
    // Best-effort: analytics must never disrupt the user experience.
  });
};

const ensureStarted = (): void => {
  if (listenersBound || typeof window === "undefined") return;
  listenersBound = true;
  timer = setInterval(() => flush(false), FLUSH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush(true);
  });
  window.addEventListener("pagehide", () => flush(true));
};

export const trackEvent = (event: TrackEventInput): void => {
  if (!isLoggedIn() || !hasAnalyticsConsent()) return;
  ensureStarted();
  buffer.push(event);
  if (buffer.length >= MAX_BUFFER) flush(false);
};

/** Force an immediate flush (e.g. right after a purchase completes). */
export const flushEvents = (): void => flush(false);

export interface TrackAnonInput {
  metric: AnonMetric;
  product_id?: number;
  query?: string;
  /** Marks a search that returned no results. */
  zero?: boolean;
}

/**
 * Record one anonymous event as a fire-and-forget beacon. No-op for logged-in
 * users (they go through the richer trackEvent path). Uses navigator.sendBeacon
 * when available so it survives page unloads, falling back to keepalive fetch.
 */
export const trackAnon = (input: TrackAnonInput): void => {
  if (isLoggedIn() || typeof window === "undefined" || !hasAnalyticsConsent()) return;
  const url = `${API_BASE_URL}/anon-events/`;
  const body = JSON.stringify(input);
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
      return;
    }
  } catch {
    // fall through to fetch
  }
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // Best-effort: analytics must never disrupt the user experience.
  });
};

/**
 * Auth-aware dispatcher: sends a rich logged-in event when authenticated, or a
 * coarse anonymous counter beacon otherwise. The two payloads differ because
 * anonymous tracking is deliberately aggregate-only.
 */
export const track = (event: TrackEventInput, anon: TrackAnonInput): void => {
  if (isLoggedIn()) {
    trackEvent(event);
  } else {
    trackAnon(anon);
  }
};
