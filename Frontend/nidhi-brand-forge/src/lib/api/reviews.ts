import { API_BASE_URL, authFetch, publicFetch } from "./config";

export interface Review {
  id: number;
  item_type: 'product' | 'combo';
  product?: number;
  combo?: number;
  user_name: string;
  item_name: string;
  rating: number;
  title?: string;
  comment: string;
  is_verified_purchase?: boolean;
  is_featured?: boolean;
  created_at: string;
}

/** Home page testimonials strip: admin-picked reviews, topped up to three. */
export interface FeaturedReviewsResponse {
  count: number;
  results: Review[];
}

export interface PaginatedReviewsResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Review[];
}

export interface CreateReviewData {
  item_type: 'product' | 'combo';
  product?: number;
  combo?: number;
  rating: number;
  title?: string;
  comment: string;
}

export interface CanReviewResponse {
  can_review: boolean;
  reason: 'not_purchased' | 'already_reviewed' | null;
}

export const reviewsAPI = {
  getByProduct: (productId: number, page: number = 1): Promise<PaginatedReviewsResponse> =>
    publicFetch(`${API_BASE_URL}/reviews/?product=${productId}&page=${page}`),

  /** Reviews chosen by an admin for the home page (public, no auth). */
  getFeatured: (): Promise<FeaturedReviewsResponse> =>
    publicFetch(`${API_BASE_URL}/reviews/featured/`),

  canReviewProduct: (productId: number): Promise<CanReviewResponse> =>
    authFetch(`${API_BASE_URL}/reviews/can-review/?product=${productId}`),

  canReviewCombo: (comboId: number): Promise<CanReviewResponse> =>
    authFetch(`${API_BASE_URL}/reviews/can-review/?combo=${comboId}`),

  getByCombo: (comboId: number, page: number = 1): Promise<PaginatedReviewsResponse> =>
    publicFetch(`${API_BASE_URL}/reviews/?combo=${comboId}&page=${page}`),

  create: (reviewData: CreateReviewData) =>
    authFetch(`${API_BASE_URL}/reviews/`, {
      method: "POST",
      body: JSON.stringify(reviewData),
    }),

  getUserReviews: () =>
    authFetch(`${API_BASE_URL}/reviews/`),
};

