import api from './axiosInstance';

export interface ReceivableAccount {
  id: number;
  account_holder_name: string;
  upi_id: string;
  bank_name: string;
  bank_account_number: string;
  ifsc_code: string;
  branch_name: string;
  contact_email: string;
  contact_phone: string;
  created_at?: string;
  updated_at?: string;
}

export interface ReceivableAccountFormData {
  account_holder_name: string;
  upi_id: string;
  bank_name?: string;
  bank_account_number?: string;
  ifsc_code?: string;
  branch_name?: string;
  contact_email?: string;
  contact_phone?: string;
}

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Fetch all receivable accounts
export const getReceivableAccounts = async () => {
  const response = await api.get<PaginatedResponse<ReceivableAccount> | ReceivableAccount[]>('/receivable-accounts/');
  const data = Array.isArray(response.data)
    ? response.data
    : (response.data as PaginatedResponse<ReceivableAccount>).results || [];
  return { data };
};

// Get single receivable account
export const getReceivableAccount = async (id: number) => {
  const response = await api.get<ReceivableAccount>(`/receivable-accounts/${id}/`);
  return response.data;
};

// Create new receivable account
export const createReceivableAccount = async (data: ReceivableAccountFormData) => {
  const response = await api.post<ReceivableAccount>('/receivable-accounts/', data);
  return response.data;
};

// Update receivable account
export const updateReceivableAccount = async (id: number, data: Partial<ReceivableAccountFormData>) => {
  const response = await api.patch<ReceivableAccount>(`/receivable-accounts/${id}/`, data);
  return response.data;
};

// Delete receivable account
export const deleteReceivableAccount = async (id: number) => {
  await api.delete(`/receivable-accounts/${id}/`);
};
