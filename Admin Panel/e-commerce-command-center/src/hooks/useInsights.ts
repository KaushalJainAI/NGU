import { useQuery } from '@tanstack/react-query';
import {
  getOverviewInsights, getSalesInsights, getFunnelInsights,
  getSearchInsights, getCustomerInsights, getAnonInsights,
  type DateRange,
} from '@/api/analytics';

/**
 * react-query hooks for the admin Insights endpoints. Keyed on the date range
 * so changing it refetches and caches per-window. Manual refresh is exposed via
 * each query's `refetch`. `enabled` lets callers lazily fetch a tab's data.
 */
const key = (name: string, r: DateRange) => ['insights', name, r.from, r.to, r.granularity];

const opts = { staleTime: 60_000, refetchOnWindowFocus: false } as const;

export const useOverview = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('overview', r), queryFn: () => getOverviewInsights(r).then((d) => d.data), enabled, ...opts });

export const useSales = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('sales', r), queryFn: () => getSalesInsights(r).then((d) => d.data), enabled, ...opts });

export const useFunnel = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('funnel', r), queryFn: () => getFunnelInsights(r).then((d) => d.data), enabled, ...opts });

export const useSearch = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('search', r), queryFn: () => getSearchInsights(r).then((d) => d.data), enabled, ...opts });

export const useCustomers = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('customers', r), queryFn: () => getCustomerInsights(r).then((d) => d.data), enabled, ...opts });

export const useAnonymous = (r: DateRange, enabled = true) =>
  useQuery({ queryKey: key('anonymous', r), queryFn: () => getAnonInsights(r).then((d) => d.data), enabled, ...opts });
