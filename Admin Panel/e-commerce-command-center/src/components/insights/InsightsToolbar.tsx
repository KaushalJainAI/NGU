import { useState } from 'react';
import { format } from 'date-fns';
import type { DateRange as DateRangeType } from 'react-day-picker';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { CalendarIcon, RefreshCw } from 'lucide-react';
import type { Granularity } from '@/api/analytics';
import { useDateRange } from '@/hooks/useDateRange';
import { useTranslation } from 'react-i18next';

interface Props {
  controls: ReturnType<typeof useDateRange>;
  onRefresh: () => void;
  refreshing?: boolean;
}

const PRESETS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
];

export const InsightsToolbar = ({ controls, onRefresh, refreshing }: Props) => {
  const { t } = useTranslation();
  const { from, to, granularity, compare, update, setPreset } = controls;
  const [open, setOpen] = useState(false);

  const onPickRange = (r: DateRangeType | undefined) => {
    if (r?.from) update({ from: format(r.from, 'yyyy-MM-dd') });
    if (r?.to) update({ to: format(r.to, 'yyyy-MM-dd') });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-md border">
        {PRESETS.map((p) => (
          <Button key={p.label} variant="ghost" size="sm"
            className="rounded-none first:rounded-l-md"
            onClick={() => setPreset(p.days)}>
            {p.label}
          </Button>
        ))}
      </div>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="gap-2">
            <CalendarIcon className="h-4 w-4" />
            {from} → {to}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="range"
            defaultMonth={new Date(from)}
            selected={{ from: new Date(from), to: new Date(to) }}
            onSelect={onPickRange}
            numberOfMonths={2}
          />
        </PopoverContent>
      </Popover>

      <Select value={granularity} onValueChange={(v) => update({ gran: v as Granularity })}>
        <SelectTrigger className="w-28 h-9"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="day">{t('insights.toolbar.daily')}</SelectItem>
          <SelectItem value="week">{t('insights.toolbar.weekly')}</SelectItem>
          <SelectItem value="month">{t('insights.toolbar.monthly')}</SelectItem>
        </SelectContent>
      </Select>

      <div className="flex items-center gap-2">
        <Switch id="compare" checked={compare} onCheckedChange={(v) => update({ compare: v })} />
        <Label htmlFor="compare" className="text-sm font-normal">{t('insights.toolbar.compare')}</Label>
      </div>

      <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing} className="gap-2">
        <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        {t('insights.toolbar.refresh')}
      </Button>
    </div>
  );
};
