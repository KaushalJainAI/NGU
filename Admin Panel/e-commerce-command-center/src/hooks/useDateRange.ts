import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { DateRange, Granularity } from '@/api/analytics';

const iso = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
};

const VALID_GRAN: Granularity[] = ['day', 'week', 'month'];

/**
 * Dashboard date-range + granularity + compare state, synced to the URL query
 * string so a view is shareable and survives reload. Defaults to the last
 * 30 days, daily granularity.
 */
export const useDateRange = () => {
  const [params, setParams] = useSearchParams();

  const from = params.get('from') || iso(daysAgo(29));
  const to = params.get('to') || iso(new Date());
  const granularity = (VALID_GRAN.includes(params.get('gran') as Granularity)
    ? params.get('gran')
    : 'day') as Granularity;
  const compare = params.get('compare') === '1';

  const range: DateRange = useMemo(
    () => ({ from, to, granularity }),
    [from, to, granularity],
  );

  // The immediately-preceding window of equal length (for compare overlays).
  const previousRange: DateRange = useMemo(() => {
    const start = new Date(from);
    const end = new Date(to);
    const spanDays = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
    const prevEnd = new Date(start);
    prevEnd.setDate(prevEnd.getDate() - 1);
    const prevStart = new Date(prevEnd);
    prevStart.setDate(prevStart.getDate() - (spanDays - 1));
    return { from: iso(prevStart), to: iso(prevEnd), granularity };
  }, [from, to, granularity]);

  const update = useCallback(
    (patch: Partial<{ from: string; to: string; gran: Granularity; compare: boolean }>) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        if (patch.from) next.set('from', patch.from);
        if (patch.to) next.set('to', patch.to);
        if (patch.gran) next.set('gran', patch.gran);
        if (patch.compare !== undefined) next.set('compare', patch.compare ? '1' : '0');
        return next;
      });
    },
    [setParams],
  );

  const setPreset = useCallback(
    (days: number) => update({ from: iso(daysAgo(days - 1)), to: iso(new Date()) }),
    [update],
  );

  return { range, previousRange, granularity, compare, from, to, update, setPreset };
};
