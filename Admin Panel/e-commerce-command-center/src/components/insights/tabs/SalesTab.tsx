import { useSales } from '@/hooks/useInsights';
import type { DateRange } from '@/api/analytics';
import { KpiCard } from '../KpiCard';
import { ChartCard } from '../ChartCard';
import { DataTable } from '../DataTable';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';
import { useCsvExport } from '@/hooks/useCsvExport';
import { useTranslation } from 'react-i18next';
import { inr, num } from '../format';

interface Props {
  range: DateRange;
  previousRange: DateRange;
  compare: boolean;
}

export const SalesTab = ({ range, previousRange, compare }: Props) => {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useSales(range);
  const prev = useSales(previousRange, compare);
  const exportCsv = useCsvExport();
  const k = data?.kpis;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard title={t('insights.kpi.revenue')} value={inr(k?.revenue ?? 0)}
          delta={k?.revenue_delta_pct} hint={t('insights.kpi.vsPrev')} />
        <KpiCard title={t('insights.kpi.orders')} value={num(k?.orders ?? 0)}
          delta={k?.orders_delta_pct} hint={t('insights.kpi.vsPrev')} />
        <KpiCard title={t('insights.kpi.aov')} value={inr(k?.aov ?? 0)} />
        <KpiCard title={t('insights.kpi.couponOrders')} value={num(k?.coupon_orders ?? 0)}
          hint={t('insights.kpi.off', { amount: inr(k?.coupon_discount ?? 0) })} />
      </div>

      <ChartCard title={t('insights.sales.overTime')}
        description={compare ? t('insights.sales.compareHint') : undefined}
        height={340} loading={isLoading} error={isError}
        empty={!isLoading && (data?.series.length ?? 0) === 0}
        onExport={() => exportCsv('sales', ['Bucket', 'Revenue', 'Orders', 'Units'],
          (data?.series ?? []).map((s) => [s.bucket, s.revenue, s.orders, s.units]))}>
        <TimeSeriesChart data={data?.series ?? []} compareData={compare ? prev.data?.series : undefined} />
      </ChartCard>

      <div className="grid gap-4 md:grid-cols-2">
        <DataTable title={t('insights.sales.topProducts')}
          cols={[t('insights.col.product'), t('insights.col.units'), t('insights.col.revenue')]}
          rows={(data?.top_products ?? []).map((p) => [p.name, num(p.units), inr(p.revenue)])}
          onExport={() => exportCsv('top_products', ['Product', 'Units', 'Revenue'],
            (data?.top_products ?? []).map((p) => [p.name, p.units, p.revenue]))} />
        <DataTable title={t('insights.sales.topCategories')}
          cols={[t('insights.col.category'), t('insights.col.units'), t('insights.col.revenue')]}
          rows={(data?.top_categories ?? []).map((c) => [c.name, num(c.units), inr(c.revenue)])}
          onExport={() => exportCsv('top_categories', ['Category', 'Units', 'Revenue'],
            (data?.top_categories ?? []).map((c) => [c.name, c.units, c.revenue]))} />
      </div>
    </div>
  );
};
