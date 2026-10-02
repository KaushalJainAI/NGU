import { ReactNode } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Download, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ChartCardProps {
  title: string;
  description?: string;
  /** Height of the chart body in px. */
  height?: number;
  loading?: boolean;
  error?: boolean;
  /** True when there is genuinely no data to plot. */
  empty?: boolean;
  /** Overrides the default "no data" line; already-translated text. */
  emptyText?: string;
  onExport?: () => void;
  children: ReactNode;
}

/**
 * Standard wrapper for every visualization: title/description, an optional CSV
 * export button, and consistent loading / error / empty states so individual
 * charts stay focused on rendering data.
 */
export const ChartCard = ({
  title, description, height = 300, loading, error, empty,
  emptyText, onExport, children,
}: ChartCardProps) => {
  const { t } = useTranslation();
  return (
  <Card>
    <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0 pb-4">
      <div className="min-w-0 space-y-1.5">
        <CardTitle className="text-xl leading-tight">{title}</CardTitle>
        {description && <CardDescription className="leading-snug">{description}</CardDescription>}
      </div>
      {onExport && (
        <Button variant="ghost" size="icon" className="shrink-0" onClick={onExport} title={t('insights.chart.exportCsv')}>
          <Download className="h-4 w-4" />
        </Button>
      )}
    </CardHeader>
    <CardContent>
      <div style={{ minHeight: height }} className="flex items-center justify-center">
        {loading ? (
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        ) : error ? (
          <p className="text-sm text-destructive">{t('insights.chart.loadFailed')}</p>
        ) : empty ? (
          <p className="text-sm text-muted-foreground">
            {emptyText ?? t('insights.chart.noData')}
          </p>
        ) : (
          <div className="w-full h-full">{children}</div>
        )}
      </div>
    </CardContent>
  </Card>
  );
};
