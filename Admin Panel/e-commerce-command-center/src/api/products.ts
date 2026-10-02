// src/api/products.ts
import api from './axiosInstance';

export interface ProductImage {
  id: number;
  product: number;
  image: string;
  alt_text: string;
}

export interface ProductVariant {
  id: number;
  product?: number;
  slug?: string;
  weight: number | string | null;
  unit: string;
  formatted_weight?: string;
  price: number | string;
  discount_price?: number | string | null;
  final_price?: number;
  discount_percentage?: number;
  stock: number;
  in_stock?: boolean;
  sku?: string;
  is_default: boolean;
  is_active: boolean;
  display_order: number;
}

export type ProductVariantInput = {
  product: number;
  weight: number | string | null;
  unit: string;
  price: number | string;
  discount_price?: number | string | null;
  stock: number;
  sku?: string;
  is_default: boolean;
  is_active: boolean;
  display_order: number;
};

export interface Product {
  id: number;
  slug: string;
  name: string;
  category: number;
  category_name?: string;
  spice_form: string;
  price: number;
  discount_price?: number;
  /** GST rate (%) for this product. Defaults to 5; papad/papad katran are 0. */
  tax_rate?: number | string;
  /**
   * HSN code (4/6/8 digits) this product is classified under for GST returns.
   * '' means not classified yet — every sale of it then lands in the
   * "NOT CLASSIFIED" row of the HSN summary. `tax_rate` says what is charged;
   * this says why, and GSTR-1 Table 12 needs both.
   */
  hsn_code?: string;
  final_price?: number;
  discount_percentage?: number;
  stock: number;
  in_stock?: boolean;
  /** Warn when stock falls to or below this (per-product; backend default 5). */
  low_stock_threshold?: number;
  weight: number;
  unit: string;
  organic?: boolean;
  image?: string;
  is_featured?: boolean;
  is_active?: boolean;
  average_rating?: number;
  created_at?: string;
  badge?: string;
  description?: string;
  ingredients?: string;
  images?: ProductImage[];
  origin_country?: string;
  shelf_life?: string;
  variants?: ProductVariant[];
  variant_count?: number;
  /** IDs of the homepage sections this product is placed in. */
  sections?: number[];
  /** Read-only section names for display. */
  section_names?: string[];
}

/** Replace the set of homepage sections a product is placed in. */
export const updateProductSections = async (slugOrId: string | number, sections: number[]) => {
  const response = await api.patch<Product>(`/products/${slugOrId}/`, { sections });
  return response.data;
};

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export const getProducts = async () => {
  const response = await api.get<PaginatedResponse<Product> | Product[]>('/products/');
  const data = Array.isArray(response.data)
    ? response.data
    : (response.data as PaginatedResponse<Product>).results || [];
  return { data };
};

export const getProduct = async (slugOrId: string | number) => {
  const response = await api.get<Product>(`/products/${slugOrId}/`);
  return response.data;
};

export const createProduct = async (data: FormData) => {
  const response = await api.post<Product>('/products/', data);
  return response.data;
};

export const updateProduct = async (slugOrId: string | number, data: FormData | Partial<Product>) => {
  const response = await api.patch<Product>(`/products/${slugOrId}/`, data);
  return response.data;
};

export const deleteProduct = async (slugOrId: string | number) => {
  await api.delete(`/products/${slugOrId}/`);
};

export const getSpiceForms = async () => {
  const response = await api.get<{ value: string; label: string }[]>('/spice-forms/');
  return response.data;
};

export const createProductImage = async (productId: number, image: File, altText: string) => {
  const formData = new FormData();
  formData.append('product', String(productId));
  formData.append('image', image);
  formData.append('alt_text', altText);

  const response = await api.post<ProductImage>('/product-images/', formData);
  return response.data;
};

export const deleteProductImage = async (id: number) => {
  await api.delete(`/product-images/${id}/`);
};

// ---- Product variants (packaging sizes) ----

export const getProductVariants = async (productId: number | string) => {
  const response = await api.get<ProductVariant[]>(`/product-variants/?product=${productId}`);
  return Array.isArray(response.data) ? response.data : [];
};

export const createProductVariant = async (data: ProductVariantInput) => {
  const response = await api.post<ProductVariant>('/product-variants/', data);
  return response.data;
};

export const updateProductVariant = async (id: number, data: Partial<ProductVariantInput>) => {
  const response = await api.patch<ProductVariant>(`/product-variants/${id}/`, data);
  return response.data;
};

export const deleteProductVariant = async (id: number) => {
  // RETIRES the size (is_active=false); the row is never removed from the DB, so
  // past orders and invoices keep resolving it. 200 on success, 409 if it is the
  // product's last active size or a combo is built from it.
  const response = await api.delete(`/product-variants/${id}/`);
  return response.data;
};