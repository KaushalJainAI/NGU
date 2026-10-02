import api from './axiosInstance';

export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string;
  image?: string;
  is_active?: boolean;
  created_at?: string;
}

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export const getCategories = async () => {
  try {
    const response = await api.get<PaginatedResponse<Category> | Category[]>('/categories/');
    const data = Array.isArray(response.data)
      ? response.data
      : (response.data as PaginatedResponse<Category>).results || [];
    return { data };
  } catch (error) {
    console.error('Failed to fetch categories:', error);
    return { data: [] };
  }
};

export const getCategory = async (slugOrId: string | number) => {
  const response = await api.get<Category>(`/categories/${slugOrId}/`);
  return { data: response.data };
};

export const createCategory = async (data: FormData | Partial<Category>) => {
  const response = await api.post<Category>('/categories/', data);
  return response.data;
};

export const updateCategory = async (slugOrId: string | number, data: FormData | Partial<Category>) => {
  const response = await api.patch<Category>(`/categories/${slugOrId}/`, data);
  return response.data;
};

export const deleteCategory = async (slugOrId: string | number) => {
  await api.delete(`/categories/${slugOrId}/`);
};
