import { API_BASE_URL, authFetch, publicFetch } from "./config";

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  name?: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
  profile_picture?: string;
}

export interface RegisterPayload {
  first_name?: string;
  last_name?: string;
  name?: string;
  email: string;
  username: string;
  password: string;
  password2: string;
  phone?: string;
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
  profile_picture?: string;
}

/** True for the login response that means "right password, email not confirmed yet". */
export const isEmailNotVerified = (error: unknown): boolean => {
  const e = error as { status?: number; data?: { code?: string } } | null;
  return e?.status === 403 && e?.data?.code === "email_not_verified";
};

export const authAPI = {
  // Uses publicFetch so the CSRF header (X-CSRFToken) is sent. CookieJWTAuthentication
  // enforces CSRF whenever a (possibly stale) access_token cookie rides along, and a
  // bare fetch without the header 403s with "CSRF Failed: CSRF token missing."
  register: async (userData: RegisterPayload) =>
    publicFetch(`${API_BASE_URL}/auth/register/`, {
      method: "POST",
      body: JSON.stringify(userData),
    }),

  login: async (email: string, password: string) =>
    publicFetch(`${API_BASE_URL}/auth/login/`, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  getProfile: () => authFetch<UserProfile>(`${API_BASE_URL}/auth/profile/`),

  updateProfile: (data: Partial<UserProfile>) =>
    authFetch<UserProfile>(`${API_BASE_URL}/auth/profile/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  changePassword: (old_password: string, new_password: string) =>
    authFetch(`${API_BASE_URL}/auth/change-password/`, {
      method: "POST",
      body: JSON.stringify({ old_password, new_password }),
    }),

  // The password goes with the code: the backend only verifies an address
  // for the person who set the account's password (see VerifyEmailConfirmView).
  verifyEmail: (email: string, otp_code: string, password: string) =>
    publicFetch(`${API_BASE_URL}/auth/verify-email/`, {
      method: "POST",
      body: JSON.stringify({ email, otp_code, password }),
    }),

  resendVerification: (email: string) =>
    publicFetch(`${API_BASE_URL}/auth/verify-email/request/`, {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  // Call once without `otp_code` to mail a code to the new address, then again
  // with it to make the switch.
  changeEmail: (new_email: string, current_password: string, otp_code?: string) =>
    authFetch(`${API_BASE_URL}/auth/change-email/`, {
      method: "POST",
      body: JSON.stringify({ new_email, current_password, ...(otp_code ? { otp_code } : {}) }),
    }),

  googleLogin: async (accessToken: string) => {
    const data = await publicFetch(`${API_BASE_URL}/auth/google/`, {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken }),
    });
    return data;
  },
};
