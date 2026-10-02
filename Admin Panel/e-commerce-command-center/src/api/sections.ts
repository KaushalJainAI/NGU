import api from './axiosInstance';

// Homepage section an admin can place a product/combo into.
export interface ProductSection {
  id: number;
  name: string;
  slug: string;
  section_type: string;
  description?: string;
  icon?: string;
  display_order?: number;
  max_products?: number;
  is_active: boolean;
}

// Flat list of sections for the product/combo edit multi-select.
export const getSections = async () => {
  const response = await api.get<ProductSection[]>('/product-sections/');
  return Array.isArray(response.data) ? response.data : [];
};

// A product placed inside a section, in display order.
export interface SectionProduct {
  id: number;
  name: string;
  image: string | null;
  position: number;
  is_active: boolean;
}

export const createSection = async (data: Partial<ProductSection>) => {
  const response = await api.post<ProductSection>('/product-sections/', data);
  return response.data;
};

export const updateSection = async (id: number, data: Partial<ProductSection>) => {
  const response = await api.patch<ProductSection>(`/product-sections/${id}/`, data);
  return response.data;
};

// Soft-hide (backend sets is_active=false; placements survive).
export const hideSection = async (id: number) => {
  await api.delete(`/product-sections/${id}/`);
};

export const getSectionProducts = async (id: number) => {
  const response = await api.get<SectionProduct[]>(`/product-sections/${id}/products/`);
  return response.data;
};

// Replace the section's product list with exactly these ids, in display order.
export const setSectionProducts = async (id: number, productIds: number[]) => {
  const response = await api.put<SectionProduct[]>(
    `/product-sections/${id}/products/`,
    { product_ids: productIds },
  );
  return response.data;
};
