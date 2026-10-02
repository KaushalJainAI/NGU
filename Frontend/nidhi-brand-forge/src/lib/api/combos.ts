import { API_BASE_URL, publicFetch } from "./config";

export interface ComboItem {
  product: number;
  product_name: string;
  product_slug: string;
  product_image: string;
  /** Small square crop, when the product has one. Cards prefer it over
   *  `product_image` for collage tiles. */
  product_thumbnail?: string;
  product_price: number;
  /** The exact packaging size this combo bundles. Price and stock come from
   *  here — a combo means "1 x 500g", not "1 x whichever size is default". */
  variant?: number;
  variant_label?: string;
  variant_price?: string;
  variant_stock?: number;
  variant_is_active?: boolean;
  quantity: number;
}

export interface Combo {
  id: number;
  name: string;
  slug: string;
  description?: string;
  title?: string;
  subtitle?: string;
  items: ComboItem[];
  price: number;
  discount_price?: number;
  final_price: number;
  discount_percentage: number;
  image?: string;
  is_active: boolean;
  is_featured: boolean;
  badge?: string;
  total_original_price: number;
  total_weight: string;
  weight?: number;
  unit?: string;
  display_title: string;
}

export const combosAPI = {
  // ComboProductViewSet has pagination_class = None, so list endpoints return a plain array.
  getAll: () => publicFetch<Combo[]>(`${API_BASE_URL}/combos/`),
  getById: (id: number | string) => publicFetch<Combo>(`${API_BASE_URL}/combos/${id}/`),
  getFeatured: () => publicFetch<Combo[]>(`${API_BASE_URL}/combos/?is_featured=true`),
};
