import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from 'recharts';
import { PALETTE } from '../format';

interface Props {
  data: { label: string; value: number }[];
  color?: string;
  /** Color each bar distinctly (useful for small categorical sets). */
  multicolor?: boolean;
  onClick?: (label: string) => void;
}

/** Horizontal ranked bars — readable labels, sorted magnitude (top-N). */
export const RankedBarChart = ({ data, color = PALETTE[0], multicolor, onClick }: Props) => (
  <ResponsiveContainer width="100%" height="100%">
    <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
      <CartesianGrid strokeDasharray="3 3" className="opacity-30" horizontal={false} />
      <XAxis type="number" fontSize={11} />
      <YAxis type="category" dataKey="label" width={140} fontSize={11} />
      <Tooltip />
      <Bar dataKey="value" fill={color} radius={[0, 4, 4, 0]}
        cursor={onClick ? 'pointer' : undefined}
        onClick={onClick ? (d: any) => onClick(d?.label) : undefined}>
        {multicolor && data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
);
