import { API_BASE_URL, authFetch } from "./config";

export const favoritesAPI = {
  get: async () => {
    try {
      return await authFetch(`${API_BASE_URL}/favorites/`);
    } catch {
      const stored = localStorage.getItem("favorites_full");
      return stored ? JSON.parse(stored) : [];
    }
  },

  add: async (productId: string | number) => {
    try {
      return await authFetch(`${API_BASE_URL}/favorites/`, {
        method: "POST",
        body: JSON.stringify({ product_id: productId }),
      });
    } catch {
      return { success: true };
    }
  },

  remove: async (productId: string | number) => {
    try {
      return await authFetch(`${API_BASE_URL}/favorites/${productId}/`, {
        method: "DELETE",
      });
    } catch {
      return { success: true };
    }
  },

  sync: async (items: unknown[]) => {
    try {
      return await authFetch(`${API_BASE_URL}/favorites/sync/`, {
        method: "POST",
        body: JSON.stringify({ items }),
      });
    } catch {
      return { success: true };
    }
  },
};
