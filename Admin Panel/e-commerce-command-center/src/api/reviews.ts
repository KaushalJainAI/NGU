import api from './axiosInstance';

export interface Review {
  id: number;
  item_type: 'product' | 'combo';
  product: number | null;
  combo: number | null;
  user: number;
  user_name: string;
  item_name: string;
  rating: number;
  title: string;
  comment: string;
  is_verified_purchase: boolean;
  is_hidden: boolean;
  is_featured: boolean;
  created_at: string;
}

/** Home page testimonial slots. Must match reviews.models.MAX_FEATURED_REVIEWS. */
export const MAX_FEATURED_REVIEWS = 3;

export interface PaginatedReviews {
  count: number;
  next: string | null;
  previous: string | null;
  results: Review[];
}

// Staff moderation list: every review across all products (?all=true).
export const getAllReviews = (page = 1) =>
  api.get<PaginatedReviews | Review[]>('/reviews/', { params: { all: 'true', page } });

// The reviews currently pinned to the home page, across every page of the table.
export const getFeaturedReviews = () =>
  api.get<PaginatedReviews | Review[]>('/reviews/', {
    params: { all: 'true', featured: 'true' },
  });

export const setReviewHidden = (id: number, hidden: boolean) =>
  api.post<{ id: number; is_hidden: boolean; is_featured: boolean }>(
    `/reviews/${id}/set-hidden/`, { hidden });

/** Pick/unpick a review for the home page. Backend caps the total at 3. */
export const setReviewFeatured = (id: number, featured: boolean) =>
  api.post<{ id: number; is_featured: boolean; featured_count: number; max_featured: number }>(
    `/reviews/${id}/set-featured/`, { featured });

export const deleteReview = (id: number) => api.delete(`/reviews/${id}/`);
