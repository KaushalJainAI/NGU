import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getExpenses, createExpense, updateExpense, deleteExpense,
  getBooksSummary, exportExpensesCsv, Expense,
} from '@/api/accounts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { Download, Loader2, AlertTriangle } from 'lucide-react';
import { TableSkeleton } from '@/components/TableSkeleton';
import { useTranslation } from 'react-i18next';

const thisMonth = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const start = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`;
  const end = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate())}`;
  return { from: start, to: end, month: `${now.getFullYear()}-${pad(now.getMonth() + 1)}` };
};

const isoToday = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

// Sign before the symbol: a loss reads "−₹1,682.00", not "₹-1,682.00".
const money = (n: string | number) => {
  const value = Number(n || 0);
  const abs = Math.abs(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${value < 0 ? '−' : ''}₹${abs}`;
};

/** One label/amount row in a breakdown card; `bold` marks the closing line. */
const Line = ({ label, value, bold }: { label: string; value: string; bold?: boolean }) => (
  <div className={`flex justify-between gap-3 ${bold ? 'border-t pt-1 font-semibold' : ''}`}>
    <span className={bold ? '' : 'text-muted-foreground'}>{label}</span>
    <span>{value}</span>
  </div>
);

const CATEGORIES = ['raw_material', 'packaging', 'marketing', 'rent_utilities', 'salary', 'other'];
const MODES = ['cash', 'bank', 'upi', 'card'];

const emptyForm = { date: '', category: 'other', vendor: '', description: '', amount: '', gst_amount: '', itc_eligible: false, bill_number: '', payment_mode: 'bank' };

const Accounts = () => {
  const { t } = useTranslation();
  const d = thisMonth();
  const [month, setMonth] = useState(d.month);
  const [range, setRange] = useState({ from: d.from, to: d.to });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Expense | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  const applyMonth = (m: string) => {
    setMonth(m);
    const [y, mo] = m.split('-').map(Number);
    if (!y || !mo) return;
    const pad = (n: number) => String(n).padStart(2, '0');
    setRange({
      from: `${y}-${pad(mo)}-01`,
      to: `${y}-${pad(mo)}-${new Date(y, mo, 0).getDate()}`,
    });
  };

  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ['books-summary', range.from, range.to],
    queryFn: () => getBooksSummary(range.from, range.to),
  });
  const { data: expenses, isLoading: expensesLoading, refetch: refetchExpenses } = useQuery({
    queryKey: ['expenses', range.from, range.to],
    queryFn: () => getExpenses({ from: range.from, to: range.to }),
  });

  const openAdd = () => {
    setEditing(null);
    // Today when the selected month is the current one; otherwise the 1st of
    // the month being looked at, so a back-dated entry lands in that month.
    const today = isoToday();
    setForm({ ...emptyForm, date: today >= range.from && today <= range.to ? today : range.from });
    setDialogOpen(true);
  };
  const openEdit = (e: Expense) => {
    setEditing(e);
    setForm({
      date: e.date, category: e.category, vendor: e.vendor || '', description: e.description || '',
      amount: String(e.amount), gst_amount: String(e.gst_amount), itc_eligible: e.itc_eligible,
      bill_number: e.bill_number || '', payment_mode: e.payment_mode,
    });
    setDialogOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...form,
        amount: form.amount,
        gst_amount: form.gst_amount || '0',
      };
      if (editing) await updateExpense(editing.id, payload);
      else await createExpense(payload);
      setDialogOpen(false);
      refetchExpenses();
      refetchSummary();
    } catch {
      toast({ title: t('accounts.saveFailed', { defaultValue: 'Could not save the expense.' }), variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (e: Expense) => {
    if (!confirm(t('accounts.deleteConfirm', { defaultValue: 'Delete this expense?' }))) return;
    await deleteExpense(e.id);
    refetchExpenses();
    refetchSummary();
  };

  const gw = summary?.costs.gateway_fee_coverage;
  const cw = summary?.costs.courier_cost_coverage;
  const moneyReceived = Number(summary?.cash.online_received || 0) + Number(summary?.cash.cod_received || 0);
  const costsTotal = Number(summary?.costs.gateway_fees_ex_gst || 0)
    + Number(summary?.costs.courier_cost || 0) + Number(summary?.costs.expenses_total || 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t('accounts.title', { defaultValue: 'Accounts' })}</h1>
        <p className="text-sm text-muted-foreground">
          {t('accounts.subtitle', { defaultValue: 'Sales, cash, costs and an estimated profit — no ledgers.' })}
        </p>
      </div>

      <Card>
        <CardContent className="pt-4 flex items-end gap-3 flex-wrap">
          <div>
            <Label htmlFor="month">{t('accounts.month', { defaultValue: 'Month' })}</Label>
            <Input id="month" type="month" value={month} onChange={e => applyMonth(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      {summaryLoading ? (
        <TableSkeleton />
      ) : summary ? (
        <>
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.netSales', { defaultValue: 'Net sales' })}</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold">{money(summary.sales.net_sales_ex_gst)}</div></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.moneyReceived', { defaultValue: 'Money received' })}</CardTitle></CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{money(moneyReceived)}</div>
                <p className="text-xs text-muted-foreground">
                  {t('accounts.moneySplit', { defaultValue: 'Online {{o}} · COD {{c}}', o: money(summary.cash.online_received), c: money(summary.cash.cod_received) })}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.costs', { defaultValue: 'Costs' })}</CardTitle></CardHeader>
              <CardContent><div className="text-2xl font-bold">{money(costsTotal)}</div></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.profit', { defaultValue: 'Estimated profit' })}</CardTitle></CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{money(summary.profit.estimated_profit)}</div>
                <p className="text-[11px] text-muted-foreground mt-1">
                  {t('accounts.estimateNote', { defaultValue: 'Estimate from the entries in this panel. Confirm with your accountant before filing or paying.' })}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.gstToPay', { defaultValue: 'Estimated GST to pay' })}</CardTitle></CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{money(summary.gst.estimated_net_gst)}</div>
                <p className="text-[11px] text-muted-foreground mt-1">
                  {t('accounts.estimateNote', { defaultValue: 'Estimate from the entries in this panel. Confirm with your accountant before filing or paying.' })}
                </p>
              </CardContent>
            </Card>
          </div>

          {gw && gw.recorded < gw.total && (
            <Card className="border-amber-500/50 bg-amber-500/5">
              <CardContent className="pt-4 text-sm flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                {t('accounts.gatewayCoverage', { defaultValue: 'Gateway fee recorded on {{a}} of {{b}} online payments.', a: gw.recorded, b: gw.total })}
              </CardContent>
            </Card>
          )}
          {cw && cw.recorded < cw.total && (
            <Card className="border-amber-500/50 bg-amber-500/5">
              <CardContent className="pt-4 text-sm flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                {t('accounts.courierCoverage', { defaultValue: 'Courier cost recorded on {{a}} of {{b}} dispatched orders.', a: cw.recorded, b: cw.total })}
              </CardContent>
            </Card>
          )}

          {/* The working behind the totals above, so each figure can be checked. */}
          <div className="grid gap-4 grid-cols-1 lg:grid-cols-3">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.costsBreakdown')}</CardTitle></CardHeader>
              <CardContent className="space-y-1 text-sm">
                <Line label={t('accounts.gatewayFees')} value={money(summary.costs.gateway_fees_ex_gst)} />
                <Line label={t('accounts.courierCost')} value={money(summary.costs.courier_cost)} />
                {summary.costs.expenses_by_category.map(c => (
                  <Line key={c.category}
                    label={t(`accounts.category.${c.category}`, { defaultValue: c.label })}
                    value={money(c.cost)} />
                ))}
                <Line bold label={t('common.total')} value={money(costsTotal)} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.cash')}</CardTitle></CardHeader>
              <CardContent className="space-y-1 text-sm">
                <Line label={t('accounts.onlineReceived')} value={money(summary.cash.online_received)} />
                <Line label={t('accounts.codReceived')} value={money(summary.cash.cod_received)} />
                <Line label={t('accounts.refundsPaid')} value={`−${money(summary.cash.refunds_paid)}`} />
                <Line bold label={t('accounts.codOutstanding')} value={money(summary.cash.cod_outstanding_now)} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{t('accounts.gstWorking')}</CardTitle></CardHeader>
              <CardContent className="space-y-1 text-sm">
                <Line label={t('accounts.gstOnInvoices')} value={money(summary.gst.output_tax)} />
                <Line label={t('accounts.gstCreditNotes')} value={`−${money(summary.gst.credit_note_tax)}`} />
                <Line label={t('accounts.gstOnExpenses')} value={`−${money(summary.gst.input_tax_expenses)}`} />
                <Line label={t('accounts.gstOnGateway')} value={`−${money(summary.gst.input_tax_gateway)}`} />
                <Line bold label={t('accounts.gstToPay')} value={money(summary.gst.estimated_net_gst)} />
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t('accounts.expenses', { defaultValue: 'Expenses' })}</CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => exportExpensesCsv(range.from, range.to)}>
              <Download className="mr-2 h-4 w-4" />
              {t('gst.downloadCsv')}
            </Button>
            <Button size="sm" onClick={openAdd}>{t('common.add')}</Button>
          </div>
        </CardHeader>
        <CardContent>
          {expensesLoading ? (
            <TableSkeleton />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('common.date')}</TableHead>
                  <TableHead>{t('common.type')}</TableHead>
                  <TableHead>{t('common.description')}</TableHead>
                  <TableHead className="text-right">{t('common.amount')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(expenses || []).map(e => (
                  <TableRow key={e.id}>
                    <TableCell>{e.date}</TableCell>
                    <TableCell>{t(`accounts.category.${e.category}`, { defaultValue: e.category })}</TableCell>
                    <TableCell className="text-muted-foreground">{e.description || e.vendor}</TableCell>
                    <TableCell className="text-right">{money(e.amount)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => openEdit(e)}>{t('common.edit')}</Button>
                      <Button variant="ghost" size="sm" className="text-destructive" onClick={() => remove(e)}>{t('common.delete')}</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t('common.edit') : t('common.add')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label>{t('common.date')}</Label>
              <Input type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} />
            </div>
            <div>
              <Label>{t('common.type')}</Label>
              <Select value={form.category} onValueChange={v => setForm({ ...form, category: v })}>
                <SelectTrigger><span>{t(`accounts.category.${form.category}`)}</span></SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map(c => <SelectItem key={c} value={c}>{t(`accounts.category.${c}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t('accounts.vendor')}</Label>
              <Input value={form.vendor} onChange={e => setForm({ ...form, vendor: e.target.value })} />
            </div>
            <div>
              <Label>{t('common.description')}</Label>
              <Input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('common.amount')}</Label>
                <Input type="number" step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div>
                <Label>{t('accounts.gstInAmount')}</Label>
                <Input type="number" step="0.01" value={form.gst_amount} onChange={e => setForm({ ...form, gst_amount: e.target.value })} />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.itc_eligible} onChange={e => setForm({ ...form, itc_eligible: e.target.checked })} />
              {t('accounts.itc', { defaultValue: 'GST can be claimed' })}
            </label>
            <div>
              <Label>{t('accounts.billNumber')}</Label>
              <Input value={form.bill_number} onChange={e => setForm({ ...form, bill_number: e.target.value })} />
            </div>
            <div>
              <Label>{t('accounts.paymentMode')}</Label>
              <Select value={form.payment_mode} onValueChange={v => setForm({ ...form, payment_mode: v })}>
                <SelectTrigger><span>{t(`accounts.mode.${form.payment_mode}`)}</span></SelectTrigger>
                <SelectContent>
                  {MODES.map(m => <SelectItem key={m} value={m}>{t(`accounts.mode.${m}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={save} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Accounts;
