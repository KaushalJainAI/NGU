import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getHsnCoverage, getHsnSummary, exportHsnSummaryCsv,
  getGstSummary, getGstB2c, getGstDocuments,
  exportGstSummaryCsv, exportGstB2cCsv, exportGstDocumentsCsv,
  exportInvoiceRegisterCsv, exportCreditNoteRegisterCsv,
} from '@/api/gst';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { Download, AlertTriangle, Loader2 } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { TableSkeleton } from '@/components/TableSkeleton';
import { useTranslation } from 'react-i18next';

/** Inclusive [from, to] for the PREVIOUS calendar month — the period GSTR-1 is
 *  filed for. Matches the backend's default so the screen and a bare API call
 *  show the same thing. */
const lastMonth = () => {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  const start = new Date(end.getFullYear(), end.getMonth(), 1);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: iso(start), to: iso(end) };
};

const money = (n: number) =>
  `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const GstReport = () => {
  const { t } = useTranslation();
  const defaults = lastMonth();
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  // The applied range, separate from the inputs, so typing a date doesn't fire
  // a query per keystroke on what is a table-scanning report.
  const [range, setRange] = useState(defaults);
  const [downloading, setDownloading] = useState<string | null>(null);
  const { toast } = useToast();

  const { data: summary, isLoading } = useQuery({
    queryKey: ['hsn-summary', range.from, range.to],
    queryFn: () => getHsnSummary(range.from, range.to),
  });
  const { data: coverage } = useQuery({
    queryKey: ['hsn-coverage'],
    queryFn: getHsnCoverage,
  });
  const { data: gst, isLoading: gstLoading } = useQuery({
    queryKey: ['gst-summary', range.from, range.to],
    queryFn: () => getGstSummary(range.from, range.to),
  });
  const { data: b2c, isLoading: b2cLoading } = useQuery({
    queryKey: ['gst-b2c', range.from, range.to],
    queryFn: () => getGstB2c(range.from, range.to),
  });
  const { data: docs, isLoading: docsLoading } = useQuery({
    queryKey: ['gst-documents', range.from, range.to],
    queryFn: () => getGstDocuments(range.from, range.to),
  });

  const download = async (key: string, fn: () => Promise<void>) => {
    setDownloading(key);
    try {
      await fn();
    } catch {
      toast({ title: t('gst.downloadFailed'), variant: 'destructive' });
    } finally {
      setDownloading(null);
    }
  };

  const dlBtn = (label: string, dlKey: string, fn: () => Promise<void>) => (
    <Button variant="outline" size="sm" onClick={() => download(dlKey, fn)} disabled={downloading === dlKey}>
      {downloading === dlKey
        ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        : <Download className="mr-2 h-4 w-4" />}
      {label}
    </Button>
  );

  const summaryRows = gst ? [
    { label: t('gst.invoicesRow', { defaultValue: 'Invoices' }), block: gst.invoices },
    { label: t('gst.creditNotesRow', { defaultValue: 'Credit notes' }), block: gst.credit_notes },
    { label: t('gst.netRow', { defaultValue: 'Net' }), block: gst.net },
  ] : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">{t('gst.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('gst.subtitle')}</p>
        </div>
        {dlBtn(t('gst.downloadCsv'), 'hsn', () => exportHsnSummaryCsv(range.from, range.to))}
      </div>

      <PageHelp>
        <p>{t('gst.help1')}</p>
        <p>
          {t('gst.help2Prefix')}
          <strong>{t('gst.help2Strong')}</strong>
          {t('gst.help2Middle')}
          <strong>{t('gst.help2Not')}</strong>
          {t('gst.help2Suffix')}
        </p>
        <p>
          {t('gst.help3Prefix')}
          <strong>{t('gst.help3Strong')}</strong>
          {t('gst.help3Suffix')}
        </p>
      </PageHelp>

      {/* Work list first: a hole in the classification makes every number below
          incomplete, so it must not sit under the table where it can be missed. */}
      {!!coverage?.unclassified_count && (
        <Card className="border-amber-500/50 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              {t('gst.unclassified', { count: coverage.unclassified_count })}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            <p className="text-muted-foreground">{t('gst.unclassifiedHint')}</p>
            <p>{coverage.unclassified.map(p => p.name).join(', ')}</p>
          </CardContent>
        </Card>
      )}

      {!!coverage?.rate_mismatch_count && (
        <Card className="border-amber-500/50 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              {t('gst.mismatch', { count: coverage.rate_mismatch_count })}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <p className="text-muted-foreground">
              {t('gst.mismatchHint', { date: coverage.rates_as_of })}
            </p>
            <ul className="space-y-1">
              {coverage.rate_mismatch.map(p => (
                <li key={p.id}>
                  <strong>{p.name}</strong>
                  {t('gst.mismatchLine', {
                    charged: p.tax_rate, code: p.hsn_code,
                    description: p.description, expected: p.expected_rate,
                  })}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('gst.period')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3 flex-wrap">
            <div>
              <Label htmlFor="from">{t('gst.from')}</Label>
              <Input id="from" type="date" value={from}
                     onChange={e => setFrom(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="to">{t('gst.to')}</Label>
              <Input id="to" type="date" value={to}
                     onChange={e => setTo(e.target.value)} />
            </div>
            <Button variant="outline" onClick={() => setRange({ from, to })}>
              {t('gst.show')}
            </Button>
            {summary && (
              <p className="text-sm text-muted-foreground pb-2">
                {t('gst.orderCount', { count: summary.order_count })}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="summary">
        <TabsList className="flex-wrap h-auto">
          <TabsTrigger value="summary">{t('gst.tabSummary', { defaultValue: 'Summary' })}</TabsTrigger>
          <TabsTrigger value="hsn">{t('gst.tabHsn', { defaultValue: 'HSN' })}</TabsTrigger>
          <TabsTrigger value="b2c">{t('gst.tabB2c', { defaultValue: 'State-wise (B2C)' })}</TabsTrigger>
          <TabsTrigger value="docs">{t('gst.tabDocs', { defaultValue: 'Documents' })}</TabsTrigger>
          <TabsTrigger value="registers">{t('gst.tabRegisters', { defaultValue: 'Registers' })}</TabsTrigger>
        </TabsList>

        <TabsContent value="summary">
          <Card>
            <CardContent className="pt-6 space-y-4">
              <div className="flex justify-end">
                {dlBtn(t('gst.downloadCsv'), 'summary', () => exportGstSummaryCsv(range.from, range.to))}
              </div>
              {!!gst?.fallback_place_of_supply.length && (
                <Card className="border-amber-500/50 bg-amber-500/5">
                  <CardContent className="pt-4 text-sm">
                    <p className="font-medium flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-600" />
                      {t('gst.fallbackTitle', { defaultValue: 'Some invoices used a fallback state' })}
                    </p>
                    <p className="text-muted-foreground">
                      {t('gst.fallbackBody', { defaultValue: 'State could not be read from the address; billed as Madhya Pradesh.' })}
                    </p>
                    <p>{gst.fallback_place_of_supply.map(f => f.number).join(', ')}</p>
                  </CardContent>
                </Card>
              )}
              {gstLoading ? (
                <TableSkeleton />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead />
                      <TableHead className="text-right">{t('gst.colTaxable')}</TableHead>
                      <TableHead className="text-right">CGST</TableHead>
                      <TableHead className="text-right">SGST</TableHead>
                      <TableHead className="text-right">IGST</TableHead>
                      <TableHead className="text-right">{t('gst.colGst')}</TableHead>
                      <TableHead className="text-right">{t('common.total')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {summaryRows.map(row => (
                      <TableRow key={row.label}>
                        <TableCell className="font-medium">{row.label}</TableCell>
                        <TableCell className="text-right">{money(row.block.taxable_value)}</TableCell>
                        <TableCell className="text-right">{money(row.block.cgst)}</TableCell>
                        <TableCell className="text-right">{money(row.block.sgst)}</TableCell>
                        <TableCell className="text-right">{money(row.block.igst)}</TableCell>
                        <TableCell className="text-right">{money(row.block.tax)}</TableCell>
                        <TableCell className="text-right">{money(row.block.total)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="hsn">
          <Card>
            <CardContent className="pt-6">
              <div className="flex justify-end mb-4">
                {dlBtn(t('gst.downloadCsv'), 'hsn2', () => exportHsnSummaryCsv(range.from, range.to))}
              </div>
              {isLoading ? (
                <TableSkeleton />
              ) : !summary?.rows.length ? (
                <p className="text-sm text-muted-foreground">{t('gst.noSupplies')}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('gst.colHsn')}</TableHead>
                      <TableHead>{t('common.description')}</TableHead>
                      <TableHead className="text-center">{t('gst.colUqc')}</TableHead>
                      <TableHead className="text-right">{t('gst.colQty')}</TableHead>
                      <TableHead className="text-right">{t('gst.colRate')}</TableHead>
                      <TableHead className="text-right">{t('gst.colTaxable')}</TableHead>
                      <TableHead className="text-right">{t('gst.colGst')}</TableHead>
                      <TableHead className="text-right">{t('common.total')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {summary.rows.map(row => (
                      <TableRow
                        key={`${row.hsn_code}-${row.rate}`}
                        className={row.is_unclassified ? 'bg-amber-500/10' : undefined}
                      >
                        <TableCell className="font-mono">
                          {row.hsn_code || t('gst.notClassified')}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {row.description}
                        </TableCell>
                        <TableCell className="text-center">{row.uqc}</TableCell>
                        <TableCell className="text-right">
                          {row.is_service ? '—' : row.quantity}
                        </TableCell>
                        <TableCell className="text-right">{row.rate}%</TableCell>
                        <TableCell className="text-right">
                          {money(row.taxable_value)}
                        </TableCell>
                        <TableCell className="text-right">
                          {money(row.tax_amount)}
                        </TableCell>
                        <TableCell className="text-right">
                          {money(row.total_value)}
                        </TableCell>
                      </TableRow>
                    ))}
                    <TableRow className="font-semibold">
                      <TableCell colSpan={3}>{t('common.total')}</TableCell>
                      <TableCell className="text-right">
                        {summary.totals.quantity}
                      </TableCell>
                      <TableCell />
                      <TableCell className="text-right">
                        {money(summary.totals.taxable_value)}
                      </TableCell>
                      <TableCell className="text-right">
                        {money(summary.totals.tax_amount)}
                      </TableCell>
                      <TableCell className="text-right">
                        {money(summary.totals.total_value)}
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              )}

              {!!summary?.refunded_in_period.amount && (
                <p className="text-xs text-muted-foreground mt-4">
                  {t('gst.refundsNotePrefix')}
                  <strong>{t('gst.refundsNoteNot')}</strong>
                  {t('gst.refundsNoteSuffix', {
                    amount: money(summary.refunded_in_period.amount),
                    tax: money(summary.refunded_in_period.tax),
                  })}
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="b2c">
          <Card>
            <CardContent className="pt-6">
              <div className="flex justify-end mb-4">
                {dlBtn(t('gst.downloadCsv'), 'b2c', () => exportGstB2cCsv(range.from, range.to))}
              </div>
              {b2cLoading ? (
                <TableSkeleton />
              ) : !b2c?.rows.length ? (
                <p className="text-sm text-muted-foreground">{t('gst.noSupplies')}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('gst.colState', { defaultValue: 'State' })}</TableHead>
                      <TableHead className="text-right">{t('gst.colRate')}</TableHead>
                      <TableHead className="text-right">{t('gst.colNetTaxable', { defaultValue: 'Net taxable' })}</TableHead>
                      <TableHead className="text-right">CGST</TableHead>
                      <TableHead className="text-right">SGST</TableHead>
                      <TableHead className="text-right">IGST</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {b2c.rows.map((row, i) => (
                      <TableRow key={`${row.state_code}-${row.rate}-${i}`}>
                        <TableCell>{row.state_name} ({row.state_code})</TableCell>
                        <TableCell className="text-right">{row.rate_label}</TableCell>
                        <TableCell className="text-right">{money(row.net_taxable_value)}</TableCell>
                        <TableCell className="text-right">{money(row.net_cgst)}</TableCell>
                        <TableCell className="text-right">{money(row.net_sgst)}</TableCell>
                        <TableCell className="text-right">{money(row.net_igst)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="docs">
          <Card>
            <CardContent className="pt-6">
              <div className="flex justify-end mb-4">
                {dlBtn(t('gst.downloadCsv'), 'docs', () => exportGstDocumentsCsv(range.from, range.to))}
              </div>
              {docsLoading ? (
                <TableSkeleton />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('gst.colType', { defaultValue: 'Type' })}</TableHead>
                      <TableHead>{t('gst.colSeries', { defaultValue: 'Series' })}</TableHead>
                      <TableHead>{t('gst.colFrom', { defaultValue: 'From' })}</TableHead>
                      <TableHead>{t('gst.colTo', { defaultValue: 'To' })}</TableHead>
                      <TableHead className="text-right">{t('gst.colCount', { defaultValue: 'Count' })}</TableHead>
                      <TableHead className="text-right">{t('gst.colGap', { defaultValue: 'Gap' })}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...(docs?.invoices || []).map(r => ({ ...r, type: 'Invoices' })),
                      ...(docs?.credit_notes || []).map(r => ({ ...r, type: 'Credit notes' }))].map(row => (
                      <TableRow key={`${row.type}-${row.series}`}>
                        <TableCell>{row.type}</TableCell>
                        <TableCell className="font-mono">{row.series}</TableCell>
                        <TableCell className="font-mono">{row.from_number}</TableCell>
                        <TableCell className="font-mono">{row.to_number}</TableCell>
                        <TableCell className="text-right">{row.count}</TableCell>
                        <TableCell className="text-right">
                          {row.gap > 0
                            ? <Badge variant="destructive">{row.gap}</Badge>
                            : row.gap}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="registers">
          <Card>
            <CardContent className="pt-6 flex gap-3 flex-wrap">
              <Button onClick={() => download('inv-reg', () => exportInvoiceRegisterCsv(range.from, range.to))}
                      disabled={downloading === 'inv-reg'}>
                {downloading === 'inv-reg'
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <Download className="mr-2 h-4 w-4" />}
                {t('gst.invoiceRegisterCsv', { defaultValue: 'Invoice register CSV' })}
              </Button>
              <Button onClick={() => download('cn-reg', () => exportCreditNoteRegisterCsv(range.from, range.to))}
                      disabled={downloading === 'cn-reg'}>
                {downloading === 'cn-reg'
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <Download className="mr-2 h-4 w-4" />}
                {t('gst.creditNoteRegisterCsv', { defaultValue: 'Credit note register CSV' })}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default GstReport;
