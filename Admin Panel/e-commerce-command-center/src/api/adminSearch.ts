import api from './axiosInstance';

// Grouped results from the one-box global admin search (/api/admin-search/).
export interface SearchOrderHit {
  id: number;
  order_number: string;
  customer: string;
  status: string;
  total: string;
}

export interface SearchProductHit {
  id: number;
  slug: string;
  name: string;
  stock: number;
  price: string;
  is_active: boolean;
}

export interface SearchCustomerHit {
  id: number;
  name: string;
  email: string;
  phone: string;
}

export interface SearchCouponHit {
  id: number;
  code: string;
  is_active: boolean;
}

export interface GlobalSearchResults {
  orders: SearchOrderHit[];
  products: SearchProductHit[];
  customers: SearchCustomerHit[];
  coupons: SearchCouponHit[];
}

export const globalSearch = (q: string) =>
  api.get<GlobalSearchResults>('/admin-search/', { params: { q } });
