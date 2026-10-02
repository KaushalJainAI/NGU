import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Mail } from 'lucide-react';
import { useDateRange } from '@/hooks/useDateRange';
import { sendReport } from '@/api/dashboard';
import { useToast } from '@/hooks/use-toast';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';
import { InsightsToolbar } from '@/components/insights/InsightsToolbar';
import { OverviewTab } from '@/components/insights/tabs/OverviewTab';
import { SalesTab } from '@/components/insights/tabs/SalesTab';
import { FunnelTab } from '@/components/insights/tabs/FunnelTab';
import { SearchTab } from '@/components/insights/tabs/SearchTab';
import { CustomersTab } from '@/components/insights/tabs/CustomersTab';
import { AnonymousTab } from '@/components/insights/tabs/AnonymousTab';

const Insights = () => {
  const { t } = useTranslation();
  const controls = useDateRange();
  const { range, previousRange, compare } = controls;
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [sending, setSending] = useState(false);

  // Manual refresh: invalidate all insights queries so they refetch.
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['insights'] });

  const handleSendSummary = async () => {
    setSending(true);
    try {
      await sendReport('weekly');
      toast({
        title: t('insights.summarySentTitle'),
        description: t('insights.summarySentBody'),
      });
    } catch {
      toast({
        title: t('insights.summaryFailedTitle'),
        description: t('insights.summaryFailedBody'),
        variant: 'destructive',
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('insights.title')}</h1>
          <p className="text-muted-foreground">{t('insights.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={handleSendSummary} disabled={sending}>
            <Mail className="mr-2 h-4 w-4" />
            {sending ? t('insights.sending') : t('insights.emailSummary')}
          </Button>
          <InsightsToolbar controls={controls} onRefresh={refresh} />
        </div>
      </div>

      <PageHelp>{t('insights.pageHelp')}</PageHelp>

      <Tabs defaultValue="overview">
        <TabsList className="flex-wrap h-auto">
          <TabsTrigger value="overview">{t('insights.tabs.overview')}</TabsTrigger>
          <TabsTrigger value="sales">{t('insights.tabs.sales')}</TabsTrigger>
          <TabsTrigger value="funnel">{t('insights.tabs.funnel')}</TabsTrigger>
          <TabsTrigger value="search">{t('insights.tabs.search')}</TabsTrigger>
          <TabsTrigger value="customers">{t('insights.tabs.customers')}</TabsTrigger>
          <TabsTrigger value="anonymous">{t('insights.tabs.anonymous')}</TabsTrigger>
        </TabsList>

        <TabsContent value="overview"><OverviewTab range={range} /></TabsContent>
        <TabsContent value="sales">
          <SalesTab range={range} previousRange={previousRange} compare={compare} />
        </TabsContent>
        <TabsContent value="funnel"><FunnelTab range={range} /></TabsContent>
        <TabsContent value="search"><SearchTab range={range} /></TabsContent>
        <TabsContent value="customers"><CustomersTab range={range} /></TabsContent>
        <TabsContent value="anonymous"><AnonymousTab range={range} /></TabsContent>
      </Tabs>
    </div>
  );
};

export default Insights;
