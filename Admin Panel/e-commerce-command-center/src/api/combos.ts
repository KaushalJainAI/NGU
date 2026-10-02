// src/api/combos.ts
import api from './axiosInstance';

export interface ComboItem {
  id?: number;
  product: number;         // product ID
  product_name?: string;
  product_slug?: string;
  /** The exact packaging size this combo bundles. Price and stock come from
   *  here — a combo means "1 x 500g", not "1 x whichever size is default". */
  variant: number;
  variant_label?: string;
  variant_price?: string;
  variant_stock?: number;
  variant_is_active?: boolean;
  quantity: number;
}

export interface Combo {
  id: number;
  slug: string;
  name: string;
  display_title?: string;
  title?: string;
  subtitle?: string;
  description?: string;
  /** READ-ONLY MRP. Derived server-side as the sum of the component sizes'
   *  prices — posting it does nothing. Change the components to change it. */
  price: number;
  /** The only price an admin sets: what the bundle actually sells for.
   *  Must be below `price`. */
  discount_price?: number;
  final_price?: number;
  discount_percentage?: number;
  /** Same figure as `price`; kept because the storefront renders it as the
   *  strike-through. */
  total_original_price?: number;
  total_weight?: string;
  weight?: number;
  unit?: string;
  image?: string;
  is_featured?: boolean;
  is_active: boolean;
  badge?: string;
  /** Alert the admin when the buildable count falls to/below this. */
  low_stock_threshold?: number;
  /** Read-only: how many combos can still be built (scarcest component). */
  available_stock?: number;
  created_at?: string;
  items?: ComboItem[];
  products?: number[];  // Product IDs in combo
  /** IDs of the homepage sections this combo is placed in. */
  sections?: number[];
  /** Read-only section names for display. */
  section_names?: string[];
}

/** Replace the set of homepage sections a combo is placed in. */
export const updateComboSections = async (slugOrId: string | number, sections: number[]) => {
  const response = await api.patch<Combo>(`/combos/${slugOrId}/`, { sections }, {
    headers: { 'Content-Type': 'application/json' },
  });
  return response.data;
};

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export const getCombos = async () => {
  const response = await api.get<PaginatedResponse<Combo> | Combo[]>('/combos/');
  const data = Array.isArray(response.data)
    ? response.data
    : (response.data as PaginatedResponse<Combo>).results || [];
  return { data };
};

export const getCombo = async (slugOrId: string | number) => {
  const response = await api.get<Combo>(`/combos/${slugOrId}/`);
  return response.data;
};

export const createCombo = async (formData: FormData) => {
  const response = await api.post<Combo>('/combos/', formData);
  return response.data;
};

export const updateCombo = async (slugOrId: string | number, data: FormData | Partial<Combo>) => {
  const isFormData = data instanceof FormData;
  const response = await api.patch<Combo>(`/combos/${slugOrId}/`, data, {
    headers: isFormData 
      ? {} // Let axios set Content-Type with boundary for FormData
      : { 'Content-Type': 'application/json' },
  });
  return response.data;
};

export const deleteCombo = async (slugOrId: string | number) => {
  await api.delete(`/combos/${slugOrId}/`);
};