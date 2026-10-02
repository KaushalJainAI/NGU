/**
 * Client-side mirror of the backend bounds (Backend/spices_backend/limits.py).
 *
 * These are the FIRST line of defence (better UX — stop bad input before a round
 * trip); the backend remains the authoritative guard. Keep the defaults in sync
 * with the backend; both are overridable per-environment (Vite VITE_* here).
 */
import { readEnv } from "./runtimeEnv";

function intEnv(name: string, fallback: number): number {
  const raw = readEnv(name);
  const n = raw != null ? parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function numberEnv(name: string, fallback: number): number {
  const raw = readEnv(name);
  const n = raw != null ? Number(raw) : NaN;
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

export const MAX_ITEM_QUANTITY = intEnv("VITE_MAX_ITEM_QUANTITY", 100);
export const MAX_CART_ITEMS = intEnv("VITE_MAX_CART_ITEMS", 50);
export const MAX_REVIEW_COMMENT = intEnv("VITE_MAX_REVIEW_COMMENT", 2000);
// NET delivery fee — GST-EXCLUSIVE, unlike product prices (which are MRP with
// GST inside). Mirrors backend SHIPPING_CHARGE_NET.
//
// ⚠ Renamed from VITE_SHIPPING_CHARGE on purpose: every deployed .env pins that
// to 69 from the era when delivery was untaxed. Reusing the name would have made
// a stale 69 be read as the NET fee and quote 69 + 18% = 81.42 in the cart. The
// old variable is now inert; don't reintroduce it.
export const SHIPPING_CHARGE = numberEnv("VITE_SHIPPING_CHARGE_NET", 59);
// GST on delivery (SAC 9968), ADDED on top of the fee above. Mirrors backend
// SHIPPING_TAX_RATE. Distinct from DEFAULT_TAX_RATE: goods are 0%/5%, the
// delivery service is 18%.
export const SHIPPING_TAX_RATE = numberEnv("VITE_SHIPPING_TAX_RATE", 18);
// Mirrors backend FREE_SHIPPING_THRESHOLD — keep the two defaults identical, or an
// environment that forgets the env var quotes a cutoff the backend won't honour.
export const FREE_SHIPPING_THRESHOLD = numberEnv("VITE_FREE_SHIPPING_THRESHOLD", 499);
// Fallback GST rate mirroring backend DEFAULT_TAX_RATE. Only used as a safety net
// when a line lacks tax_rate — defaulting to the backend rate (not 0) avoids
// quoting a total below what the customer is actually charged.
export const DEFAULT_TAX_RATE = numberEnv("VITE_DEFAULT_TAX_RATE", 5);
// Max total (₹) payable via the online gateway. Mirrors backend
// MAX_ONLINE_ORDER_TOTAL — UPI is capped at ₹1,00,000 per transaction.
export const MAX_ONLINE_ORDER_TOTAL = numberEnv("VITE_MAX_ONLINE_ORDER_TOTAL", 100_000);

/**
 * GST payable ON TOP of a delivery fee, rounded to paisa.
 *
 * The delivery fee is the one GST-EXCLUSIVE figure in the basket: product MRPs
 * already contain their GST (so it is only ever *extracted* for disclosure),
 * while this is a genuine addend to the total. Mirrors
 * `Backend/orders/pricing.py::add_tax` — including the rounding, so a browser
 * quote matches the placed order to the last paisa.
 *
 * Lives here rather than being inlined at each call site because the cart, the
 * checkout page and the checkout fallback all need it, and three copies of a
 * money formula is how they drift apart.
 */
export function shippingTaxFor(shipping: number): number {
  if (!Number.isFinite(shipping) || shipping <= 0) return 0;
  return Math.round(shipping * SHIPPING_TAX_RATE) / 100;
}

/** Clamp a quantity into [1, MAX_ITEM_QUANTITY]; non-finite -> 1. */
export function clampQuantity(q: number): number {
  if (!Number.isFinite(q)) return 1;
  return Math.max(1, Math.min(MAX_ITEM_QUANTITY, Math.floor(q)));
}
