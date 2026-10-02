import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { useCustomers } from '@/hooks/useInsights';
import type { DateRange } from '@/api/analytics';
import { KpiCard } from '../KpiCard';
import { ChartCard } from '../ChartCard';
import { DataTable } from '../DataTable';
import { RadialGauge } from '../charts/RadialGauge';
import { IndiaMap } from '../charts/IndiaMap';
import { useCsvExport } from '@/hooks/useCsvExport';
import { useTranslation } from 'react-i18next';
import { inr, num, PALETTE } from '../format';

export const CustomersTab = ({ range }: { range: DateRange }) => {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useCustomers(range);
  const exportCsv = useCsvExport();
  const geoValues = Object.fromEntries((data?.geo ?? []).map((g) => [g.state, g.users]));

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <KpiCard title={t('insights.kpi.newCustomers')} value={num(data?.kpis.new_customers ?? 0)} />
        <KpiCard title={t('insights.kpi.returningCustomers')} value={num(data?.kpis.returning_customers ?? 0)} />
        <ChartCard title={t('insights.customersTab.repeatRate')} height={140} loading={isLoading} error={isError}>
          <RadialGauge value={data?.kpis.repeat_rate_pct ?? 0} label={t('insights.customersTab.returning')} />
        </ChartCard>
      </div>

      <ChartCard title={t('insights.customersTab.newVsReturning')} height={300}
        loading={isLoading} error={isError}
        empty={!isLoading && (data?.series.length ?? 0) === 0}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data?.series ?? []}>
            <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
            <XAxis dataKey="bucket" fontSize={11} />
            <YAxis fontSize={11} />
            <Tooltip /><Legend />
            <Bar dataKey="new" stackId="a" fill={PALETTE[1]} name={t('insights.customersTab.new')} />
            <Bar dataKey="returning" stackId="a" fill={PALETTE[0]} name={t('insights.customersTab.returningSeries')} />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t('insights.customersTab.byRegion')} description={t('insights.customersTab.byRegionDesc')}
          height={420} loading={isLoading} error={isError}
          empty={!isLoading && (data?.geo.length ?? 0) === 0}>
          <IndiaMap values={geoValues} unit={t('insights.customersTab.users')} />
        </ChartCard>
        <DataTable title={t('insights.customersTab.topCustomers')}
          cols={[t('insights.col.email'), t('insights.col.orders'), t('insights.col.revenue')]}
          rows={(data?.top_customers ?? []).map((c) => [c.email, num(c.orders), inr(c.revenue)])}
          onExport={() => exportCsv('top_customers', ['Email', 'Orders', 'Revenue'],
            (data?.top_customers ?? []).map((c) => [c.email, c.orders, c.revenue]))} />
      </div>
    </div>
  );
};
