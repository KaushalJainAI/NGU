import api from './axiosInstance';

export interface Customer {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  city: string | null;
  state: string | null;
  created_at: string;
  order_count: number;
  total_spent: string;
}

export interface CustomerOrder {
  id: number;
  order_number: string;
  status: string;
  payment_method: string | null;
  total_amount: string;
  created_at: string;
}

export interface CustomerDetail extends Customer {
  address: string;
  orders: CustomerOrder[];
}

export interface PaginatedCustomers {
  count: number;
  next: string | null;
  previous: string | null;
  results: Customer[];
}

export const getCustomers = (search?: string, page = 1) =>
  api.get<PaginatedCustomers>('/admin-customers/', {
    params: { page, ...(search?.trim() ? { search: search.trim() } : {}) },
  });

export const getCustomer = (id: number | string) =>
  api.get<CustomerDetail>(`/admin-customers/${id}/`);
