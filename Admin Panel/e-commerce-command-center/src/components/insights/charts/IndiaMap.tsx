import { useMemo, useState } from 'react';
import indiaMap from '@svg-maps/india';
import { useTranslation } from 'react-i18next';
import { num } from '../format';

interface Props {
  /** state name (as returned by GeoIP region_name) -> value */
  values: Record<string, number>;
  unit?: string;
}

// Linear interpolate between a light and a deep indigo by intensity 0..1.
const colorFor = (t: number) => {
  if (t <= 0) return '#eef2ff';
  const from = [199, 210, 254]; // indigo-200
  const to = [67, 56, 202];     // indigo-700
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
};

const normalize = (s: string) => s.trim().toLowerCase();

/**
 * India choropleth coloured by per-state value. Matches the data's state names
 * (case-insensitive) against the SVG map's location names; unmatched states
 * render in the empty colour. No projection/topojson needed — the package ships
 * ready-to-render SVG paths.
 */
export const IndiaMap = ({ values, unit = '' }: Props) => {
  const { t } = useTranslation();
  const [hover, setHover] = useState<{ name: string; value: number } | null>(null);

  const byName = useMemo(() => {
    const m: Record<string, number> = {};
    Object.entries(values).forEach(([k, v]) => { m[normalize(k)] = v; });
    return m;
  }, [values]);

  const max = useMemo(
    () => Math.max(1, ...Object.values(values)),
    [values],
  );

  return (
    <div className="relative h-full w-full">
      <svg viewBox={indiaMap.viewBox} className="h-full w-full" role="img" aria-label={t('insights.indiaMapLabel')}>
        {indiaMap.locations.map((loc) => {
          const value = byName[normalize(loc.name)] ?? 0;
          return (
            <path
              key={loc.id}
              d={loc.path}
              fill={colorFor(value / max)}
              stroke="#fff"
              strokeWidth={0.5}
              onMouseEnter={() => setHover({ name: loc.name, value })}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: 'default' }}
            />
          );
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute left-2 top-2 rounded bg-popover px-2 py-1 text-xs shadow border">
          <span className="font-medium">{hover.name}</span>: {num(hover.value)}{unit ? ` ${unit}` : ''}
        </div>
      )}
    </div>
  );
};
