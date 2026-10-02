import { useEffect, useState } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { TableSkeleton } from '@/components/TableSkeleton';

/**
 * Shown while a lazily-loaded route chunk is downloading.
 *
 * Nothing is drawn for the first 150 ms: a cached chunk resolves in a few
 * milliseconds, and flashing a skeleton for one frame reads as a glitch — worse
 * than a brief pause. Past that threshold the page shape appears, so a slow
 * connection gets feedback instead of a frozen screen.
 */
export const RouteFallback = () => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 150);
    return () => clearTimeout(timer);
  }, []);

  if (!visible) return null;

  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-2">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <TableSkeleton rows={8} columns={5} />
    </div>
  );
};
