import { toast } from "sonner";
import { API_BASE_URL, authFetch } from "./config";

// An item the /cart/sync/ endpoint could not add (e.g. out of stock, delisted,
// invalid quantity). The backend returns these instead of silently dropping
// them — callers must surface them so the user knows part of their cart didn't
// carry over.
export interface SkippedCartItem {
  id: string;
  type: "product" | "combo";
  reason: string;
}

export interface CartItem {
  id: number;
  product_id: number;
  variant_id?: number | null;
  variant_slug?: string | null;
  item_type: "product" | "combo";
  name: string;
  image: string;
  price: number;
  quantity: number;
  weight?: string;
}

/** One GST rate slab present in the cart (0% papad, 5% spices, …). */
export interface TaxSlab {
  /** GST percentage. `null` only on legacy orders whose rate wasn't recorded. */
  rate: number | null;
  /** Net (pre-GST) value taxed at this rate. */
  taxable_value: number | null;
  tax_amount: number;
}

export interface CartSummary {
  subtotal: number;
  /** GST contained in `subtotal` — prices are inclusive, so never added to `total`. */
  tax: number;
  /** Per-rate breakup of `tax`, for the customer-facing bill. */
  tax_breakdown?: TaxSlab[];
  /** `subtotal` net of the GST inside it. */
  taxable_value?: number;
  /** NET delivery fee — GST-EXCLUSIVE, unlike product prices. See `shipping_tax`. */
  shipping?: number;
  /**
   * GST on the delivery fee (SAC 9968, 18%), charged ON TOP of `shipping`.
   * Goods GST is inside `subtotal` and never added to `total`; this one IS.
   */
  shipping_tax?: number;
  /** All GST the customer pays: `tax` + `shipping_tax`. */
  total_tax?: number;
  /** Order value at/above which delivery is free — drives the "add ₹X more" nudge. */
  free_shipping_threshold?: number;
  discount: number;
  total: number;
}

export interface CartResponse {
  success?: boolean;
  items?: CartItem[];
  summary?: CartSummary;
  skipped?: SkippedCartItem[];
  error?: string;
  message?: string;
}

export interface PaymentQRResponse {
  qr_code_base64: string;
  upi_uri: string;
  amount: number;
  discount_percent: number;
  summary: {
    original: number;
    discount: number;
    final: number;
  };
}

export const cartAPI = {
  get: async () => {
    try {
      const data = await authFetch<CartResponse>(`${API_BASE_URL}/cart/`);
      return data;
    } catch (error) {
      console.error('Get cart error:', error);
      throw error;
    }
  },

  addItem: async (data: {
    product_id: number;
    item_type: "product" | "combo";
    quantity: number;
    variant_id?: number | null;
  }) => {
    try {
      const result = await authFetch<CartResponse>(`${API_BASE_URL}/cart/add_item/`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      return result;
    } catch (error) {
      console.error('Add item error:', error);
      throw error;
    }
  },

  updateItem: async (data: {
    product_id: number;
    item_type: "product" | "combo";
    quantity: number;
    variant_id?: number | null;
  }) => {
    try {
      const result = await authFetch<CartResponse>(`${API_BASE_URL}/cart/update_item/`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      return result;
    } catch (error) {
      console.error('Update item error:', error);
      throw error;
    }
  },

  removeItem: async (data: {
    product_id: number;
    item_type: "product" | "combo";
    variant_id?: number | null;
  }) => {
    try {
      const result = await authFetch<CartResponse>(`${API_BASE_URL}/cart/remove_item/`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      return result;
    } catch (error) {
      console.error('Remove item error:', error);
      throw error;
    }
  },

  clear: async () => {
    try {
      const result = await authFetch<CartResponse>(`${API_BASE_URL}/cart/clear/`, {
        method: "POST",
      });
      return result;
    } catch (error) {
      console.error('Clear cart error:', error);
      throw error;
    }
  },

  sync: async (items: Array<{
    product_id: number;
    item_type: "product" | "combo";
    quantity: number;
    variant_id?: number | null;
  }>) => {
    try {

      
      const data = await authFetch<CartResponse>(`${API_BASE_URL}/cart/sync/`, {
        method: "POST",
        body: JSON.stringify({ items }),
      });

      // Never let items vanish silently: if the backend couldn't add some of
      // them, tell the user which and why.
      if (data?.skipped?.length) {
        const names = data.skipped.map((s) => s.reason).join("; ");
        toast.warning(
          `${data.skipped.length} item(s) couldn't be added to your cart: ${names}`,
        );
      }

      return data;
    } catch (error) {
      console.error('Cart sync error:', error);
      throw error;
    }
  },

  getPaymentQR: async (
    receivableAccountId: number, 
    couponCode?: string
  ): Promise<PaymentQRResponse> => {
    try {
      const payload: { receivable_account_id: number; coupon_code?: string } = {
        receivable_account_id: receivableAccountId,
      };
      
      // Only include coupon_code if it's provided and not empty
      if (couponCode && couponCode.trim()) {
        payload.coupon_code = couponCode.trim();
      }
      
      const result = await authFetch<PaymentQRResponse>(`${API_BASE_URL}/cart/payment_qr/`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      
      return result;
    } catch (error) {
      console.error('Get payment QR error:', error);
      throw error;
    }
  },
};
