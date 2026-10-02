import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAdminData, useInvalidate } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import { getCombos, getCombo, createCombo, updateCombo, updateComboSections, Combo, ComboItem } from '@/api/combos';
import { getProducts, Product } from '@/api/products';
import { getSections, ProductSection } from '@/api/sections';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { Plus, Edit, ToggleLeft, ToggleRight, AlertTriangle } from 'lucide-react';
import { ComboItemsEditor } from '@/components/ComboItemsEditor';
import { ComboLine, lineProblem } from '@/lib/comboLines';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';


const Combos = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const {
    data: combos = [], isInitialLoading, refreshing, refetch: fetchCombos,
  } = useAdminData(['combos'], () => getCombos().then(r => r.data || []));
  // Shared cache with Products/Sections — opening this page after those is free.
  const { data: allProducts = [], refetch: fetchAllProducts } =
    useAdminData(['products'], () => getProducts().then(r => r.data));
  const { data: sections = [] } = useAdminData(['sections'], () => getSections());
  // Only active products can go into a new combo, but an existing combo may
  // still reference one that was since deactivated — hence both lists.
  const products = allProducts.filter(p => p.is_active);
  const [selectedSections, setSelectedSections] = useState<number[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCombo, setEditingCombo] = useState<Combo | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    description: '',
    // `variant` is the packaging size bundled — the unit of price and stock.
    items: [] as ComboLine[],
    // NOTE: no `price`. A combo's MRP is DERIVED server-side as the sum of its
    // component sizes' prices, so it is displayed (see computedMrp) but never
    // typed or posted. `discount_price` is the only price an admin sets.
    discount_price: '',
    weight: '',
    unit: 'g',
    low_stock_threshold: '5',
    is_active: true,
    is_featured: false,
  });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { toast } = useToast();

  /** Patch one combo's active flag in the cached list (optimistic + revert). */
  const setComboActive = (id: number, isActive: boolean) =>
    queryClient.setQueryData(['combos'], (prev: Combo[] | undefined) =>
      prev?.map(c => (c.id === id ? { ...c, is_active: isActive } : c)));

  const parseNumberOrZero = (value: string) => {
    const n = parseFloat(value);
    return Number.isNaN(n) ? 0 : n;
  };

  const toggleSection = (sectionId: number) => {
    setSelectedSections((prev) =>
      prev.includes(sectionId) ? prev.filter((id) => id !== sectionId) : [...prev, sectionId]
    );
  };

  const buildFormData = () => {
    const form = new FormData();
    form.append('name', formData.name);
    if (formData.slug && !editingCombo) form.append('slug', formData.slug);
    if (formData.description) form.append('description', formData.description);
    // No `price`: the server derives the MRP from the items posted below.
    if (formData.discount_price) {
      form.append('discount_price', String(parseNumberOrZero(formData.discount_price)));
    }
    form.append('weight', String(parseNumberOrZero(formData.weight)));
    form.append('unit', formData.unit);
    form.append('low_stock_threshold', String(parseNumberOrZero(formData.low_stock_threshold)));
    form.append('is_active', String(formData.is_active));
    form.append('is_featured', String(formData.is_featured));
    
    // Build items array — send the SIZE (variant) as well as the product. The
    // backend keys the component on the variant; sending product alone makes it
    // fall back to the default size, which is what we're fixing.
    const items = formData.items
      .filter((i) => i.product !== '')
      .map((i) => ({
        product: i.product,  // This should be the product ID
        variant: i.variant || undefined,
        quantity: i.quantity || 1
      }));
    
    // Always append items as JSON string
    form.append('items', JSON.stringify(items));
    
    if (imageFile) form.append('image', imageFile);
    
    return form;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // Validate items
    const validItems = formData.items.filter((i) => i.product !== '');
    if (validItems.length === 0) {
      toast({
        title: t('combos.validationTitle'),
        description: t('combos.needOneProduct'),
        variant: 'destructive',
      });
      return;
    }

    // A line whose size was retired, or whose product is gone, can't be saved —
    // the server would refuse it. Say which line, here, instead of after upload.
    const broken = validItems.find(line => lineProblem(line, allProducts));
    if (broken) {
      const name = getProductById(broken.product)?.name || broken.productName || '';
      toast({
        title: t('combos.validationTitle'),
        description: `${name}: ${t(lineProblem(broken, allProducts)!)}`,
        variant: 'destructive',
      });
      return;
    }

    // Mirror the server's rule, so the admin sees the problem next to the field
    // rather than as a 400 after upload. The MRP is derived, so a selling price
    // at or above it means the bundle is no cheaper than buying the parts.
    // `>` not `>=`: the server (ProductCombo.clean / ProductComboSerializer.validate)
    // permits a bundle priced exactly AT the sum of its parts — a legitimate
    // curation with no discount, which the field's own help text promises. Only
    // charging MORE than à-la-carte is wrong.
    const sellingPrice = parseNumberOrZero(formData.discount_price);
    if (formData.discount_price && sellingPrice > computedMrp) {
      toast({
        title: t('combos.validationTitle'),
        description: t('combos.priceAboveMrp', { mrp: computedMrp.toFixed(2) }),
        variant: 'destructive',
      });
      return;
    }


    setSubmitting(true);
    
    try {
      const form = buildFormData();

      // Slug we can address the combo by afterwards to set its sections.
      let comboSlug: string;
      if (editingCombo) {
        await updateCombo(editingCombo.slug, form);
        comboSlug = editingCombo.slug;
        toast({ title: t('combos.successTitle'), description: t('combos.updatedBody') });
      } else {
        const created = await createCombo(form);
        comboSlug = created.slug;
        toast({ title: t('combos.successTitle'), description: t('combos.createdBody') });
      }

      // Replace homepage-section placements (separate JSON PATCH so an empty
      // selection cleanly clears all placements).
      await updateComboSections(comboSlug, selectedSections);

      setDialogOpen(false);
      resetForm();
      // A combo's section placements just changed too.
      invalidate(['combos'], ['sections']);
    } catch (error: any) {
      console.error('Submit error:', error);
      toast({
        title: t('common.error'),
        description: error.message || t('combos.saveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };
const handleToggleStatus = async (combo: Combo) => {
  const newStatus = !combo.is_active;
  
  // Optimistic update
  setComboActive(combo.id, newStatus);

  try {
    // Send as JSON instead of FormData for simple updates
    await updateCombo(combo.slug, { is_active: newStatus });
    
    toast({
      title: t('combos.successTitle'),
      description: newStatus ? t('combos.markedActive') : t('combos.markedInactive'),
    });
    
    if (editingCombo && editingCombo.id === combo.id) {
      setEditingCombo({ ...editingCombo, is_active: newStatus });
      setFormData(prev => ({ ...prev, is_active: newStatus }));
    }
  } catch (error) {
    console.error('Toggle status error:', error);
    // Revert on error
    setComboActive(combo.id, !newStatus);

    // Show the server's reason: a combo that lost a line to a switched-off
    // product can't go back on sale above its new MRP, and "failed" alone
    // gives the admin nothing to act on.
    toast({
      title: t('common.error'),
      description: (error as { message?: string })?.message || t('combos.statusFailed'),
      variant: 'destructive',
    });
  }
};


  const openEditDialog = async (combo: Combo) => {
    setEditingCombo(combo);
    
    try {
      await fetchAllProducts();
      
      // Fetch full combo details using slug
      const fullCombo = await getCombo(combo.slug);
      
      // Map items - use product ID from the response
      const mappedItems: ComboLine[] = (fullCombo.items || []).map((i: ComboItem) => ({
        product: String(i.product),  // This is the product ID
        variant: i.variant ? String(i.variant) : '',
        quantity: i.quantity,
        // Kept so a line whose size has since been retired can still be named.
        productName: i.product_name,
        variantLabel: i.variant_label,
      }));
      
      setEditingCombo(fullCombo);
      setFormData({
        name: fullCombo.name,
        slug: fullCombo.slug,
        description: fullCombo.description || '',
        items: mappedItems,
        // No `price` — it is derived from `items` and shown read-only.
        discount_price: fullCombo.discount_price !== undefined && fullCombo.discount_price !== null ? String(fullCombo.discount_price) : '',
        weight: fullCombo.weight !== undefined && fullCombo.weight !== null ? String(fullCombo.weight) : '',
        unit: fullCombo.unit || 'g',
        low_stock_threshold: fullCombo.low_stock_threshold !== undefined && fullCombo.low_stock_threshold !== null ? String(fullCombo.low_stock_threshold) : '5',
        is_active: fullCombo.is_active,
        is_featured: fullCombo.is_featured || false,
      });
      setSelectedSections(fullCombo.sections || []);
      setImageFile(null);
      setImagePreview(fullCombo.image || null);
      setDialogOpen(true);
    } catch (error) {
      console.error('Failed to load combo:', error);
      toast({
        title: t('common.error'),
        description: t('combos.loadDetailsFailed'),
        variant: 'destructive',
      });
      setEditingCombo(null);
    }
  };

  const resetForm = () => {
    setEditingCombo(null);
    setFormData({
      name: '',
      slug: '',
      description: '',
      items: [],
      discount_price: '',
      weight: '',
      unit: 'g',
      low_stock_threshold: '5',
      is_active: true,
      is_featured: false,
    });
    setSelectedSections([]);
    setImageFile(null);
    setImagePreview(null);
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  const formatMoney = (value: string | number | undefined) => {
    if (value === undefined || value === null) return null;
    const n = typeof value === 'number' ? value : parseFloat(value);
    if (Number.isNaN(n)) return null;
    return n.toFixed(2);
  };

  // Get product by ID from allProducts
  const getProductById = (productId: string) => {
    return allProducts.find(p => String(p.id) === String(productId));
  };

  /**
   * The MRP the backend will derive: sum of each component SIZE's price times
   * its quantity. Must price off the variant, not `product.price` (a mirror of
   * whichever size happens to be default), or the figure shown here disagrees
   * with the one the API returns after saving.
   */
  const computedMrp = formData.items.reduce((total, item) => {
    const product = getProductById(item.product);
    const size = (product?.variants || []).find(v => String(v.id) === item.variant);
    return total + Number(size?.price ?? 0) * (item.quantity || 1);
  }, 0);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('combos.title')}</h1>
          <p className="text-muted-foreground">{t('combos.subtitle')}</p>
        </div>
        <Button onClick={() => { resetForm(); fetchAllProducts(); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> {t('combos.addButton')}
        </Button>
      </div>

      <PageHelp>{t('combos.pageHelp')}</PageHelp>

      <Card>
        <CardHeader>
          <CardTitle>{t('combos.allCombos')}</CardTitle>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={6} columns={6} /> : (
          <>
          <Table className="min-w-[600px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('common.image')}</TableHead>
                <TableHead>{t('common.name')}</TableHead>
                <TableHead>{t('combos.colProducts')}</TableHead>
                <TableHead>{t('common.price')}</TableHead>
                <TableHead>{t('combos.colDiscountedPrice')}</TableHead>
                <TableHead>{t('combos.colWeight')}</TableHead>
                <TableHead>{t('common.status')}</TableHead>
                <TableHead className="text-right">{t('common.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {combos.map((combo) => {
                const price = formatMoney(combo.price);
                const discount = formatMoney(combo.discount_price);
                return (
                  <TableRow key={combo.id}>
                    <TableCell>
                      {combo.image && (
                        <img
                          src={combo.image}
                          alt={combo.name}
                          className="h-8 w-8 rounded-full object-cover"
                        />
                      )}
                    </TableCell>
                    <TableCell className="font-medium">{combo.name}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {(combo.items || []).map((item) => {
                          // Either makes the combo unsellable (checkout refuses
                          // it). A switched-off product is normally taken out of
                          // the combo automatically, so `productOff` only shows
                          // for a row that was changed outside the panel.
                          const sizeRetired = item.variant_is_active === false;
                          const productOff = !sizeRetired && item.product_is_active === false;
                          return (
                            <span
                              key={item.variant}
                              title={sizeRetired ? t('combos.componentUnavailable')
                                : productOff ? t('combos.componentProductOff') : undefined}
                              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${
                                sizeRetired ? 'border-red-400 bg-red-50 text-red-700 dark:bg-red-950/30'
                                  : productOff ? 'border-red-400 bg-red-50 text-red-700 dark:bg-red-950/30'
                                  : 'bg-muted/50'
                              }`}
                            >
                              {(sizeRetired || productOff) && <AlertTriangle className="h-3 w-3" />}
                              {item.product_name} {item.variant_label}
                              {item.quantity > 1 ? ` ×${item.quantity}` : ''}
                            </span>
                          );
                        })}
                        {!combo.items?.length && (
                          <span className="text-xs text-red-600">{t('combos.noComponents')}</span>
                        )}
                      </div>
                      {!!combo.missing_products?.length && (
                        <div className="mt-1 flex items-start gap-1 text-xs text-amber-700">
                          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                          {t('combos.missingProducts', { products: combo.missing_products.join(', ') })}
                        </div>
                      )}
                      {combo.available_stock !== undefined && (
                        <div className={`mt-1 text-xs ${combo.available_stock > 0 ? 'text-muted-foreground' : 'text-red-600 font-medium'}`}>
                          {t('combos.canBuild', { count: combo.available_stock })}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono">
                      {price !== null ? `₹${price}` : '—'}
                    </TableCell>
                    <TableCell className="font-mono">
                      {discount !== null ? `₹${discount}` : '—'}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      {/* The form posts 0 for a blank weight; "0.00g" is not a weight. */}
                      {Number(combo.weight) > 0 ? `${Number(combo.weight)}${combo.unit || ''}` : '—'}
                    </TableCell>
                    <TableCell>
                      <span className={
                        `inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${
                          combo.is_active
                            ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                        }`
                      }>
                        {combo.is_active ? t('common.active') : t('common.inactive')}
                      </span>
                    </TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => openEditDialog(combo)} 
                        title={t('combos.editTooltip')}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleToggleStatus(combo)}
                        title={combo.is_active
                          ? t('combos.deactivateTooltip')
                          : t('combos.activateTooltip')}
                        className={
                          combo.is_active
                            ? 'hover:bg-green-500/10 text-green-600 hover:text-green-700'
                            : 'hover:bg-red-500/10 text-red-600 hover:text-red-700'
                        }
                      >
                        {combo.is_active
                          ? <ToggleRight className="h-5 w-5" />
                          : <ToggleLeft className="h-5 w-5" />}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {combos.length === 0 && (
            <div className="text-center py-12">
              <p className="text-muted-foreground">{t('combos.noneFound')}</p>
            </div>
          )}
          </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) resetForm();
        }}
      >
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingCombo ? t('combos.editTitle') : t('combos.addTitle')}</DialogTitle>
            <DialogDescription>
              {editingCombo ? t('combos.editDescription') : t('combos.addDescription')}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="relative h-20 w-20 rounded-full overflow-hidden bg-muted flex items-center justify-center">
                {imagePreview ? (
                  <img src={imagePreview} alt="Combo" className="h-full w-full object-cover" />
                ) : (
                  <span className="text-xs text-muted-foreground text-center px-2">
                    {t('combos.noImage')}
                  </span>
                )}
              </div>
              <div className="space-y-1">
                <Label htmlFor="image">{t('combos.comboImage')}</Label>
                <Input
                  id="image"
                  type="file"
                  accept="image/*"
                  onChange={handleImageChange}
                  className="cursor-pointer"
                />
                <p className="text-xs text-muted-foreground">{t('combos.imageHint')}</p>
              </div>
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="name">{t('combos.nameLabel')}</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={e => setFormData({ ...formData, name: e.target.value })}
                  required
                  placeholder={t('combos.namePlaceholder')}
                />
              </div>

              <div>
                <Label htmlFor="slug">{t('combos.slugLabel')}</Label>
                <Input
                  id="slug"
                  value={formData.slug}
                  onChange={e => setFormData({ ...formData, slug: e.target.value })}
                  placeholder={t('combos.slugPlaceholder')}
                  disabled={!!editingCombo}
                />
              </div>
            </div>
            
            <div>
              <Label htmlFor="description">{t('combos.descriptionLabel')}</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={e => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('combos.descriptionPlaceholder')}
                rows={3}
              />
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="mrp">{t('combos.mrpLabel')}</Label>
                <Input
                  id="mrp"
                  value={`₹${computedMrp.toFixed(2)}`}
                  readOnly
                  disabled
                  className="bg-muted font-mono"
                />
                <p className="text-xs text-muted-foreground mt-1">{t('combos.mrpHint')}</p>
              </div>
              <div>
                <Label htmlFor="discount_price">{t('combos.sellingPriceLabel')}</Label>
                <Input
                  id="discount_price"
                  type="number"
                  step="0.01"
                  min="0"
                  value={formData.discount_price}
                  onChange={e => setFormData({ ...formData, discount_price: e.target.value })}
                  placeholder="0.00"
                />
                <p className="text-xs text-muted-foreground mt-1">{t('combos.sellingPriceHint')}</p>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex-1">
                <Label htmlFor="weight">{t('combos.weightLabel')}</Label>
                <Input
                  id="weight"
                  type="number"
                  step="0.01"
                  min="0"
                  value={formData.weight}
                  onChange={e => setFormData({ ...formData, weight: e.target.value })}
                  placeholder={t('combos.weightPlaceholder')}
                />
                <p className="text-xs text-muted-foreground mt-1">{t('combos.weightHint')}</p>
              </div>
              <div className="w-24">
                <Label htmlFor="unit">{t('combos.unitLabel')}</Label>
                <Select
                  value={formData.unit}
                  onValueChange={value => setFormData({ ...formData, unit: value })}
                >
                  <SelectTrigger id="unit">
                    <SelectValue placeholder={t('combos.unitLabel')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="g">g</SelectItem>
                    <SelectItem value="kg">kg</SelectItem>
                    <SelectItem value="ml">ml</SelectItem>
                    <SelectItem value="l">l</SelectItem>
                    <SelectItem value="pc">pc</SelectItem>
                    <SelectItem value="box">box</SelectItem>
                    <SelectItem value="pack">pack</SelectItem>
                    <SelectItem value="combo">combo</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <Label htmlFor="low_stock_threshold">{t('combos.lowStockLabel')}</Label>
              <Input
                id="low_stock_threshold"
                type="number"
                min="0"
                step="1"
                value={formData.low_stock_threshold}
                onChange={e => setFormData({ ...formData, low_stock_threshold: e.target.value })}
                placeholder={t('combos.lowStockPlaceholder')}
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t('combos.lowStockHint')}
                {editingCombo?.available_stock !== undefined && (
                  <>{t('combos.lowStockCurrent', { count: editingCombo.available_stock })}</>
                )}
              </p>
            </div>

            <ComboItemsEditor
              products={allProducts}
              lines={formData.items}
              onChange={(items) => setFormData(prev => ({ ...prev, items }))}
            />

            {/* Homepage Sections */}
            <div className="space-y-2 rounded-lg border p-3">
              <div>
                <Label className="text-base">{t('combos.homepageSections')}</Label>
                <p className="text-xs text-muted-foreground">{t('combos.homepageSectionsHint')}</p>
              </div>
              {sections.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('combos.noSections')}</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {sections.map((section) => (
                    <label
                      key={section.id}
                      className="flex items-center gap-2 text-sm cursor-pointer rounded-md border px-3 py-2"
                    >
                      <input
                        type="checkbox"
                        className="rounded"
                        checked={selectedSections.includes(section.id)}
                        onChange={() => toggleSection(section.id)}
                      />
                      <span className="truncate">{section.name}</span>
                      {!section.is_active && (
                        <span className="text-xs text-muted-foreground">{t('combos.sectionInactive')}</span>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-4 sm:gap-6">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="is_active"
                  checked={formData.is_active}
                  onChange={e => setFormData({ ...formData, is_active: e.target.checked })}
                  className="rounded"
                />
                <Label htmlFor="is_active" className="cursor-pointer">{t('common.active')}</Label>
              </div>
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="is_featured"
                  checked={formData.is_featured}
                  onChange={e => setFormData({ ...formData, is_featured: e.target.checked })}
                  className="rounded"
                />
                <Label htmlFor="is_featured" className="cursor-pointer">{t('combos.featured')}</Label>
              </div>
            </div>
            
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={() => { setDialogOpen(false); resetForm(); }}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? t('common.saving') : (editingCombo ? t('combos.update') : t('combos.create'))}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Combos;
