import { useOverview } from '@/hooks/useInsights';
import type { DateRange } from '@/api/analytics';
import { KpiCard } from '../KpiCard';
import { ChartCard } from '../ChartCard';
import { DataTable } from '../DataTable';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';
import { FunnelChart } from '../charts/FunnelChart';
import { DonutChart } from '../charts/DonutChart';
import { useTranslation } from 'react-i18next';
import { inr, num } from '../format';

export const OverviewTab = ({ range }: { range: DateRange }) => {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useOverview(range);
  const k = data?.kpis;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
        <KpiCard title={t('insights.kpi.revenue')} value={inr(k?.revenue ?? 0)}
          delta={k?.revenue_delta_pct} hint={t('insights.kpi.vsPrev')} />
        <KpiCard title={t('insights.kpi.orders')} value={num(k?.orders ?? 0)}
          delta={k?.orders_delta_pct} hint={t('insights.kpi.vsPrev')} />
        <KpiCard title={t('insights.kpi.aov')} value={inr(k?.aov ?? 0)} />
        <KpiCard title={t('insights.kpi.repeatRate')} value={`${k?.repeat_rate_pct ?? 0}%`} />
        <KpiCard title={t('insights.kpi.anonPageViews')} value={num(k?.anon_page_views ?? 0)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t('insights.overview.revenueAndOrders')} loading={isLoading} error={isError}
          empty={!isLoading && (data?.revenue_series.length ?? 0) === 0}>
          <TimeSeriesChart data={data?.revenue_series ?? []} />
        </ChartCard>
        <ChartCard title={t('insights.overview.conversionFunnel')} description={t('insights.overview.loggedInJourney')}
          loading={isLoading} error={isError}
          empty={!isLoading && (data?.funnel.length ?? 0) === 0}>
          <FunnelChart stages={data?.funnel ?? []} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <DataTable title={t('insights.overview.topProducts')}
          cols={[t('insights.col.product'), t('insights.col.revenue')]}
          rows={(data?.top_products ?? []).map((p) => [p.name, inr(p.revenue)])} />
        <ChartCard title={t('insights.overview.anonByDevice')} height={260}
          loading={isLoading} error={isError}
          empty={!isLoading && (data?.anon_by_device.length ?? 0) === 0}>
          <DonutChart data={(data?.anon_by_device ?? []).map((d) => ({ label: d.device, value: d.count }))} />
        </ChartCard>
        <ChartCard title={t('insights.overview.anonBySource')} height={260}
          loading={isLoading} error={isError}
          empty={!isLoading && (data?.anon_by_source.length ?? 0) === 0}>
          <DonutChart data={(data?.anon_by_source ?? []).map((d) => ({ label: d.source, value: d.count }))} />
        </ChartCard>
      </div>
    </div>
  );
};
