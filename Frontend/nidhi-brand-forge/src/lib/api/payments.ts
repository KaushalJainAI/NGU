import { API_BASE_URL, authFetch, Paginated } from "./config";

export interface PaymentMethod {
  id: number;
  payment_type: "UPI" | "CARD" | "NETBANKING" | "WALLET";
  is_default: boolean;
  is_active: boolean;
  upi_id?: string;
  card_last_four?: string;
  card_brand?: string;
  card_expiry_month?: number;
  card_expiry_year?: number;
  bank_name?: string;
  wallet_provider?: string;
  masked_display: string;
  created_at: string;
}

export const paymentMethodsAPI = {
  getAll: () => authFetch<Paginated<PaymentMethod>>(`${API_BASE_URL}/payment-methods/`),

  getDefault: () => authFetch(`${API_BASE_URL}/payment-methods/default/`),

  getByType: (type: string) =>
    authFetch(`${API_BASE_URL}/payment-methods/by_type/?type=${type}`),

  create: (data: Partial<PaymentMethod>) =>
    authFetch(`${API_BASE_URL}/payment-methods/`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  update: (id: number, data: Partial<PaymentMethod>) =>
    authFetch(`${API_BASE_URL}/payment-methods/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    authFetch(`${API_BASE_URL}/payment-methods/${id}/`, {
      method: "DELETE",
    }),

  setDefault: (id: number) =>
    authFetch(`${API_BASE_URL}/payment-methods/${id}/set_default/`, {
      method: "POST",
    }),

  getStats: () => authFetch(`${API_BASE_URL}/payment-methods/stats/`),
};


// ---------------------------------------------------------------------------
// Razorpay online-payment gateway (create-order / verify / status)
// ---------------------------------------------------------------------------

export interface CreatePaymentOrderResponse {
  razorpay_order_id: string;
  razorpay_key_id: string;
  amount: number; // paise
  currency: string;
  order_id: number;
}

export interface VerifyPaymentPayload {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface VerifyPaymentResponse {
  success: boolean;
  order_id: number;
  status?: "cancelled";
  message?: string;
}

export interface PaymentStatusResponse {
  order_id: number;
  payment_status: "pending" | "processing" | "paid" | "failed" | "refunded";
  order_status: string;
  label: string;
  razorpay_payment_id: string | null;
}

export const razorpayAPI = {
  // Create (or fetch the existing) Razorpay order for a placed, payable Order.
  createOrder: (orderId: number): Promise<CreatePaymentOrderResponse> =>
    authFetch(`${API_BASE_URL}/payments/create-order/`, {
      method: "POST",
      body: JSON.stringify({ order_id: orderId }),
    }),

  // L1 confirmation from the browser after Razorpay Checkout succeeds.
  // `success: false` with status 'cancelled' means the order was cancelled before
  // the capture landed — the charge is routed to an automatic refund.
  verify: (payload: VerifyPaymentPayload): Promise<VerifyPaymentResponse> =>
    authFetch(`${API_BASE_URL}/payments/verify/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Honest, non-alarming payment state — poll after Checkout so the "paid but
  // /verify/ not yet confirmed" window shows "Confirming…", not a false failure.
  getStatus: (orderId: number): Promise<PaymentStatusResponse> =>
    authFetch(`${API_BASE_URL}/payments/status/?order_id=${orderId}`),
};
