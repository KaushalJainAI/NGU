import { useSearch } from '@/hooks/useInsights';
import type { DateRange } from '@/api/analytics';
import { ChartCard } from '../ChartCard';
import { DataTable } from '../DataTable';
import { RankedBarChart } from '../charts/RankedBarChart';
import { useCsvExport } from '@/hooks/useCsvExport';
import { useTranslation } from 'react-i18next';
import { num, PALETTE } from '../format';

export const SearchTab = ({ range }: { range: DateRange }) => {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useSearch(range);
  const exportCsv = useCsvExport();

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t('insights.searchTab.topTerms')} height={320}
          loading={isLoading} error={isError}
          empty={!isLoading && (data?.top_terms.length ?? 0) === 0}
          onExport={() => exportCsv('top_terms', ['Term', 'Searches'],
            (data?.top_terms ?? []).map((t) => [t.term, t.count]))}>
          <RankedBarChart data={(data?.top_terms ?? []).slice(0, 12).map((t) => ({ label: t.term, value: t.count }))} />
        </ChartCard>
        <ChartCard title={t('insights.searchTab.zeroResults')} description={t('insights.searchTab.zeroResultsDesc')}
          height={320} loading={isLoading} error={isError}
          empty={!isLoading && (data?.zero_result_terms.length ?? 0) === 0}
          emptyText={t('insights.searchTab.zeroResultsEmpty')}
          onExport={() => exportCsv('zero_result_terms', ['Term', 'Searches'],
            (data?.zero_result_terms ?? []).map((t) => [t.term, t.count]))}>
          <RankedBarChart color={PALETTE[3]}
            data={(data?.zero_result_terms ?? []).slice(0, 12).map((t) => ({ label: t.term, value: t.count }))} />
        </ChartCard>
      </div>

      <DataTable title={t('insights.searchTab.viewedNotBought')}
        cols={[t('insights.col.product'), t('insights.col.views')]}
        rows={(data?.viewed_not_bought ?? []).map((p) => [p.name, num(p.views)])}
        onExport={() => exportCsv('viewed_not_bought', ['Product', 'Views'],
          (data?.viewed_not_bought ?? []).map((p) => [p.name, p.views]))} />
    </div>
  );
};
