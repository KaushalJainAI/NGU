import {
  ResponsiveContainer, RadialBarChart, RadialBar, PolarAngleAxis,
} from 'recharts';

interface Props {
  value: number;       // 0..100
  label: string;
  color?: string;
}

/** Single bounded percentage as a radial gauge (e.g. repeat-purchase rate). */
export const RadialGauge = ({ value, label, color = '#22c55e' }: Props) => (
  <div className="relative h-full w-full">
    <ResponsiveContainer width="100%" height="100%">
      <RadialBarChart
        innerRadius="70%" outerRadius="100%" data={[{ value }]}
        startAngle={90} endAngle={-270}
      >
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
        <RadialBar dataKey="value" cornerRadius={8} fill={color} background />
      </RadialBarChart>
    </ResponsiveContainer>
    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
      <span className="text-3xl font-bold">{value}%</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  </div>
);
