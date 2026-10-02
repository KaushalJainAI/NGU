import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface KpiCardProps {
  title: string;
  value: string;
  delta?: number | null;
  /** Optional hint shown under the value (e.g. "vs prev period"). */
  hint?: string;
}

const Delta = ({ value }: { value: number | null }) => {
  if (value === null || value === undefined) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const up = value >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center text-xs font-medium ${up ? 'text-success' : 'text-destructive'}`}>
      <Icon className="h-3 w-3 mr-1" />
      {Math.abs(value)}%
    </span>
  );
};

export const KpiCard = ({ title, value, delta, hint }: KpiCardProps) => (
  <Card>
    <CardHeader className="pb-2">
      <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      <div className="text-2xl font-bold">{value}</div>
      <div className="mt-1 flex items-center gap-2">
        {delta !== undefined && <Delta value={delta ?? null} />}
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
    </CardContent>
  </Card>
);
