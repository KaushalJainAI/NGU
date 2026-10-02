import { useQuery, useQueryClient, QueryKey } from '@tanstack/react-query';

/**
 * The panel's standard list fetch.
 *
 * Wraps React Query so every page gets the same two things the hand-rolled
 * `useState` + `useEffect` fetches could not:
 *
 *  - **Cached back-navigation.** Leaving Orders and coming back re-renders the
 *    rows immediately from cache and revalidates in the background, instead of
 *    blanking the screen and refetching from zero.
 *  - **A first-load / refetch distinction.** `isInitialLoading` is true only
 *    when there is nothing to show yet (draw a skeleton). `refreshing` is a
 *    background revalidation — dim the table, never unmount it.
 */
export function useAdminData<T>(
  key: QueryKey,
  fetcher: () => Promise<T>,
  options?: { enabled?: boolean; refetchInterval?: number },
) {
  const query = useQuery({
    queryKey: key,
    queryFn: fetcher,
    enabled: options?.enabled ?? true,
    refetchInterval: options?.refetchInterval,
  });

  return {
    data: query.data,
    error: query.error,
    /** Nothing cached yet — show a skeleton. */
    isInitialLoading: query.isLoading,
    /** Revalidating over data we already have — dim, don't unmount. */
    refreshing: query.isFetching && !query.isLoading,
    refetch: query.refetch,
  };
}

/**
 * Invalidate cached lists after a mutation. Pages used to call their own
 * `fetchX()` again, which both refetched and (usually) flipped the page back to
 * a blank "Loading…" state; invalidating instead refetches in the background
 * and leaves the current rows on screen.
 */
export function useInvalidate() {
  const queryClient = useQueryClient();
  return (...keys: QueryKey[]) =>
    Promise.all(keys.map(key => queryClient.invalidateQueries({ queryKey: key })));
}
