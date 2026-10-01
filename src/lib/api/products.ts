import { API_BASE_URL, authFetch, publicFetch } from "./config";
import { Combo } from "./combos";

export interface ProductVariant {
  id: number;
  slug: string;
  weight: number | null;
  unit: string | null;
  formatted_weight: string;
  price: number;
  discount_price?: number | null;
  final_price: number;
  discount_percentage: number;
  // AP8/S12: exact counts are staff-only now — absent on the storefront
  // session. Use `in_stock` for availability; the server enforces quantities.
  stock?: number;
  in_stock: boolean;
  sku?: string;
  is_default: boolean;
  is_active: boolean;
  display_order: number;
}

export interface Product {
  id: number;
  name: string;
  slug: string;
  category: number;
  category_name?: string;
  description: string;
  spice_form: string;
  price: number;
  discount_price?: number;
  final_price: number;
  discount_percentage: number;
  // AP8/S12: staff-only now — absent on the storefront session (see ProductVariant note).
  stock?: number;
  weight: number;
  unit: string;
  origin_country?: string;
  organic: boolean;
  shelf_life?: string;
  ingredients?: string;
  recipe?: string;
  nutrition?: Record<string, string> | null;
  image: string;
  images?: { id: number; product: number; image: string; alt_text?: string }[];
  is_active: boolean;
  is_featured: boolean;
  badge?: string;
  average_rating: number;
  reviews_count: number;
  in_stock: boolean;
  created_at?: string;
  sections?: number[];
  section_names?: string[];
  // Multiple-packaging support
  variants?: ProductVariant[];
  variant_count?: number;
  // Set only when a variant slug was used to fetch this product
  selected_variant_id?: number;
}

export interface ProductSection {
  id: number;
  name: string;
  slug: string;
  section_type: string;
  description?: string;
  icon?: string;
  display_order: number;
  max_products: number;
  is_active: boolean;
  products: Product[];
  combos: Combo[];
}

export const productsAPI = {
  getAll: (params?: { category?: string; search?: string }) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append("category", params.category);
    if (params?.search) queryParams.append("search", params.search);
    const query = queryParams.toString();
    // ProductViewSet has pagination_class = None, so list endpoints return a plain array.
    return publicFetch<Product[]>(`${API_BASE_URL}/products/${query ? `?${query}` : ""}`);
  },

  getById: (id: number | string) => publicFetch<Product>(`${API_BASE_URL}/products/${id}/`),

  // FIXED: Detail endpoint by slug, not list filter
  getBySlug: (slug: string) => publicFetch<Product>(`${API_BASE_URL}/products/${slug}/`),

  getByCategory: (categoryId: string) =>
    publicFetch<Product[]>(`${API_BASE_URL}/products/?category=${categoryId}`),

  getFeatured: () => publicFetch<Product[]>(`${API_BASE_URL}/products/?is_featured=true`),

  getSections: () => publicFetch<ProductSection[]>(`${API_BASE_URL}/products/sections/`),

  getSpiceForms: () => publicFetch<string[]>(`${API_BASE_URL}/spice-forms/`),
};
