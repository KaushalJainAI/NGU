import { API_BASE_URL, authFetch } from "./config";

export interface CouponValidation {
  valid: boolean;
  discount_percent?: number;
  discount_amount?: number;
  message?: string;
}

export const couponsAPI = {
  validate: (code: string) =>
    authFetch(`${API_BASE_URL}/auth/validate-coupon/`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  getAll: () => authFetch(`${API_BASE_URL}/coupons/`),
};
