import api from './axiosInstance';

export type Granularity = 'day' | 'week' | 'month';

export interface DateRange {
  from: string; // YYYY-MM-DD
  to: string;
  granularity?: Granularity;
}

// ---- Sales ---------------------------------------------------------------

export interface SalesKpis {
  revenue: number;
  orders: number;
  units: number;
  aov: number;
  coupon_orders: number;
  coupon_discount: number;
  revenue_delta_pct: number | null;
  orders_delta_pct: number | null;
}

export interface SalesPoint { bucket: string; revenue: number; orders: number; units: number; }
export interface TopProduct { product_id: number | null; name: string; units: number; revenue: number; }
export interface TopCategory { category_id: number | null; name: string; units: number; revenue: number; }

export interface SalesInsights {
  range: DateRange;
  kpis: SalesKpis;
  series: SalesPoint[];
  top_products: TopProduct[];
  top_categories: TopCategory[];
}

// ---- Funnel --------------------------------------------------------------

export interface FunnelStage {
  stage: string;
  count: number;
  pct_of_top: number | null;
  step_conversion_pct: number | null;
}

export interface FunnelInsights {
  range: DateRange;
  stages: FunnelStage[];
  all_event_counts: Record<string, number>;
}

// ---- Search --------------------------------------------------------------

export interface TermCount { term: string; count: number; }
export interface ViewedNotBought { product_id: number; name: string; views: number; }

export interface SearchInsights {
  range: DateRange;
  top_terms: TermCount[];
  zero_result_terms: TermCount[];
  viewed_not_bought: ViewedNotBought[];
}

// ---- Customers -----------------------------------------------------------

export interface CustomerPoint { bucket: string; new: number; returning: number; }
export interface GeoRow { state: string; users: number; }
export interface TopCustomer { user_id: number; email: string; revenue: number; orders: number; }

export interface CustomerInsights {
  range: DateRange;
  kpis: { new_customers: number; returning_customers: number; repeat_rate_pct: number };
  series: CustomerPoint[];
  geo: GeoRow[];
  top_customers: TopCustomer[];
}

// ---- Anonymous -----------------------------------------------------------

export interface AnonInsights {
  range: DateRange;
  totals: Record<string, number>;
  macro_funnel: FunnelStage[];
  by_device: { device: string; count: number }[];
  by_state: { state: string; count: number }[];
  by_source: { source: string; count: number }[];
}

// ---- Overview ------------------------------------------------------------

export interface OverviewInsights {
  range: DateRange;
  kpis: {
    revenue: number;
    revenue_delta_pct: number | null;
    orders: number;
    orders_delta_pct: number | null;
    aov: number;
    repeat_rate_pct: number;
    anon_page_views: number;
  };
  revenue_series: SalesPoint[];
  funnel: FunnelStage[];
  top_products: TopProduct[];
  anon_by_device: { device: string; count: number }[];
  anon_by_source: { source: string; count: number }[];
}

// ---- API calls -----------------------------------------------------------

const params = (r: DateRange) => ({
  from: r.from,
  to: r.to,
  ...(r.granularity ? { granularity: r.granularity } : {}),
});

export const getOverviewInsights = (r: DateRange) =>
  api.get<OverviewInsights>('/analytics/overview/', { params: params(r) });

export const getSalesInsights = (r: DateRange) =>
  api.get<SalesInsights>('/analytics/sales/', { params: params(r) });

export const getFunnelInsights = (r: DateRange) =>
  api.get<FunnelInsights>('/analytics/funnel/', { params: params(r) });

export const getSearchInsights = (r: DateRange) =>
  api.get<SearchInsights>('/analytics/search/', { params: params(r) });

export const getCustomerInsights = (r: DateRange) =>
  api.get<CustomerInsights>('/analytics/customers/', { params: params(r) });

export const getAnonInsights = (r: DateRange) =>
  api.get<AnonInsights>('/analytics/anonymous/', { params: params(r) });
