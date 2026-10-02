import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';
import { PALETTE } from '../format';

interface Props {
  data: { label: string; value: number }[];
}

/** Part-to-whole for small categorical sets (device, traffic source). */
export const DonutChart = ({ data }: Props) => (
  <ResponsiveContainer width="100%" height="100%">
    <PieChart>
      <Pie data={data} dataKey="value" nameKey="label" cx="50%" cy="50%"
        innerRadius={50} outerRadius={80} paddingAngle={2}
        label={(d: any) => d?.label}>
        {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
      </Pie>
      <Tooltip />
      <Legend />
    </PieChart>
  </ResponsiveContainer>
);
