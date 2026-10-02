import { useAnonymous } from '@/hooks/useInsights';
import type { DateRange } from '@/api/analytics';
import { ChartCard } from '../ChartCard';
import { FunnelChart } from '../charts/FunnelChart';
import { DonutChart } from '../charts/DonutChart';
import { IndiaMap } from '../charts/IndiaMap';
import { useTranslation } from 'react-i18next';

export const AnonymousTab = ({ range }: { range: DateRange }) => {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useAnonymous(range);
  const geoValues = Object.fromEntries((data?.by_state ?? []).map((s) => [s.state, s.count]));

  return (
    <div className="space-y-4">
      <ChartCard title={t('insights.anonymousTab.macroFunnel')}
        description={t('insights.anonymousTab.macroFunnelDesc')}
        height={300} loading={isLoading} error={isError}
        empty={!isLoading && (data?.macro_funnel.length ?? 0) === 0}>
        <FunnelChart stages={data?.macro_funnel ?? []} color="#06b6d4" />
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title={t('insights.anonymousTab.byDevice')} height={260} loading={isLoading} error={isError}
          empty={!isLoading && (data?.by_device.length ?? 0) === 0}>
          <DonutChart data={(data?.by_device ?? []).map((d) => ({ label: d.device, value: d.count }))} />
        </ChartCard>
        <ChartCard title={t('insights.anonymousTab.bySource')} height={260} loading={isLoading} error={isError}
          empty={!isLoading && (data?.by_source.length ?? 0) === 0}>
          <DonutChart data={(data?.by_source ?? []).map((d) => ({ label: d.source, value: d.count }))} />
        </ChartCard>
        <ChartCard title={t('insights.anonymousTab.pageViews')} height={260} loading={isLoading} error={isError}>
          <div className="flex h-full flex-col items-center justify-center">
            <span className="text-4xl font-bold">{data?.totals.page_view ?? 0}</span>
            <span className="text-sm text-muted-foreground">{t('insights.anonymousTab.anonPageViews')}</span>
          </div>
        </ChartCard>
      </div>

      <ChartCard title={t('insights.anonymousTab.whereFrom')} description={t('insights.anonymousTab.whereFromDesc')}
        height={440} loading={isLoading} error={isError}
        empty={!isLoading && (data?.by_state.length ?? 0) === 0}>
        <IndiaMap values={geoValues} unit={t('insights.anonymousTab.pageViewsUnit')} />
      </ChartCard>
    </div>
  );
};
