import { useMemo, useState } from 'react';
import { Product, ProductVariant } from '@/api/products';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { AlertTriangle, Check, Minus, Plus, Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ComboLine, activeSizes, lineProblem } from '@/lib/comboLines';

interface Props {
  /** The whole catalogue, including inactive products (for existing lines). */
  products: Product[];
  lines: ComboLine[];
  onChange: (lines: ComboLine[]) => void;
}

const sizeLabel = (v: ProductVariant, fallback: string) => v.formatted_weight || fallback;

/**
 * Picks the sizes a combo is built from.
 *
 * The unit a combo consumes is a SIZE, so this never asks for "a product, then
 * its size" as two separate dropdowns. The catalogue is listed with every
 * active size as its own button: one click adds that exact pack, and a second
 * size of the same product is just another click — each becomes its own line.
 * A size already in the combo is marked and can't be added twice (the server
 * treats a repeat as an error; the quantity box is how you ask for more).
 */
export const ComboItemsEditor = ({ products, lines, onChange }: Props) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);

  const usedVariantIds = useMemo(
    () => new Set(lines.map(l => l.variant).filter(Boolean)), [lines]);

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products
      .filter(p => p.is_active)
      .filter(p => !q
        || p.name.toLowerCase().includes(q)
        || (p.category_name || '').toLowerCase().includes(q)
        || activeSizes(p).some(v => (v.formatted_weight || '').toLowerCase().includes(q)))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [products, query]);

  const addSize = (product: Product, variant: ProductVariant) => {
    if (usedVariantIds.has(String(variant.id))) return;
    onChange([...lines, {
      product: String(product.id),
      variant: String(variant.id),
      quantity: 1,
      productName: product.name,
      variantLabel: variant.formatted_weight,
    }]);
  };

  const patchLine = (index: number, patch: Partial<ComboLine>) =>
    onChange(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));

  const removeLine = (index: number) => onChange(lines.filter((_, i) => i !== index));

  const total = lines.reduce((sum, line) => {
    const product = products.find(p => String(p.id) === line.product);
    const size = activeSizes(product).find(v => String(v.id) === line.variant);
    return sum + Number(size?.price ?? 0) * (line.quantity || 1);
  }, 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <Label>{t('combos.productsInCombo')}</Label>
        <Button type="button" variant="outline" size="sm"
          onClick={() => setPickerOpen(open => !open)}>
          {pickerOpen
            ? <><X className="h-4 w-4 mr-1" /> {t('combos.closePicker')}</>
            : <><Plus className="h-4 w-4 mr-1" /> {t('combos.addProduct')}</>}
        </Button>
      </div>

      {/* ---- The lines already in the combo ---- */}
      {lines.length === 0 && !pickerOpen && (
        <p className="text-sm text-muted-foreground">{t('combos.noProductsAdded')}</p>
      )}

      {lines.map((line, index) => {
        const product = products.find(p => String(p.id) === line.product);
        const sizes = activeSizes(product);
        const selected = sizes.find(v => String(v.id) === line.variant) ?? null;
        const problemKey = lineProblem(line, products);
        const name = product?.name || line.productName
          || t('combos.productNotFound', { id: line.product });
        const lineTotal = Number(selected?.price ?? 0) * (line.quantity || 1);
        const shortBy = selected ? (line.quantity || 1) - selected.stock : 0;

        return (
          <div key={`${line.product}-${line.variant}-${index}`}
            className={`rounded-lg border p-3 space-y-2 ${problemKey ? 'border-red-500 bg-red-50 dark:bg-red-950/20' : ''}`}>
            <div className="flex items-start gap-3">
              {product?.image
                ? <img src={product.image} alt="" className="h-10 w-10 rounded object-cover shrink-0" />
                : <div className="h-10 w-10 rounded bg-muted shrink-0" />}
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">
                  {name}
                  {product && !product.is_active && (
                    <span className="ml-2 text-xs font-normal text-amber-700">
                      {t('combos.inactiveSuffix')}
                    </span>
                  )}
                </div>

                {/* Size buttons: switch this line to another pack of the same
                    product. Sizes used by another line are locked. */}
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {sizes.map(v => {
                    const isSelected = String(v.id) === line.variant;
                    const usedElsewhere = !isSelected && usedVariantIds.has(String(v.id));
                    return (
                      <button
                        key={v.id}
                        type="button"
                        disabled={usedElsewhere}
                        onClick={() => patchLine(index, {
                          variant: String(v.id), variantLabel: v.formatted_weight,
                        })}
                        title={usedElsewhere ? t('combos.sizeUsedElsewhere') : undefined}
                        className={`rounded-md border px-2 py-1 text-xs font-mono transition-colors ${
                          isSelected
                            ? 'border-primary bg-primary text-primary-foreground'
                            : usedElsewhere
                              ? 'opacity-40 cursor-not-allowed'
                              : 'hover:bg-muted'
                        }`}
                      >
                        {sizeLabel(v, t('combos.defaultSize'))} · ₹{Number(v.price).toFixed(2)}
                      </button>
                    );
                  })}
                  {!selected && line.variantLabel && (
                    <span className="rounded-md border border-red-400 px-2 py-1 text-xs font-mono line-through text-red-700">
                      {line.variantLabel}
                    </span>
                  )}
                </div>

                {problemKey ? (
                  <p className="mt-1.5 flex items-center gap-1 text-xs text-red-700">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {t(problemKey)}
                  </p>
                ) : selected && (
                  <p className={`mt-1.5 text-xs ${shortBy > 0 ? 'text-amber-700' : 'text-muted-foreground'}`}>
                    {shortBy > 0
                      ? t('combos.lineShortStock', { stock: selected.stock, need: line.quantity })
                      : t('combos.stockLine', { stock: selected.stock })}
                  </p>
                )}
              </div>

              <div className="flex flex-col items-end gap-1 shrink-0">
                <div className="flex items-center gap-1">
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8"
                    aria-label={t('combos.qtyLess')}
                    disabled={line.quantity <= 1}
                    onClick={() => patchLine(index, { quantity: Math.max(1, line.quantity - 1) })}>
                    <Minus className="h-3 w-3" />
                  </Button>
                  <Input
                    type="number" min="1" inputMode="numeric"
                    aria-label={t('combos.qty')}
                    className="h-8 w-14 text-center px-1"
                    value={line.quantity}
                    onChange={e => {
                      const n = parseInt(e.target.value, 10);
                      patchLine(index, { quantity: Number.isNaN(n) || n < 1 ? 1 : n });
                    }}
                  />
                  <Button type="button" variant="outline" size="icon" className="h-8 w-8"
                    aria-label={t('combos.qtyMore')}
                    onClick={() => patchLine(index, { quantity: line.quantity + 1 })}>
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <span className="text-xs font-mono text-muted-foreground">
                  ₹{lineTotal.toFixed(2)}
                </span>
              </div>

              <Button type="button" variant="ghost" size="icon"
                className="text-destructive hover:text-destructive shrink-0"
                aria-label={t('combos.removeLine')} title={t('combos.removeLine')}
                onClick={() => removeLine(index)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        );
      })}

      {/* ---- The picker: every product, every active size one click away ---- */}
      {pickerOpen && (
        <div className="rounded-lg border">
          <div className="relative border-b p-2">
            <Search className="absolute left-4 top-4 h-4 w-4 text-muted-foreground" />
            <Input autoFocus className="pl-8" placeholder={t('combos.pickerSearch')}
              value={query} onChange={e => setQuery(e.target.value)} />
          </div>
          <div className="max-h-72 overflow-y-auto divide-y">
            {candidates.length === 0 && (
              <p className="p-3 text-sm text-muted-foreground">{t('combos.pickerEmpty')}</p>
            )}
            {candidates.map(product => {
              const sizes = activeSizes(product);
              return (
                <div key={product.id} className="flex items-center gap-3 p-2">
                  {product.image
                    ? <img src={product.image} alt="" className="h-8 w-8 rounded object-cover shrink-0" />
                    : <div className="h-8 w-8 rounded bg-muted shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{product.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {sizes.length === 0 && (
                        <span className="text-xs text-muted-foreground">{t('combos.noActiveSize')}</span>
                      )}
                      {sizes.map(v => {
                        const added = usedVariantIds.has(String(v.id));
                        return (
                          <button
                            key={v.id}
                            type="button"
                            disabled={added}
                            onClick={() => addSize(product, v)}
                            className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-mono transition-colors ${
                              added
                                ? 'border-green-600 bg-green-50 text-green-800 dark:bg-green-950/30 dark:text-green-400'
                                : 'hover:bg-muted'
                            }`}
                          >
                            {added ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                            {sizeLabel(v, t('combos.defaultSize'))} · ₹{Number(v.price).toFixed(2)}
                            <span className={`font-sans ${v.stock > 0 ? 'text-muted-foreground' : 'text-red-600'}`}>
                              {v.stock > 0
                                ? t('combos.pickerStock', { stock: v.stock })
                                : t('combos.outOfStock')}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {lines.length > 0 && (
        <div className="border-t pt-3">
          <div className="flex justify-between items-center text-sm">
            <span className="font-medium">{t('combos.comboMrp')}</span>
            <span className="font-mono font-semibold">₹{total.toFixed(2)}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">{t('combos.comboMrpHint')}</p>
        </div>
      )}
    </div>
  );
};
