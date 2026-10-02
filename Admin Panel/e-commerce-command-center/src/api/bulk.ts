import api from './axiosInstance';

/** One packaging size of a product (100g, 500g, …) with its own price & stock. */
export interface BulkVariant {
  id: number;
  label: string;
  price: string;
  discount_price: string;
  stock: number;
  low_stock_threshold: number;
  is_default: boolean;
}

export interface BulkProductRow {
  id: number;
  name: string;
  category_name: string;
  price: string;
  discount_price: string;
  stock: number;
  low_stock_threshold: number;
  variants: BulkVariant[];
}

export interface BulkChange {
  id: number;
  /** Omit to edit the product's own price/stock; set to edit one size. */
  variant_id?: number;
  price?: string;
  discount_price?: string;
  stock?: number | string;
}

export interface BulkApplyResult {
  applied: number;
  errors: { row: number; id?: number; error: string }[];
}

export interface ImportRow {
  name: string;
  /** Which packaging the CSV row targets, e.g. "500g". Blank for a sheet with
   *  no `size` column, which the backend resolves to the default size. */
  size?: string;
  id: number | null;
  variant_id?: number | null;
  /** Carries `variant_id` alongside the edited fields, so a preview row can be
   *  handed straight to applyBulkChanges. */
  changes: Record<string, string | number>;
  error: string | null;
}

export interface ImportPreview {
  rows: ImportRow[];
  ok_count: number;
  error_count: number;
}

export const getBulkProducts = () =>
  api.get<BulkProductRow[]>('/admin/bulk-products/');

export const applyBulkChanges = (changes: BulkChange[]) =>
  api.post<BulkApplyResult>('/admin/bulk-products/apply/', { changes });

export const importProductsCsv = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post<ImportPreview>('/admin/bulk-products/import/', form);
};

// File download helpers (blob → browser download). Each carries the auth cookie
// via the shared axios instance.
const downloadBlob = async (url: string, filename: string) => {
  const res = await api.get(url, { responseType: 'blob' });
  const objectUrl = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(objectUrl);
};

export const exportProductsCsv = () =>
  downloadBlob('/admin/products-export/', 'products.csv');

export const exportCustomersCsv = () =>
  downloadBlob('/admin-customers/export/', 'customers.csv');

// Orders export respects whatever filters are currently applied.
export const exportOrdersCsv = (params: Record<string, string | number> = {}) => {
  // scope=all — the CSV is the admin's all-customers export, not "my orders".
  const search = new URLSearchParams(
    { ...params, scope: 'all', export: 'csv' } as Record<string, string>,
  ).toString();
  return downloadBlob(`/orders/?${search}`, 'orders.csv');
};
