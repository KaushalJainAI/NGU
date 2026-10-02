// lib/api/orders.ts
import { API_BASE_URL, authFetch, unwrap, ApiEnvelope } from "./config";
import type { TaxSlab } from "./cart";

export interface CreateOrderPayload {
  shipping_address: string;
  phone_number?: string;
  payment_method?: string;
  coupon_code?: string;
  /**
   * Destination state and PIN, sent ALONGSIDE the flattened `shipping_address`
   * rather than instead of it. The backend needs the state on its own to decide
   * the GST place of supply — CGST+SGST for a delivery inside the seller's
   * state, IGST outside it — and cannot reliably recover it from the address
   * blob. Optional on the wire: an order must never fail to place over a
   * tax-reporting field, so the backend falls back to parsing the address and
   * then to the seller's own state.
   */
  shipping_state?: string;
  shipping_pincode?: string;
}

export interface CouponValidationResponse {
  valid?: boolean;
  message?: string;
  error?: string;
  coupon_code?: string;
  discount_amount?: number;
  discount_percent?: number;
  discount_type?: string;
  discount_value?: number;
  /** NET delivery fee — GST-EXCLUSIVE, unlike product prices. See `shipping_tax`. */
  shipping_charge?: number;
  /**
   * GST on the delivery fee (SAC 9968, 18%), charged ON TOP of `shipping_charge`.
   * Goods GST is already inside `subtotal` and is never added to `total_amount`;
   * this one IS, so a summary that drops it no longer reconciles.
   */
  shipping_tax?: number;
  subtotal?: number;
  /** Subtotal after the coupon discount, before delivery. */
  discounted_subtotal?: number;
  /** GST contained in `subtotal` (goods only) — a disclosure figure, not an addend. */
  tax?: number;
  /** All GST the customer pays: `tax` + `shipping_tax`. */
  total_tax?: number;
  total_amount?: number;
  savings?: number;
  /** A full-value coupon leaves nothing to pay — placed without a gateway call. */
  is_zero_total?: boolean;
}

export interface OrderItem {
  id: number;
  item_type: 'product' | 'combo';
  product_id: number | null;
  combo_id: number | null;
  product_name: string;
  image: string | null;
  quantity: number;
  price: number;
  total: number;
}

export interface Order {
  id: number;
  order_number: string;
  status: string;
  items: OrderItem[];
  subtotal: number;
  tax: number;
  /** GST on the delivery fee, ADDED on top of `shipping_charge` (18%, SAC 9968). */
  shipping_tax?: number | string;
  /** All output GST on the order: `tax` + `shipping_tax`. */
  total_tax?: number | string;
  /**
   * True (all current orders): `tax` is already contained in `subtotal` and must
   * not be added into `total`. False: a legacy order placed before GST-inclusive
   * pricing, where `tax` was added on top. Absent on very old cached responses —
   * treat that as inclusive.
   */
  tax_inclusive?: boolean;
  /** Per-GST-rate breakup of `tax`, from the order's stored line snapshots. */
  tax_breakdown?: TaxSlab[];
  /** `subtotal` net of the GST inside it; null on legacy tax-exclusive orders. */
  taxable_value?: string | null;
  /** Delivery fee charged on this order; 0 when free shipping applied. */
  shipping_charge?: number;
  discount: number;
  total: number;
  shipping_address: string;
  tracking_number?: string;
  courier_name?: string;
  tracking_url?: string;
  payment_method?: string;
  payment_status?: "pending" | "processing" | "paid" | "failed" | "refunded";
  /**
   * Money returned to the customer so far. A refund may be PARTIAL, so
   * `status: 'refunded'` on its own does NOT mean the full order came back —
   * always show this amount alongside the status, never the status alone.
   */
  refunded_amount?: number | string;
  /** GST reversed by those refunds (informational; already inside the amount). */
  refunded_tax?: number | string;
  /** When the most recent refund was recorded. */
  refunded_at?: string | null;
  /** One row per refund, oldest first — a refund can be settled in instalments. */
  refunds?: { id: number; amount: string; tax_amount: string; created_at: string }[];
  /**
   * The issued tax invoice, or null when none has been issued yet. An invoice is
   * raised once payment is confirmed (online) or the order is dispatched (COD) —
   * NOT at download time. Null means there is no document to fetch, so the
   * download button must be hidden rather than left to fail with a 409.
   */
  invoice?: { number: string; issued_at: string } | null;
  created_at: string;
  updated_at: string;
}

// The order-placement response wraps the created order plus the top-level fields
// the checkout flow needs immediately: order_id + total (a zero-total coupon
// order comes back already paid, so no gateway call is required).
export interface CreateOrderResult {
  message: string;
  order_id: number;
  order_number: string;
  total_amount: number;
  order: Order;
}

export const ordersAPI = {
  getAll: async (): Promise<Order[]> => {
    const res = await authFetch<ApiEnvelope<Order[]> | Order[]>(`${API_BASE_URL}/orders/`);
    return unwrap(res);
  },

  getById: async (id: string): Promise<Order> => {
    const res = await authFetch<ApiEnvelope<Order> | Order>(`${API_BASE_URL}/orders/${id}/`);
    return unwrap(res);
  },

  create: async (orderData: CreateOrderPayload): Promise<CreateOrderResult> => {
    // The placement endpoint returns a wrapper (order_id + total_amount + the
    // created order), not a bare Order — the checkout flow needs order_id and
    // the total to decide whether a Razorpay call is required.
    return authFetch<CreateOrderResult>(`${API_BASE_URL}/orders/`, {
      method: "POST",
      body: JSON.stringify(orderData),
    });
  },

  cancel: async (id: number): Promise<Order> => {
    const res = await authFetch<ApiEnvelope<Order> | Order>(`${API_BASE_URL}/orders/${id}/cancel/`, {
      method: "POST",
    });
    return unwrap(res);
  },

  validateCoupon: async (couponCode: string): Promise<CouponValidationResponse> => {
    const res = await authFetch<ApiEnvelope<CouponValidationResponse> | CouponValidationResponse>(
      `${API_BASE_URL}/orders/validate_coupon/`,
      {
        method: "POST",
        body: JSON.stringify({ coupon_code: couponCode }),
      },
    );
    return unwrap(res);
  },

  // Download the PDF invoice/bill for an order and trigger a browser download.
  // The endpoint returns a binary PDF (not JSON), so we fetch the blob directly
  // instead of going through authFetch.
  downloadInvoice: async (id: number, orderNumber?: string): Promise<void> => {
    const res = await fetch(`${API_BASE_URL}/orders/${id}/invoice/`, {
      credentials: "include",
    });
    if (!res.ok) {
      // 409 = no invoice has been issued for this order yet (payment not
      // confirmed, or a COD parcel not yet dispatched). That is a normal state,
      // not a failure, so pass the server's explanation through rather than
      // reporting a generic download error.
      if (res.status === 409) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || body?.error || "No invoice has been issued yet.");
      }
      throw new Error("Failed to download invoice");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `invoice-${orderNumber || `order-${id}`}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  },
};
