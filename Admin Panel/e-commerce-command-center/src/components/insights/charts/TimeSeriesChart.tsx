import {
  ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, Brush,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { PALETTE } from '../format';

export interface SeriesPoint { bucket: string; revenue: number; orders: number; units?: number; }

interface Props {
  data: SeriesPoint[];
  /** Optional previous-period series for the compare overlay. */
  compareData?: SeriesPoint[];
}

/**
 * Revenue (area, left axis) + orders (line, right axis) over time. Shows a
 * ghosted previous-period revenue line when compareData is supplied, and a
 * brush for zooming longer ranges.
 */
export const TimeSeriesChart = ({ data, compareData }: Props) => {
  const { t } = useTranslation();
  // Align compare series by index so both render on the same X categories.
  const merged = data.map((d, i) => ({
    ...d,
    prevRevenue: compareData?.[i]?.revenue,
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={merged} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
        <XAxis dataKey="bucket" fontSize={11} />
        <YAxis yAxisId="left" fontSize={11} />
        <YAxis yAxisId="right" orientation="right" fontSize={11} />
        <Tooltip />
        <Legend />
        <Area yAxisId="left" type="monotone" dataKey="revenue" name={t('insights.series.revenue')}
          stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2} />
        {compareData && (
          <Line yAxisId="left" type="monotone" dataKey="prevRevenue" name={t('insights.series.prevRevenue')}
            stroke={PALETTE[5]} strokeDasharray="4 4" strokeWidth={1.5} dot={false} />
        )}
        <Line yAxisId="right" type="monotone" dataKey="orders" name={t('insights.series.orders')}
          stroke={PALETTE[1]} strokeWidth={2} dot={false} />
        {data.length > 12 && <Brush dataKey="bucket" height={20} stroke={PALETTE[0]} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
};
