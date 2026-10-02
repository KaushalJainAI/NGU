import { useMemo, useState } from 'react';
import { useAdminData, useInvalidate } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import {
  getBulkProducts, applyBulkChanges, importProductsCsv, exportProductsCsv,
  BulkProductRow, BulkVariant, BulkChange, ImportPreview,
} from '@/api/bulk';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { Search, Save, Download, Upload, CheckCircle2, AlertTriangle } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

type Field = 'price' | 'discount_price' | 'stock';

/** Pending edits, keyed by the thing being edited: `p:<productId>` for a
 *  product's own price/stock, or `v:<variantId>` for one packaging size. */
type Edits = Record<string, {
  productId: number;
  variantId?: number;
  price?: string;
  discount_price?: string;
  stock?: string;
}>;

/** The size the grid is currently editing for a product, or `null` for the
 *  product's own (legacy, size-less) fields. Defaults to the default size. */
const defaultVariant = (row: BulkProductRow): BulkVariant | null =>
  row.variants?.find(v => v.is_default) ?? row.variants?.[0] ?? null;

const BulkEdit = () => {
  const { t } = useTranslation();
  const {
    data: rows = [], isInitialLoading, refreshing, refetch: fetchRows,
  } = useAdminData(['bulk-products'], () => getBulkProducts().then(r => r.data));
  const invalidate = useInvalidate();
  const [edits, setEdits] = useState<Edits>({});
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const { toast } = useToast();

  // Import wizard state
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(r => r.name.toLowerCase().includes(q) || r.category_name.toLowerCase().includes(q));
  }, [rows, search]);

  // Which size each product row is editing, by variant id. Unset rows fall back
  // to the product's default size. There is deliberately no "edit the product
  // itself" option: price and stock live on the size, and the product's own
  // columns are a read-only mirror of the default size — writing them looks
  // like it worked and is then overwritten by the next size save.
  const [sizeChoice, setSizeChoice] = useState<Record<number, string>>({});

  const activeVariant = (row: BulkProductRow): BulkVariant | null => {
    const choice = sizeChoice[row.id];
    if (choice === undefined) return defaultVariant(row);
    return row.variants?.find(v => String(v.id) === choice) ?? defaultVariant(row);
  };

  // The row's edit key + the values the inputs compare against.
  const target = (row: BulkProductRow) => {
    const variant = activeVariant(row);
    const source = variant ?? row;
    return {
      key: variant ? `v:${variant.id}` : `p:${row.id}`,
      variantId: variant?.id,
      original: (field: Field) =>
        String(field === 'stock' ? source.stock : source[field] ?? ''),
    };
  };

  const setEdit = (row: BulkProductRow, field: Field, value: string) => {
    const { key, variantId, original } = target(row);
    setEdits(prev => {
      const next = {
        ...prev,
        [key]: { ...prev[key], productId: row.id, variantId, [field]: value },
      };
      // Drop the edit if it matches the original again (no longer dirty).
      if (value === original(field)) {
        delete next[key][field];
        const { productId: _p, variantId: _v, ...fields } = next[key];
        if (Object.keys(fields).length === 0) delete next[key];
      }
      return next;
    });
  };

  const isDirty = (row: BulkProductRow, field: Field) =>
    edits[target(row).key]?.[field] !== undefined;

  const cellValue = (row: BulkProductRow, field: Field) => {
    const { key, original } = target(row);
    return edits[key]?.[field] ?? original(field);
  };

  // A plain-language description of every pending change, for the review step.
  const changeList = useMemo(() => {
    const list: { name: string; description: string }[] = [];
    for (const entry of Object.values(edits)) {
      const { productId, variantId, ...fields } = entry;
      const row = rows.find(r => r.id === productId);
      if (!row) continue;
      const variant = variantId ? row.variants?.find(v => v.id === variantId) : null;
      const before = variant ?? row;
      const parts: string[] = [];
      if (fields.price !== undefined) {
        parts.push(t('bulkEdit.change.price', { from: before.price || 0, to: fields.price }));
      }
      if (fields.discount_price !== undefined) {
        const money = (v?: string | number | null) =>
          v ? `₹${v}` : t('bulkEdit.none');
        parts.push(t('bulkEdit.change.discountPrice', {
          from: money(before.discount_price), to: money(fields.discount_price),
        }));
      }
      if (fields.stock !== undefined) {
        parts.push(t('bulkEdit.change.stock', { from: before.stock, to: fields.stock }));
      }
      if (parts.length) {
        list.push({
          name: variant ? `${row.name} (${variant.label})` : row.name,
          description: parts.join(', '),
        });
      }
    }
    return list;
  }, [edits, rows, t]);

  const applyEdits = async () => {
    const changes: BulkChange[] = Object.values(edits).map(({ productId, variantId, ...fields }) => ({
      id: productId,
      ...(variantId ? { variant_id: variantId } : {}),
      ...fields,
    }));
    if (changes.length === 0) return;
    setSaving(true);
    try {
      const res = await applyBulkChanges(changes);
      toast({
        title: t('bulkEdit.savedTitle'),
        description: t('bulkEdit.savedBody', { count: res.data.applied }),
      });
      setEdits({});
      setReviewOpen(false);
      // Prices/stock just changed — the Products page and dashboard low-stock
      // counts are now stale, so drop their caches too.
      invalidate(['bulk-products'], ['products'], ['dashboard']);
    } catch (error: unknown) {
      // The apply endpoint returns per-row errors on 400.
      const errs = (error as { response?: { data?: { errors?: { error: string }[] } } })?.response?.data?.errors;
      const msg = errs?.length ? errs.map(e => e.error).join(' ') : t('bulkEdit.saveFailed');
      toast({ title: t('bulkEdit.nothingSavedTitle'), description: msg, variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  // ---- Import wizard ----
  const openImport = () => { setPreview(null); setImportOpen(true); };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setImporting(true);
    try {
      const res = await importProductsCsv(file);
      setPreview(res.data);
    } catch (error: unknown) {
      const msg = (error as { response?: { data?: { error?: string } } })?.response?.data?.error
        || t('bulkEdit.readFailed');
      toast({ title: t('bulkEdit.importProblemTitle'), description: msg, variant: 'destructive' });
    } finally {
      setImporting(false);
    }
  };

  const applyImport = async () => {
    if (!preview) return;
    const changes: BulkChange[] = preview.rows
      .filter(r => r.id && !r.error && Object.keys(r.changes).length)
      .map(r => ({ id: r.id as number, ...r.changes }));
    if (changes.length === 0) return;
    setImporting(true);
    try {
      const res = await applyBulkChanges(changes);
      toast({
        title: t('bulkEdit.importDoneTitle'),
        description: t('bulkEdit.importDoneBody', { count: res.data.applied }),
      });
      setImportOpen(false);
      setPreview(null);
      invalidate(['bulk-products'], ['products'], ['dashboard']);
    } catch {
      toast({
        title: t('common.error'),
        description: t('bulkEdit.importApplyFailed'),
        variant: 'destructive',
      });
    } finally {
      setImporting(false);
    }
  };

  const dirtyCount = Object.keys(edits).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('bulkEdit.title')}</h1>
          <p className="text-muted-foreground">{t('bulkEdit.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => exportProductsCsv()}>
            <Download className="mr-2 h-4 w-4" /> {t('bulkEdit.exportButton')}
          </Button>
          <Button variant="outline" onClick={openImport}>
            <Upload className="mr-2 h-4 w-4" /> {t('bulkEdit.importButton')}
          </Button>
        </div>
      </div>

      <PageHelp>{t('bulkEdit.pageHelp')}</PageHelp>

      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="relative max-w-sm w-full">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input placeholder={t('bulkEdit.searchPlaceholder')} className="pl-8"
                value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Button disabled={dirtyCount === 0} onClick={() => setReviewOpen(true)}>
              <Save className="mr-2 h-4 w-4" />
              {t('bulkEdit.reviewAndSave')}{dirtyCount ? ` (${dirtyCount})` : ''}
            </Button>
          </div>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={8} columns={6} /> : (
          <Table className="min-w-[820px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('bulkEdit.colProduct')}</TableHead>
                <TableHead>{t('bulkEdit.colCategory')}</TableHead>
                <TableHead className="w-40">{t('bulkEdit.colSize')}</TableHead>
                <TableHead className="w-32">{t('bulkEdit.colPrice')}</TableHead>
                <TableHead className="w-32">{t('bulkEdit.colDiscountPrice')}</TableHead>
                <TableHead className="w-28">{t('bulkEdit.colStock')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map(row => {
                const variant = activeVariant(row);
                const dirtyClass = 'border-amber-500 bg-amber-50 dark:bg-amber-950/30';
                return (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell className="text-muted-foreground">{row.category_name || '—'}</TableCell>
                  <TableCell>
                    {row.variants?.length ? (
                      <Select
                        value={variant ? String(variant.id) : 'base'}
                        onValueChange={(v) => setSizeChoice(prev => ({ ...prev, [row.id]: v }))}
                      >
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {row.variants.map(v => (
                            <SelectItem key={v.id} value={String(v.id)}>
                              {v.label}{v.is_default ? t('bulkEdit.defaultSuffix') : ''}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" inputMode="decimal"
                      className={isDirty(row, 'price') ? dirtyClass : ''}
                      value={cellValue(row, 'price')}
                      onChange={(e) => setEdit(row, 'price', e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" inputMode="decimal" placeholder={t('bulkEdit.none')}
                      className={isDirty(row, 'discount_price') ? dirtyClass : ''}
                      value={cellValue(row, 'discount_price')}
                      onChange={(e) => setEdit(row, 'discount_price', e.target.value)}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number" inputMode="numeric"
                      className={isDirty(row, 'stock') ? dirtyClass : ''}
                      value={cellValue(row, 'stock')}
                      onChange={(e) => setEdit(row, 'stock', e.target.value)}
                    />
                  </TableCell>
                </TableRow>
                );
              })}
            </TableBody>
          </Table>
          )}
        </CardContent>
      </Card>

      {/* Review step */}
      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('bulkEdit.reviewTitle')}</DialogTitle>
            <DialogDescription>
              {t('bulkEdit.reviewDescription', { count: changeList.length })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {changeList.map((c, i) => (
              <div key={i} className="rounded border p-2 text-sm">
                <span className="font-medium">{c.name}</span>: {c.description}
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReviewOpen(false)}>
              {t('bulkEdit.keepEditing')}
            </Button>
            <Button onClick={applyEdits} disabled={saving}>
              {saving ? t('common.saving') : t('bulkEdit.saveChanges', { count: changeList.length })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import wizard */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('bulkEdit.importTitle')}</DialogTitle>
            <DialogDescription>
              {/* The column names are literal CSV headers the backend parses —
                  they stay in English in every language or the import breaks. */}
              {t('bulkEdit.importTitlePrefix')}<b>name</b>{' '}
              {t('bulkEdit.importColumnsHint')} <b>price</b>, <b>discount_price</b>, <b>stock</b>.{' '}
              {t('bulkEdit.importTip')}
            </DialogDescription>
          </DialogHeader>

          {!preview ? (
            <div className="space-y-3">
              <Input type="file" accept=".csv,text/csv"
                onChange={(e) => handleFile(e.target.files?.[0])} disabled={importing} />
              {importing && (
                <p className="text-sm text-muted-foreground">{t('bulkEdit.readingFile')}</p>
              )}
              <p className="text-xs text-muted-foreground">{t('bulkEdit.excelHint')}</p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex gap-4 text-sm">
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 className="h-4 w-4" /> {t('bulkEdit.ready', { count: preview.ok_count })}
                </span>
                {preview.error_count > 0 && (
                  <span className="flex items-center gap-1 text-amber-600">
                    <AlertTriangle className="h-4 w-4" /> {t('bulkEdit.withProblems', { count: preview.error_count })}
                  </span>
                )}
              </div>
              <div className="space-y-1 max-h-[40vh] overflow-y-auto">
                {preview.rows.map((r, i) => (
                  <div key={i} className={`rounded border p-2 text-sm ${r.error ? 'border-amber-300 bg-amber-50 dark:bg-amber-950/20' : ''}`}>
                    <span className="font-medium">{r.name}</span>
                    {r.size && <span className="text-muted-foreground"> ({r.size})</span>}
                    {r.error
                      ? <span className="text-amber-700"> — {r.error}</span>
                      // variant_id rides along in `changes` so the row can be
                      // applied as-is; it's plumbing, not a field the admin edited.
                      : <span className="text-muted-foreground"> — {Object.entries(r.changes)
                          .filter(([k]) => k !== 'variant_id')
                          .map(([k, v]) => `${t(`bulkEdit.field.${k}`, { defaultValue: k.replace('_', ' ') })}: ${v || t('bulkEdit.none')}`)
                          .join(', ')}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportOpen(false); setPreview(null); }}>
              {t('common.cancel')}
            </Button>
            {preview && (
              <Button onClick={applyImport} disabled={importing || preview.ok_count === 0}>
                {importing
                  ? t('bulkEdit.applying')
                  : t('bulkEdit.applyChanges', { count: preview.ok_count })}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default BulkEdit;
