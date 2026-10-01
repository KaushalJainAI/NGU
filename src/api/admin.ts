import api from './axiosInstance';

// Matches backend UserSerializer fields
export interface AdminInfo {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
  profile_picture?: string;
  created_at?: string;
  is_staff: boolean;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

// Match SimpleJWT-style response
export interface LoginResponse {
  access: string;
  refresh: string;
  user?: {
    id: number;
    email: string;
    first_name?: string;
    last_name?: string;
    is_staff: boolean;
    is_superuser: boolean;
  };
}

// Call Django admin JWT endpoint (separate admin session cookies)
export const login = (credentials: LoginCredentials) =>
  api.post<LoginResponse>('/auth/admin/login/', credentials);

export const googleLogin = (credential: string) =>
  api.post('/auth/admin/google/', { id_token: credential });

// Get admin profile (uses auth/profile endpoint)
export const getAdminInfo = () => api.get<AdminInfo>('/auth/profile/');

// Update admin profile
export const updateAdminInfo = (data: Partial<AdminInfo> & { password?: string }) =>
  api.patch<AdminInfo>('/auth/profile/', data);

// Logout (just clears tokens on frontend)
export const logout = () => {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('refresh_token');
};
