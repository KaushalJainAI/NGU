import { API_BASE_URL, publicFetch, authFetch } from "./config";

export interface SearchProduct {
  id: number;
  name: string;
  slug: string;
  type: string;
  category: string;
  spice_form: string;
  price: number;
  original_price: number;
  discount: number;
  weight: number;
  unit: string;
  image: string;
  score: number;
  score_type: string;
  in_stock: number;
  is_featured: boolean;
}

export interface SearchResponse {
  query: string;
  total_results: number;
  products: SearchProduct[];
  combos: unknown[];
  stats: {
    direct_matches: number;
    other_recs: number;
  };
}

export interface Suggestion {
  id: number;
  name: string;
  slug: string;
  type: "product" | "combo";
  price: number;
  image: string | null;
}

export interface SuggestResponse {
  query: string;
  suggestions: Suggestion[];
}

export const searchAPI = {
  search: async (query: string, total_results: number = 20): Promise<SearchResponse> => {
    const queryParams = new URLSearchParams();
    queryParams.append("q", query);
    if (total_results) {
      queryParams.append("top_k", total_results.toString());
    }
    const queryString = queryParams.toString();
    return publicFetch<SearchResponse>(`${API_BASE_URL}/search/?${queryString}`);
  },

  /**
   * Lightweight autocomplete suggestions for the navbar search box.
   */
  suggest: async (query: string, limit: number = 8): Promise<SuggestResponse> => {
    const queryParams = new URLSearchParams();
    queryParams.append("q", query);
    queryParams.append("limit", limit.toString());
    return publicFetch<SuggestResponse>(`${API_BASE_URL}/search/suggest/?${queryParams.toString()}`);
  },

  /**
   * Personalized product recommendations for the logged-in user.
   *
   * Calls GET /api/recommendations/ (per-user, signal-based). For logged-out
   * users the endpoint returns 401, which we swallow and return an empty result
   * so callers transparently fall back to their static/popular content.
   */
  getRecommendations: async (
    limit: number = 8,
    context: string = "home",
  ): Promise<SearchResponse> => {
    try {
      const params = new URLSearchParams({ limit: limit.toString(), context });
      const res = await authFetch<{ products?: SearchProduct[] }>(`${API_BASE_URL}/recommendations/?${params.toString()}`);
      const products = res?.products || [];
      return {
        query: "",
        total_results: products.length,
        products,
        combos: [],
        stats: { direct_matches: products.length, other_recs: 0 },
      };
    } catch {
      return {
        query: "",
        total_results: 0,
        products: [],
        combos: [],
        stats: { direct_matches: 0, other_recs: 0 },
      };
    }
  },
};
