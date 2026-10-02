import api from './axiosInstance';

export type DiscountType = 'percent' | 'fixed';

export interface Coupon {
  id: number;
  code: string;
  discount_type: DiscountType;
  /** Set when discount_type === 'percent', null otherwise. */
  discount_percent: number | null;
  /** Flat ₹ off — set when discount_type === 'fixed', null otherwise.
   *  DRF serialises DecimalField as a string. */
  discount_amount: string | null;
  /** Non-null = special coupon: only this customer may redeem it. */
  assigned_user: number | null;
  /** Read-only convenience field from the backend, so the list can name the
   *  bound customer without a second lookup. */
  assigned_user_email: string | null;
  is_active: boolean;
  valid_until: string | null;
  /** Global redemption cap; null = unlimited. */
  max_usage: number | null;
  usage_count: number;
  minimum_order_amount: string;
}

/** Writable shape. Both discount fields are always sent — the unused one as
 *  null — so switching a coupon between % and ₹ never leaves a stale value. */
export interface CouponFormData {
  code: string;
  discount_type: DiscountType;
  discount_percent: number | null;
  discount_amount: string | null;
  assigned_user: number | null;
  is_active: boolean;
  valid_until: string | null;
  max_usage: number | null;
  minimum_order_amount: string;
}

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Fetch all coupons (handles both paginated and array responses)
export const getCoupons = async () => {
  const response = await api.get<PaginatedResponse<Coupon> | Coupon[]>('/coupons/');
  const data = Array.isArray(response.data)
    ? response.data
    : (response.data as PaginatedResponse<Coupon>).results || [];
  return { data };
};

// Fetch single coupon by ID
export const getCoupon = async (id: number) => {
  const response = await api.get<Coupon>(`/coupons/${id}/`);
  return response.data;
};

// Create new coupon
export const createCoupon = async (data: CouponFormData) => {
  const response = await api.post<Coupon>('/coupons/', data);
  return response.data;
};

// Update existing coupon (partial update) - supports both form data and JSON
export const updateCoupon = async (id: number, data: Partial<CouponFormData> | Record<string, any>) => {
  const response = await api.patch<Coupon>(`/coupons/${id}/`, data);
  return response.data;
};

// Delete coupon
export const deleteCoupon = async (id: number) => {
  await api.delete(`/coupons/${id}/`);
};

// Validate coupon code — admin check that a code exists and is redeemable
// (active, not expired, usage limit not reached).
export interface CouponValidation {
  valid: boolean;
  reason?: string | null;
  coupon?: Coupon;
  error?: string;
}

export const validateCoupon = async (code: string): Promise<CouponValidation> => {
  const response = await api.post<CouponValidation>('/coupons/validate/', { code });
  return response.data;
};

/** Human-readable discount for a coupon of either type. */
/** The badge text for a coupon's discount.
 *
 *  Takes `t` rather than building the sentence itself: "OFF" is UI copy, and an
 *  api/ module has no React context to translate it in. */
export const formatDiscount = (
  coupon: Coupon,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string =>
  coupon.discount_type === 'fixed'
    ? t('coupons.amountOff', {
        amount: Number(coupon.discount_amount || 0).toLocaleString('en-IN'),
      })
    : t('coupons.percentOff', { percent: coupon.discount_percent ?? 0 });
