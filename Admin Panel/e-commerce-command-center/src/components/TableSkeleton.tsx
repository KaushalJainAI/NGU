import { Skeleton } from '@/components/ui/skeleton';

/**
 * Placeholder rows for a table that is loading for the FIRST time.
 *
 * Deliberately shaped like the table it replaces: the page keeps its height,
 * so headers, search box and toolbar stay exactly where they are instead of the
 * whole screen collapsing to a centered "Loading…" and snapping back — which is
 * what makes a refetch feel like a page reload.
 */
export const TableSkeleton = ({ rows = 6, columns = 5 }: { rows?: number; columns?: number }) => (
  <div className="space-y-2" aria-busy="true" aria-live="polite">
    {Array.from({ length: rows }).map((_, r) => (
      <div key={r} className="flex items-center gap-4 py-2">
        {Array.from({ length: columns }).map((_, c) => (
          <Skeleton
            key={c}
            className="h-4 flex-1"
            style={{ maxWidth: c === 0 ? '8rem' : undefined }}
          />
        ))}
      </div>
    ))}
  </div>
);
