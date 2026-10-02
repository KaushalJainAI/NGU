import { useMemo, useState } from 'react';
import { useAdminData, useInvalidate } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import {
  getBulkProducts, applyBulkChanges, importProductsCsv, exportProductsCsv,
  BulkProductRow, BulkVariant, BulkChange, BulkApplyError, ImportPreview,
} from '@/api/bulk';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useToast } from '@/hooks/use-toast';
import { Search, Save, Download, Upload, CheckCircle2, AlertTriangle, Undo2 } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

type Field = 'price' | 'discount_price' | 'stock';
const FIELDS: Field[] = ['price', 'discount_price', 'stock'];

/** Pending edits, keyed by the SIZE being edited. Price and stock live on a
 *  size, never on the product itself, so there is no product-level key. */
type Edits = Record<number, {
  productId: number;
  price?: string;
  discount_price?: string;
  stock?: string;
}>;

/** One grid line: a single size of a product. */
type Line = {
  product: BulkProductRow;
  /** `null` only for a product with no active size — shown, but not editable. */
  variant: BulkVariant | null;
  /** First line of its product, so the name is printed once per group. */
  first: boolean;
  sizeCount: number;
};

const original = (variant: BulkVariant, field: Field) =>
  String(field === 'stock' ? variant.stock : variant[field] ?? '');

const BulkEdit = () => {
  const { t } = useTranslation();
  const {
    data: rows = [], isInitialLoading, refreshing,
  } = useAdminData(['bulk-products'], () => getBulkProducts().then(r => r.data));
  const invalidate = useInvalidate();
  const [edits, setEdits] = useState<Edits>({});
  const [search, setSearch] = useState('');
  const [changedOnly, setChangedOnly] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  /** What the server refused on the last save, by size id. */
  const [serverErrors, setServerErrors] = useState<Record<number, string>>({});
  const { toast } = useToast();

  // Import wizard state
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  // Every size on its own line. The old grid showed one line per product with a
  // size dropdown, which hid all but one size at a time: an edit to the 500g
  // pack disappeared from view the moment the dropdown moved to 1kg.
  const lines = useMemo(() => {
    const q = search.trim().toLowerCase();
    const out: Line[] = [];
    for (const product of rows) {
      const variants = product.variants ?? [];
      const productMatches = !q
        || product.name.toLowerCase().includes(q)
        || product.category_name.toLowerCase().includes(q);
      let shown = variants.filter(v =>
        productMatches || v.label.toLowerCase().includes(q));
      if (changedOnly) shown = shown.filter(v => edits[v.id]);
      if (variants.length === 0) {
        if (productMatches && !changedOnly) {
          out.push({ product, variant: null, first: true, sizeCount: 0 });
        }
        continue;
      }
      shown.forEach((variant, index) => out.push({
        product, variant, first: index === 0, sizeCount: variants.length,
      }));
    }
    return out;
  }, [rows, search, changedOnly, edits]);

  const value = (variant: BulkVariant, field: Field) =>
    edits[variant.id]?.[field] ?? original(variant, field);

  const isDirty = (variant: BulkVariant, field: Field) =>
    edits[variant.id]?.[field] !== undefined;

  const setEdit = (product: BulkProductRow, variant: BulkVariant, field: Field, next: string) => {
    setServerErrors(prev => {
      if (!(variant.id in prev)) return prev;
      const { [variant.id]: _gone, ...rest } = prev;
      return rest;
    });
    setEdits(prev => {
      const entry = { ...prev[variant.id], productId: product.id, [field]: next };
      // Typing the original value back means "not changed" again.
      if (next === original(variant, field)) delete entry[field];
      const copy = { ...prev };
      if (FIELDS.some(f => entry[f] !== undefined)) copy[variant.id] = entry;
      else delete copy[variant.id];
      return copy;
    });
  };

  const resetLine = (variant: BulkVariant) =>
    setEdits(prev => {
      const { [variant.id]: _gone, ...rest } = prev;
      return rest;
    });

  /** Why this line can't be saved as typed, or null. Mirrors the server's
   *  rules so the problem shows beside the box instead of after Save. */
  const problem = (variant: BulkVariant): string | null => {
    if (!edits[variant.id]) return null;
    const price = value(variant, 'price').trim();
    const discount = value(variant, 'discount_price').trim();
    const stock = value(variant, 'stock').trim();
    if (price === '' || !(Number(price) > 0)) return t('bulkEdit.errPrice');
    if (discount !== '' && (Number.isNaN(Number(discount)) || Number(discount) < 0)) {
      return t('bulkEdit.errDiscount');
    }
    if (Number(discount) > 0 && Number(discount) >= Number(price)) {
      return t('bulkEdit.errDiscountTooHigh');
    }
    if (stock === '' || !Number.isInteger(Number(stock)) || Number(stock) < 0) {
      return t('bulkEdit.errStock');
    }
    return null;
  };

  const variantById = useMemo(() => {
    const map = new Map<number, { product: BulkProductRow; variant: BulkVariant }>();
    for (const product of rows) {
      for (const variant of product.variants ?? []) map.set(variant.id, { product, variant });
    }
    return map;
  }, [rows]);

  const problemCount = Object.keys(edits).filter(id => {
    const found = variantById.get(Number(id));
    return found ? problem(found.variant) !== null : false;
  }).length;

  // A plain-language description of every pending change, for the review step.
  const changeList = useMemo(() => {
    const list: { name: string; description: string }[] = [];
    for (const [id, fields] of Object.entries(edits)) {
      const found = variantById.get(Number(id));
      if (!found) continue;
      const { product, variant } = found;
      const parts: string[] = [];
      if (fields.price !== undefined) {
        parts.push(t('bulkEdit.change.price', { from: variant.price || 0, to: fields.price }));
      }
      if (fields.discount_price !== undefined) {
        const money = (v?: string | number | null) =>
          v && Number(v) > 0 ? `₹${v}` : t('bulkEdit.none');
        parts.push(t('bulkEdit.change.discountPrice', {
          from: money(variant.discount_price), to: money(fields.discount_price),
        }));
      }
      if (fields.stock !== undefined) {
        parts.push(t('bulkEdit.change.stock', { from: variant.stock, to: fields.stock }));
      }
      if (parts.length) {
        list.push({ name: `${product.name} (${variant.label})`, description: parts.join(', ') });
      }
    }
    return list.sort((a, b) => a.name.localeCompare(b.name));
  }, [edits, variantById, t]);

  const applyEdits = async () => {
    const changes: BulkChange[] = Object.entries(edits).map(([id, { productId, ...fields }]) => ({
      id: productId,
      variant_id: Number(id),
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
      setServerErrors({});
      setReviewOpen(false);
      // Prices/stock just changed — the Products page and dashboard low-stock
      // counts are now stale, so drop their caches too.
      invalidate(['bulk-products'], ['products'], ['combos'], ['dashboard']);
    } catch (error: unknown) {
      // The apply endpoint returns per-row errors on 400. Nothing was saved, so
      // the edits stay in the grid; mark the rows it refused.
      const errs = (error as { response?: { data?: { errors?: BulkApplyError[] } } })
        ?.response?.data?.errors ?? [];
      const byVariant: Record<number, string> = {};
      for (const e of errs) if (e.variant_id) byVariant[e.variant_id] = e.error;
      setServerErrors(byVariant);
      setReviewOpen(false);
      toast({
        title: t('bulkEdit.nothingSavedTitle'),
        description: errs.length
          ? errs.slice(0, 3).map(e => e.error).join(' ')
          : t('bulkEdit.saveFailed'),
        variant: 'destructive',
      });
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
      invalidate(['bulk-products'], ['products'], ['combos'], ['dashboard']);
    } catch (error: unknown) {
      const errs = (error as { response?: { data?: { errors?: BulkApplyError[] } } })
        ?.response?.data?.errors ?? [];
      toast({
        title: t('common.error'),
        description: errs.length
          ? errs.slice(0, 3).map(e => e.error).join(' ')
          : t('bulkEdit.importApplyFailed'),
        variant: 'destructive',
      });
    } finally {
      setImporting(false);
    }
  };

  const dirtyCount = Object.keys(edits).length;
  const dirtyClass = 'border-amber-500 bg-amber-50 dark:bg-amber-950/30';
  const errorClass = 'border-red-500 bg-red-50 dark:bg-red-950/30';

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
            <div className="flex flex-col sm:flex-row sm:items-center gap-3 w-full">
              <div className="relative max-w-sm w-full">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input placeholder={t('bulkEdit.searchPlaceholder')} className="pl-8"
                  value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer whitespace-nowrap">
                <input type="checkbox" className="rounded" checked={changedOnly}
                  onChange={e => setChangedOnly(e.target.checked)} />
                {t('bulkEdit.changedOnly')}
              </label>
            </div>
            <div className="flex items-center gap-3">
              {problemCount > 0 && (
                <span className="flex items-center gap-1 text-sm text-red-600 whitespace-nowrap">
                  <AlertTriangle className="h-4 w-4" />
                  {t('bulkEdit.problemCount', { count: problemCount })}
                </span>
              )}
              <Button disabled={dirtyCount === 0 || problemCount > 0}
                onClick={() => setReviewOpen(true)}>
                <Save className="mr-2 h-4 w-4" />
                {t('bulkEdit.reviewAndSave')}{dirtyCount ? ` (${dirtyCount})` : ''}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={8} columns={5} /> : (
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('bulkEdit.colProduct')}</TableHead>
                <TableHead className="w-36">{t('bulkEdit.colSize')}</TableHead>
                <TableHead className="w-32">{t('bulkEdit.colPrice')}</TableHead>
                <TableHead className="w-32">{t('bulkEdit.colDiscountPrice')}</TableHead>
                <TableHead className="w-28">{t('bulkEdit.colStock')}</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    {changedOnly ? t('bulkEdit.noChangesYet') : t('bulkEdit.noMatch')}
                  </TableCell>
                </TableRow>
              )}
              {lines.map(({ product, variant, first, sizeCount }) => {
                const productCell = first ? (
                  <div>
                    <div className="font-medium">
                      {product.name}
                      {product.is_active === false && (
                        <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                          {t('common.inactive')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {product.category_name || '—'}
                      {sizeCount > 1 && ` · ${t('bulkEdit.sizesCount', { count: sizeCount })}`}
                    </div>
                  </div>
                ) : null;

                if (!variant) {
                  return (
                    <TableRow key={`p-${product.id}`} className="border-t-2">
                      <TableCell>{productCell}</TableCell>
                      <TableCell colSpan={5} className="text-sm text-muted-foreground">
                        {t('bulkEdit.noActiveSize')}
                      </TableCell>
                    </TableRow>
                  );
                }

                const issue = problem(variant) ?? serverErrors[variant.id] ?? null;
                const cellClass = (field: Field) =>
                  issue && edits[variant.id] ? errorClass
                    : isDirty(variant, field) ? dirtyClass : '';
                return (
                  <TableRow key={variant.id} className={first ? 'border-t-2' : 'border-t-0'}>
                    <TableCell className="align-top">
                      {productCell}
                      {/* In the wide column, so the reason reads on one line
                          instead of wrapping under a narrow number box. */}
                      {issue && (
                        <p className={`flex items-center gap-1 text-xs text-red-600 ${first ? 'mt-1' : 'pt-2.5'}`}>
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {issue}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="pt-2 font-mono text-sm">
                        {variant.label}
                        {variant.is_default && sizeCount > 1 && (
                          <span className="ml-1 font-sans text-[10px] text-muted-foreground">
                            {t('bulkEdit.defaultSuffix')}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <Input
                        type="number" inputMode="decimal" min="0" step="0.01"
                        aria-label={`${product.name} ${variant.label} ${t('bulkEdit.colPrice')}`}
                        className={cellClass('price')}
                        value={value(variant, 'price')}
                        onChange={(e) => setEdit(product, variant, 'price', e.target.value)}
                      />
                    </TableCell>
                    <TableCell className="align-top">
                      <Input
                        type="number" inputMode="decimal" min="0" step="0.01"
                        placeholder={t('bulkEdit.none')}
                        aria-label={`${product.name} ${variant.label} ${t('bulkEdit.colDiscountPrice')}`}
                        className={cellClass('discount_price')}
                        value={value(variant, 'discount_price')}
                        onChange={(e) => setEdit(product, variant, 'discount_price', e.target.value)}
                      />
                    </TableCell>
                    <TableCell className="align-top">
                      <Input
                        type="number" inputMode="numeric" min="0" step="1"
                        aria-label={`${product.name} ${variant.label} ${t('bulkEdit.colStock')}`}
                        className={cellClass('stock')}
                        value={value(variant, 'stock')}
                        onChange={(e) => setEdit(product, variant, 'stock', e.target.value)}
                      />
                    </TableCell>
                    <TableCell className="align-top">
                      {edits[variant.id] && (
                        <Button variant="ghost" size="icon" title={t('bulkEdit.undoRow')}
                          onClick={() => resetLine(variant)}>
                          <Undo2 className="h-4 w-4" />
                        </Button>
                      )}
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
              {t('bulkEdit.importColumnsHint')} <b>size</b>, <b>price</b>, <b>discount_price</b>, <b>stock</b>.{' '}
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
