import api from './axiosInstance';

// Status types matching backend Order model
export type OrderStatus = 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'cancelled' | 'delivering' | 'refunded';
export type PaymentMethod = 'COD' | 'ONLINE' | 'stripe' | 'razorpay';

// OrderItem interface matching backend OrderItemListSerializer
export interface OrderItem {
  id: number;
  product_id: number;
  product_name: string;
  quantity: number;
  price: number;
  total: number;
}

/** One GST rate slab on an order (0% papad, 5% spices, …). */
export interface TaxSlab {
  /** GST percentage; `null` only on legacy orders whose rate wasn't recorded. */
  rate: number | null;
  /** Net (pre-GST) value taxed at this rate. */
  taxable_value: number | null;
  tax_amount: number;
}

export type PaymentInstrument = 'upi' | 'card' | 'netbanking' | 'wallet' | string;

// Razorpay payment detail for an order. Admin-only — the backend returns null
// for non-staff requests and for orders with no gateway payment (e.g. COD).
// Instrument fields are populated from the Razorpay webhook, so they may be null
// for payments captured before this was introduced or still in flight.
export interface OrderPayment {
  gateway: string;
  status: string;
  razorpay_payment_id: string | null;
  method: PaymentInstrument | null;
  vpa?: string | null;
  card_last4?: string | null;
  card_network?: string | null;
  card_type?: string | null;
  bank?: string | null;
  wallet?: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  /**
   * Razorpay's cut. ADMIN-ONLY, like the rest of this object.
   * `gateway_tax` is the GST inside the fee — input tax credit, deductible from
   * output tax. `0` means "not reported yet" (a payment completed through the
   * /verify/ callback carries no fee until the webhook lands), never "free".
   */
  gateway_fee?: string;
  gateway_tax?: string;
  /** amount − gateway_fee: what actually reaches the bank. */
  net_settlement?: string;
}

// Order interface matching backend OrderListSerializer / OrderDetailSerializer
export interface Order {
  id: number;
  order_number: string;
  customer_name?: string;
  customer_email?: string;
  status: OrderStatus;
  items: OrderItem[];
  subtotal: number;
  tax: number;
  /**
   * True (all current orders): `tax` is already contained in `subtotal` and is
   * shown as a disclosure line, not an addend. False: a legacy order placed
   * before GST-inclusive pricing, where `tax` was added on top of `subtotal`.
   */
  tax_inclusive?: boolean;
  /** Per-GST-rate breakup of `tax` — same rows the customer's bill shows. */
  tax_breakdown?: TaxSlab[];
  /** `subtotal` net of the GST inside it; null on legacy tax-exclusive orders. */
  taxable_value?: string | null;
  /**
   * What the COURIER charged us for this delivery, admin-entered (0 = not
   * recorded). ADMIN-ONLY — the backend strips this from customer responses.
   */
  shipping_cost?: number | string;
  /** Money returned to the customer so far across all refunds. */
  refunded_amount?: number | string;
  /** GST reversed by those refunds — subtracted from what's owed to the government. */
  refunded_tax?: number | string;
  refunded_at?: string | null;
  /** One entry per refund. `credit_note_number` (CN-000012) is the serial of the
   *  GST credit note evidencing it — quote it on the return, download it from
   *  `/orders/{id}/credit-note/?refund={refund id}`. */
  refunds?: {
    id: number; amount: string; tax_amount: string; created_at: string;
    credit_note_number?: string;
  }[];
  /**
   * The issued tax invoice ({number, issued_at}), or null when none has been
   * issued. Raised at payment confirmation (online) or at DISPATCH (COD) — never
   * at download. Null means there is no document yet, so the invoice action must
   * be hidden; the endpoint returns 409 for those orders.
   */
  invoice?: { number: string; issued_at: string } | null;
  /**
   * NET delivery fee charged on this order; 0 when free shipping applied.
   * GST-EXCLUSIVE, unlike product prices — see `shipping_tax`.
   */
  shipping_charge?: number;
  /**
   * GST on the delivery fee (SAC 9968, 18%), charged ON TOP of
   * `shipping_charge`. Goods carry their GST inside the MRP, so `tax` is never
   * added to the total — this is. 0 on free shipping and on orders placed
   * before delivery was taxed.
   */
  shipping_tax?: number | string;
  /** All output GST on the order: `tax` + `shipping_tax`. Report this, not `tax`. */
  total_tax?: number | string;
  /**
   * Where the supply was made, and the heads `total_tax` therefore falls under.
   * Destination inside the seller's state ⇒ CGST + SGST; outside ⇒ IGST for the
   * SAME amount — this re-heads the tax, it never adds any, so cgst+sgst+igst
   * always equals `total_tax`. `code` is blank on orders placed before place of
   * supply was captured; those are intra-state by definition and `name` still
   * resolves. Correct a misdetected one by PATCHing `place_of_supply_state_code`.
   */
  place_of_supply?: {
    code: string;
    name: string;
    is_interstate: boolean;
    cgst: string;
    sgst: string;
    igst: string;
  };
  /**
   * When an admin confirmed the COD cash was received. NULL on a COD order
   * means the money is still outstanding with the courier. Always null for
   * ONLINE orders, whose money came through the gateway.
   */
  cod_paid_at?: string | null;
  discount: number;
  total: number;
  shipping_address: string;
  phone_number?: string;
  payment_method?: PaymentMethod;
  payment_status?: string;
  payment?: OrderPayment | null;
  tracking_number?: string;
  courier_name?: string;
  tracking_url?: string;
  coupon_code?: string;
  created_at: string;
  updated_at: string;
  is_deleted?: boolean;
  deleted_at?: string | null;
  // Admin-only delivery bill (courier/delivery receipt). Only metadata is sent
  // over the API — the file itself is streamed through a staff-gated endpoint.
  has_delivery_bill?: boolean;
  delivery_bill_uploaded_at?: string | null;
}

export interface OrderFilters {
  status?: OrderStatus;
  dateFrom?: string;
  dateTo?: string;
  paymentMethod?: PaymentMethod;
  minAmount?: number;
  maxAmount?: number;
  sortBy?: 'newest' | 'oldest' | 'highestTotal' | 'lowestTotal';
  search?: string;
}

// DRF PageNumberPagination envelope. The order list is paginated server-side
// (PAGE_SIZE=12), so filters/sort MUST be pushed to the backend — filtering the
// current page in the browser would silently ignore every other page.
export interface PaginatedOrders {
  count: number;
  next: string | null;
  previous: string | null;
  results: Order[];
}

// API functions with correct endpoint paths (trailing slashes for Django).
// Filters map to the server-side query params handled by OrderViewSet.
// `scope=all` explicitly asks for the ADMIN order table (every customer's
// orders, paginated). Without it the backend serves the *customer* view — only
// the caller's own orders as a bare array — which is what the storefront gets.
// The scope follows the request, not the account's is_staff flag, so a shop
// owner's own /my-orders page is never handed the all-customers table.
export const getOrders = (filters?: OrderFilters, page = 1) => {
  const params: Record<string, string | number> = { page, scope: 'all' };
  if (filters?.status) params.status = filters.status;
  if (filters?.paymentMethod) params.payment_method = filters.paymentMethod;
  if (filters?.dateFrom) params.date_from = filters.dateFrom;
  if (filters?.dateTo) params.date_to = filters.dateTo;
  if (filters?.minAmount != null) params.min_amount = filters.minAmount;
  if (filters?.maxAmount != null) params.max_amount = filters.maxAmount;
  if (filters?.sortBy) params.ordering = filters.sortBy;
  if (filters?.search?.trim()) params.search = filters.search.trim();
  return api.get<PaginatedOrders | Order[]>('/orders/', { params });
};

// Recycle Bin: soft-deleted orders only (?deleted=true). The staff order list is
// paginated (PAGE_SIZE=12), so we walk every page and return the FULL flat
// Order[] — the recycle bin has no pagination UI and must show all trashed
// orders, not just the first page. Still handles a bare-array response.
export const getDeletedOrders = async (): Promise<Order[]> => {
  const all: Order[] = [];
  let page = 1;
  // Bounded safety cap so a pathological response can't loop forever.
  for (let guard = 0; guard < 1000; guard++) {
    const response = await api.get<PaginatedOrders | Order[]>('/orders/', {
      params: { deleted: 'true', page, scope: 'all' },
    });
    if (Array.isArray(response.data)) return response.data;
    const data = response.data as PaginatedOrders;
    all.push(...(data.results || []));
    if (!data.next) break;
    page += 1;
  }
  return all;
};

export const getOrder = (id: number | string) =>
  api.get<Order>(`/orders/${id}/`);

/**
 * What an admin may PATCH onto an order. A subset of `Order`, plus one
 * write-only instruction that isn't a field on the model:
 *
 * - `refund_note` is the reason stored against a refund.
 * - `refund_amount` is how much went back. OPTIONAL — omit it and the backend
 *   refunds the whole outstanding balance (the old all-or-nothing behaviour).
 *
 * Sending `status: 'refunded'` records a refund and reverses the matching GST.
 * A PARTIAL amount is allowed and still marks the order 'refunded', so the flag
 * means "a refund was recorded", not "all of it came back" — always render
 * `refunded_amount` next to the status. Re-sending an explicit amount on an
 * already-refunded order records a further partial (refund in instalments).
 * The backend 400s if the amount is non-numeric, <= 0, or exceeds what is
 * still refundable.
 *
 * - `cod_paid` is the "Paid in cash" tick. COD orders only (the backend 400s on
 *   an ONLINE order, so an unpaid gateway order can't be hand-marked settled).
 *   Sending `true` stamps who confirmed it and when, and flips `payment_status`
 *   to 'paid'; `false` reverses a misclick, and is refused once a refund has
 *   been recorded against the payment. A COD order must be ticked BEFORE it can
 *   be refunded — without proof cash arrived, a refund would reverse GST on
 *   money that never came in.
 */
export type OrderUpdatePayload = Partial<
  Pick<Order, 'status' | 'tracking_number' | 'courier_name' | 'tracking_url'
    | 'shipping_address' | 'phone_number'
    | 'payment_status' | 'shipping_cost'>
> & {
  refund_note?: string;
  /** Omit to refund the whole outstanding balance. */
  refund_amount?: string | number;
  /** COD only: confirm (or reverse) receipt of the cash. */
  cod_paid?: boolean;
};

export const updateOrder = (id: number | string, data: OrderUpdatePayload) =>
  api.patch<Order>(`/orders/${id}/`, data);

export const deleteOrder = (id: number | string) => 
  api.delete(`/orders/${id}/`);

export const restoreOrder = (id: number | string) => 
  api.post(`/orders/${id}/restore/`);

// Cancel order action
export const cancelOrder = (id: number | string) =>
  api.post(`/orders/${id}/cancel/`);

// Download the PDF tax invoice / bill for an order and trigger a browser
// download. The endpoint returns a binary PDF (not JSON), so we request a blob
// via the configured axios instance (carries the auth cookie + baseURL). Staff
// access is enforced server-side by OrderViewSet.get_queryset().
// Download the printable packing slip PDF (address + items + COD amount) for
// packing and sticking on the parcel. Staff-only endpoint.
export const downloadPackingSlip = async (
  id: number | string,
  orderNumber?: string,
): Promise<void> => {
  const res = await api.get(`/orders/${id}/packing-slip/`, { responseType: 'blob' });
  const url = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `packing-slip-${orderNumber || `order-${id}`}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

export const downloadOrderInvoice = async (
  id: number | string,
  orderNumber?: string,
): Promise<void> => {
  let res;
  try {
    res = await api.get(`/orders/${id}/invoice/`, { responseType: 'blob' });
  } catch (err: any) {
    // responseType 'blob' means an error BODY is a Blob too, so the server's
    // explanation has to be read back out of it. A 409 ("no invoice issued
    // yet") is a normal state and deserves its real message, not a generic one.
    const blob = err?.response?.data;
    if (blob instanceof Blob) {
      const text = await blob.text().catch(() => '');
      // Parse and throw in SEPARATE steps. Throwing from inside the try meant the
      // catch swallowed our own error and re-threw it only when the message
      // happened not to match one specific parse failure — so a non-JSON body (an
      // nginx 502 HTML page) surfaced to the admin as "Unexpected token <" instead
      // of the real HTTP error.
      let body: { detail?: string; error?: string } | null = null;
      try {
        body = JSON.parse(text);
      } catch {
        body = null;   // not JSON — fall through to the original axios error
      }
      if (body) {
        throw new Error(body.detail || body.error || 'Could not download the invoice.');
      }
    }
    throw err;
  }
  const url = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `invoice-${orderNumber || `order-${id}`}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// Download the GST credit note for a refund. Omit `refundId` for the most
// recent refund on the order; pass one to reach an earlier instalment, since
// each instalment is its own numbered document.
export const downloadCreditNote = async (
  id: number | string,
  refundId?: number | string,
  creditNoteNumber?: string,
): Promise<void> => {
  const res = await api.get(`/orders/${id}/credit-note/`, {
    responseType: 'blob',
    params: refundId ? { refund: refundId } : undefined,
  });
  const url = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `credit-note-${creditNoteNumber || `order-${id}`}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// --- Delivery bill (admin-only) -------------------------------------------
// The courier/delivery receipt an admin stores against an order. The file is
// never exposed via a public storage URL — it is uploaded to and streamed from
// a staff-gated endpoint. Only staff can reach any of these.

export const uploadDeliveryBill = (id: number | string, file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post<{
    success: boolean;
    has_delivery_bill: boolean;
    delivery_bill_uploaded_at: string;
  }>(`/orders/${id}/delivery_bill/`, form);
};

export const deleteDeliveryBill = (id: number | string) =>
  api.delete(`/orders/${id}/delivery_bill/`);

// Fetch the stored delivery bill as a blob and open it in a new browser tab so
// the admin can view (and print/save) it. Streamed through the auth cookie.
export const viewDeliveryBill = async (id: number | string): Promise<void> => {
  const res = await api.get(`/orders/${id}/delivery_bill/`, { responseType: 'blob' });
  const url = window.URL.createObjectURL(res.data as Blob);
  window.open(url, '_blank', 'noopener');
  // Revoke after a delay so the new tab has time to load the object URL.
  setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
};
