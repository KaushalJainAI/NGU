import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAdminData, useInvalidate } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import { useSearchParams } from 'react-router-dom';
import {
  getProducts, getProduct, createProduct, updateProduct, updateProductSections, Product, ProductImage,
  createProductImage, deleteProductImage, getSpiceForms,
  getProductVariants, createProductVariant, updateProductVariant, deleteProductVariant,
} from '@/api/products';
import { getCategories, Category } from '@/api/categories';
import { getSections, ProductSection } from '@/api/sections';
import { getHsnReference, HsnCode } from '@/api/gst';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { Plus, Edit, ToggleLeft, ToggleRight, X, ImagePlus, Loader2, Trash2, Search, Copy } from 'lucide-react';
import { checkImageFile } from '@/lib/imageCheck';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

const UNIT_OPTIONS = ['g', 'kg', 'ml', 'l', 'pc', 'box', 'pack'];

type VariantRow = {
  key: string;
  id?: number;
  weight: string;
  unit: string;
  price: string;
  discount_price: string;
  stock: string;
  is_default: boolean;
  is_active: boolean;
};

let _rowSeq = 0;
const newRowKey = () => `row-${Date.now()}-${_rowSeq++}`;
const blankVariantRow = (is_default = false): VariantRow => ({
  key: newRowKey(), weight: '', unit: 'g', price: '', discount_price: '',
  stock: '0', is_default, is_active: true,
});

const Products = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  // Four independent caches: the catalog is shared with Sections/RecycleBin,
  // while categories/sections/spice-forms are near-static reference data that
  // no longer refetch every time this page is opened.
  const {
    data: products = [], isInitialLoading, refreshing, refetch: fetchProducts,
  } = useAdminData(['products'], () => getProducts().then(r => r.data || []));
  const { data: categories = [] } =
    useAdminData(['categories'], () => getCategories().then(r => r.data || []));
  const { data: sections = [] } = useAdminData(['sections'], () => getSections());
  const { data: spiceForms = [] } = useAdminData(['spice-forms'], () => getSpiceForms());
  // Static reference data (the curated HSN code list + the statutory rate for
  // each). Cached like the other near-static lookups — it changes when the law
  // changes, not when the catalogue does.
  const { data: hsnRef } = useAdminData(['hsn-reference'], () => getHsnReference());
  const [selectedSections, setSelectedSections] = useState<number[]>([]);
  // The dashboard's "Restock products" button deep-links to /products?stock=low.
  const [searchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('search') || '');
  const [filterCategory, setFilterCategory] = useState('all');
  const [filterStock, setFilterStock] = useState<'all' | 'low' | 'out'>(() => {
    const s = searchParams.get('stock');
    return s === 'low' || s === 'out' ? s : 'all';
  });
  const [sortBy, setSortBy] = useState<'newest' | 'name' | 'priceLow' | 'priceHigh' | 'stockLow'>('name');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    category: '',
    spice_form: '',
    price: '',
    discount_price: '',
    tax_rate: '5',
    hsn_code: '',
    stock: '',
    low_stock_threshold: '5',
    weight: '',
    unit: 'g',
    origin_country: '',
    organic: false,
    shelf_life: '',
    ingredients: '',
    is_active: true,
    is_featured: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);

  // Packaging sizes (variants)
  const [variantRows, setVariantRows] = useState<VariantRow[]>([blankVariantRow(true)]);
  const [removedVariantIds, setRemovedVariantIds] = useState<number[]>([]);
  
  // Gallery images state
  const [galleryImages, setGalleryImages] = useState<ProductImage[]>([]);
  const [newGalleryImages, setNewGalleryImages] = useState<{ file: File; preview: string }[]>([]);
  const [uploadingGallery, setUploadingGallery] = useState(false);

  const { toast } = useToast();

  /** Patch one product's active flag in the cached list (optimistic + revert). */
  const setProductActive = (id: number, isActive: boolean) =>
    queryClient.setQueryData(['products'], (prev: Product[] | undefined) =>
      prev?.map(p => (p.id === id ? { ...p, is_active: isActive } : p)));

  const parseNumberOrZero = (value: string) => {
    const n = parseFloat(value);
    return Number.isNaN(n) ? 0 : n;
  };

  // ---- GST classification helpers ----
  // The reference row for whatever code is currently typed/selected, and the
  // statutory rate that goes with it. Both are ADVISORY: the admin types the
  // rate, this only makes a disagreement visible. Auto-applying it would change
  // how every future invoice splits the price, silently.
  const hsnCodes: HsnCode[] = hsnRef?.codes ?? [];
  const selectedHsn = hsnCodes.find(c => c.code === (formData.hsn_code || '').trim());
  const enteredRate = parseFloat(formData.tax_rate);
  const rateDiffers =
    !!selectedHsn && Number.isFinite(enteredRate) && enteredRate !== selectedHsn.gst_rate;

  const toggleSection = (sectionId: number) => {
    setSelectedSections((prev) =>
      prev.includes(sectionId) ? prev.filter((id) => id !== sectionId) : [...prev, sectionId]
    );
  };

  // ---- Packaging size (variant) row helpers ----
  const getDefaultRow = (): VariantRow | undefined => {
    const active = variantRows.filter(r => r.is_active);
    return active.find(r => r.is_default) || active[0] || variantRows[0];
  };

  const addVariantRow = () => {
    setVariantRows(prev => [...prev, blankVariantRow(prev.length === 0)]);
  };

  const updateVariantRow = (key: string, patch: Partial<VariantRow>) => {
    setVariantRows(prev => prev.map(r => (r.key === key ? { ...r, ...patch } : r)));
  };

  const setDefaultRow = (key: string) => {
    setVariantRows(prev => prev.map(r => ({ ...r, is_default: r.key === key })));
  };

  const removeVariantRow = (key: string) => {
    setVariantRows(prev => {
      const row = prev.find(r => r.key === key);
      if (row?.id) setRemovedVariantIds(ids => [...ids, row.id as number]);
      const remaining = prev.filter(r => r.key !== key);
      // Ensure one default remains among active rows
      if (row?.is_default) {
        const firstActive = remaining.find(r => r.is_active);
        if (firstActive) firstActive.is_default = true;
      }
      return [...remaining];
    });
  };

  const buildFormData = () => {
    // The product's legacy price/stock/weight fields are seeded from the
    // default size; the backend then keeps them mirrored to the default variant.
    const def = getDefaultRow();
    const form = new FormData();
    form.append('name', formData.name);
    if (formData.description) form.append('description', formData.description);
    if (formData.category) form.append('category', formData.category);
    if (formData.spice_form) form.append('spice_form', formData.spice_form);
    form.append('price', String(parseNumberOrZero(def?.price ?? '0')));
    if (def?.discount_price) form.append('discount_price', String(parseNumberOrZero(def.discount_price)));
    form.append('stock', String(parseInt(def?.stock ?? '0') || 0));
    // Per-product low-stock alert level (emails the admin when stock falls to
    // or below this). Product-level threshold; sizes can have their own too.
    form.append('low_stock_threshold', String(parseInt(formData.low_stock_threshold ?? '5') || 0));
    // Per-product GST rate (%), matching the backend model default of 5. Prices
    // are GST-INCLUSIVE, so this only splits the price on the invoice — it never
    // changes what the customer pays. 0 for exempt goods (papad / papad katran).
    form.append('tax_rate', String(parseNumberOrZero(formData.tax_rate || '5')));
    // Sent even when blank, so an admin can CLEAR a code they decided was wrong.
    // Blank is a meaningful value here ("not classified yet"), not a no-op.
    form.append('hsn_code', (formData.hsn_code || '').trim());
    form.append('weight', String(parseNumberOrZero(def?.weight ?? '0')));
    form.append('unit', def?.unit || 'g');
    if (formData.origin_country) form.append('origin_country', formData.origin_country);
    form.append('organic', String(formData.organic));
    if (formData.shelf_life) form.append('shelf_life', formData.shelf_life);
    if (formData.ingredients) form.append('ingredients', formData.ingredients);
    form.append('is_active', String(formData.is_active));
    form.append('is_featured', String(formData.is_featured));
    if (imageFile) form.append('image', imageFile);
    return form;
  };

  const syncVariants = async (productId: number) => {
    // Removals first — the API retires the size, it never deletes the row
    for (const id of removedVariantIds) {
      try { await deleteProductVariant(id); } catch { /* ignore individual failures */ }
    }
    // Guarantee one default among active rows
    const hasDefault = variantRows.some(r => r.is_active && r.is_default);
    let assignedDefault = hasDefault;
    let idx = 0;
    for (const r of variantRows) {
      let isDefault = r.is_active && r.is_default;
      if (!assignedDefault && r.is_active) { isDefault = true; assignedDefault = true; }
      const payload = {
        product: productId,
        weight: parseNumberOrZero(r.weight),
        unit: r.unit,
        price: parseNumberOrZero(r.price),
        discount_price: r.discount_price ? parseNumberOrZero(r.discount_price) : null,
        stock: parseInt(r.stock) || 0,
        is_default: isDefault,
        is_active: r.is_active,
        display_order: idx++,
      };
      if (r.id) await updateProductVariant(r.id, payload);
      else await createProductVariant(payload);
    }
  };

  /** Returns a translation KEY, not a sentence, so the caller renders it in
   *  whichever language is active when the toast fires. */
  const validateVariants = (): string | null => {
    const active = variantRows.filter(r => r.is_active);
    if (active.length === 0) return 'products.needOneSize';
    for (const r of active) {
      if (!(parseNumberOrZero(r.weight) > 0)) return 'products.needWeight';
      if (!(parseNumberOrZero(r.price) > 0)) return 'products.needPrice';
      if (r.discount_price && parseNumberOrZero(r.discount_price) >= parseNumberOrZero(r.price))
        return 'products.discountTooHigh';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const sizeErrorKey = validateVariants();
    if (sizeErrorKey) {
      toast({
        title: t('products.checkSizesTitle'),
        description: t(sizeErrorKey),
        variant: 'destructive',
      });
      return;
    }
    if (!editingProduct && !imageFile) {
      toast({
        title: t('products.imageRequiredTitle'),
        description: t('products.imageRequiredBody'),
        variant: 'destructive',
      });
      return;
    }

    setSubmitting(true);
    try {
      const form = buildFormData();
      let productId: number;
      // The product-detail endpoint is addressed by slug (lookup_field='slug'),
      // so section placement PATCHes must use the slug, not the numeric id.
      let productSlug: string;

      if (editingProduct) {
        await updateProduct(editingProduct.slug, form);
        productId = editingProduct.id;
        productSlug = editingProduct.slug;
      } else {
        const newProduct = await createProduct(form);
        productId = newProduct.id;
        productSlug = newProduct.slug;
      }

      // Sync packaging sizes (variants) — keyed by the numeric product id.
      await syncVariants(productId);

      // Replace homepage-section placements. Sent as a separate JSON PATCH so an
      // empty selection cleanly clears all placements (a multipart body can't
      // express an empty list).
      await updateProductSections(productSlug, selectedSections);

      // Upload gallery images if any
      if (newGalleryImages.length > 0) {
        await uploadGalleryImages(productId);
      }

      toast({
        title: t('products.successTitle'),
        description: editingProduct ? t('products.updatedBody') : t('products.createdBody'),
      });
      setDialogOpen(false);
      resetForm();
      // Saving a product can change its sections and its stock, so the pages
      // built on those (Sections, Bulk edit, dashboard low-stock) go stale too.
      invalidate(['products'], ['sections'], ['bulk-products'], ['dashboard']);
    } catch (error: any) {
      console.error('Submit error:', error);
      toast({
        title: t('common.error'),
        description: error.message || t('products.saveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleStatus = async (product: Product) => {
    const newStatus = !product.is_active;
    
    // Optimistic update - update UI immediately
    setProductActive(product.id, newStatus);


    try {
      // Create FormData for the update
      const formData = new FormData();
      formData.append('is_active', String(newStatus));
      
      await updateProduct(product.slug, formData);
      toast({
        title: t('products.successTitle'),
        description: newStatus ? t('products.markedActive') : t('products.markedInactive'),
      });
      
      // Also update editingProduct if it's the same product being edited
      if (editingProduct && editingProduct.id === product.id) {
        setEditingProduct({ ...editingProduct, is_active: newStatus });
        setFormData(prev => ({ ...prev, is_active: newStatus }));
      }
    } catch (error: any) {
      console.error('Toggle error:', error);
      
      // Revert optimistic update on error
      setProductActive(product.id, !newStatus);


      toast({
        title: t('common.error'),
        description: error.message || t('products.statusFailed'),
        variant: 'destructive',
      });
    }
  };

  const openEditDialog = async (product: Product) => {
    setEditingProduct(product);
    try {
      const fullProduct = await getProduct(product.slug);
      setEditingProduct(fullProduct);
      setFormData({
        name: fullProduct.name,
        description: fullProduct.description || '',
        category: String(fullProduct.category),
        spice_form: fullProduct.spice_form || '',
        price: fullProduct.price !== undefined && fullProduct.price !== null ? String(fullProduct.price) : '',
        discount_price: fullProduct.discount_price !== undefined && fullProduct.discount_price !== null ? String(fullProduct.discount_price) : '',
        tax_rate: fullProduct.tax_rate !== undefined && fullProduct.tax_rate !== null ? String(fullProduct.tax_rate) : '5',
        hsn_code: fullProduct.hsn_code || '',
        stock: String(fullProduct.stock ?? 0),
        low_stock_threshold: fullProduct.low_stock_threshold != null ? String(fullProduct.low_stock_threshold) : '5',
        weight: fullProduct.weight !== undefined && fullProduct.weight !== null ? String(fullProduct.weight) : '',
        unit: fullProduct.unit || 'g',
        origin_country: fullProduct.origin_country || 'India',
        organic: fullProduct.organic || false,
        shelf_life: fullProduct.shelf_life || '',
        ingredients: fullProduct.ingredients || '',
        is_active: fullProduct.is_active ?? true,
        is_featured: fullProduct.is_featured || false,
      });
      setImageFile(null);
      setImagePreview(fullProduct.image || null);
      // Prefill the section placements from the product (array of section IDs).
      setSelectedSections(fullProduct.sections || []);
      // Set gallery images from product
      setGalleryImages(fullProduct.images || []);
      setNewGalleryImages([]);
      // Load packaging sizes (variants), including inactive ones, for editing
      setRemovedVariantIds([]);
      try {
        const variants = await getProductVariants(product.id);
        if (variants.length > 0) {
          setVariantRows(
            variants
              .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0))
              .map(v => ({
                key: newRowKey(),
                id: v.id,
                weight: v.weight !== null && v.weight !== undefined ? String(v.weight) : '',
                unit: v.unit || 'g',
                price: v.price !== null && v.price !== undefined ? String(v.price) : '',
                discount_price: v.discount_price !== null && v.discount_price !== undefined ? String(v.discount_price) : '',
                stock: String(v.stock ?? 0),
                is_default: !!v.is_default,
                is_active: v.is_active !== false,
              }))
          );
        } else {
          // Legacy product without variants — seed one default row from its fields
          setVariantRows([{
            key: newRowKey(), weight: fullProduct.weight ? String(fullProduct.weight) : '',
            unit: fullProduct.unit || 'g',
            price: fullProduct.price !== undefined && fullProduct.price !== null ? String(fullProduct.price) : '',
            discount_price: fullProduct.discount_price !== undefined && fullProduct.discount_price !== null ? String(fullProduct.discount_price) : '',
            stock: String(fullProduct.stock ?? 0), is_default: true, is_active: true,
          }]);
        }
      } catch {
        setVariantRows([blankVariantRow(true)]);
      }
      setDialogOpen(true);
    } catch {
      toast({
        title: t('common.error'),
        description: t('products.loadDetailsFailed'),
        variant: 'destructive',
      });
      setEditingProduct(null);
    }
  };

  const resetForm = () => {
    setEditingProduct(null);
    setFormData({
      name: '',
      description: '',
      category: '',
      spice_form: '',
      price: '',
      discount_price: '',
      tax_rate: '5',
      // Must be reset explicitly: omitting it left the previous product's HSN
      // code sitting in the form when "Add Product" was opened after an edit.
      hsn_code: '',
      stock: '',
      low_stock_threshold: '5',
      weight: '',
      unit: 'g',
      origin_country: '',
      organic: false,
      shelf_life: '',
      ingredients: '',
      is_active: true,
      is_featured: false,
    });
    setImageFile(null);
    setImagePreview(null);
    setSelectedSections([]);
    // Reset gallery images
    setGalleryImages([]);
    setNewGalleryImages([]);
    // Reset packaging sizes to a single default row
    setVariantRows([blankVariantRow(true)]);
    setRemovedVariantIds([]);
  };

  const handleImageChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const check = await checkImageFile(file);
    if (!check.ok) {
      toast({
        title: t('imageCheck.problemTitle'),
        description: t(check.errorKey!, check.params),
        variant: 'destructive',
      });
      e.target.value = '';
      return;
    }
    if (check.warningKey) {
      toast({
        title: t('imageCheck.smallTitle'),
        description: t(check.warningKey, check.params),
      });
    }
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  // Duplicate: open the create dialog pre-filled from an existing product so
  // similar SKUs don't have to be typed from scratch. Images stay behind —
  // the copy gets its own photos.
  const openDuplicateDialog = async (product: Product) => {
    try {
      const fullProduct = await getProduct(product.slug);
      resetForm();
      setFormData({
        name: `${fullProduct.name}${t('products.copySuffix')}`,
        description: fullProduct.description || '',
        category: String(fullProduct.category),
        spice_form: fullProduct.spice_form || '',
        price: fullProduct.price != null ? String(fullProduct.price) : '',
        discount_price: fullProduct.discount_price != null ? String(fullProduct.discount_price) : '',
        tax_rate: fullProduct.tax_rate != null ? String(fullProduct.tax_rate) : '5',
        hsn_code: fullProduct.hsn_code || '',
        stock: '0',
        low_stock_threshold: fullProduct.low_stock_threshold != null ? String(fullProduct.low_stock_threshold) : '5',
        weight: fullProduct.weight != null ? String(fullProduct.weight) : '',
        unit: fullProduct.unit || 'g',
        origin_country: fullProduct.origin_country || 'India',
        organic: fullProduct.organic || false,
        shelf_life: fullProduct.shelf_life || '',
        ingredients: fullProduct.ingredients || '',
        is_active: false, // start hidden so the admin reviews it before it goes live
        is_featured: false,
      });
      setDialogOpen(true);
      toast({
        title: t('products.copyReadyTitle'),
        description: t('products.copyReadyBody'),
      });
    } catch {
      toast({
        title: t('common.error'),
        description: t('products.loadDetailsFailed'),
        variant: 'destructive',
      });
    }
  };

  // Gallery image handlers
  const handleGalleryImageAdd = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    const accepted: { file: File; preview: string }[] = [];
    for (const file of Array.from(files)) {
      const check = await checkImageFile(file);
      if (!check.ok) {
        toast({
          title: t('imageCheck.skippedTitle'),
          description: t(check.errorKey!, check.params),
          variant: 'destructive',
        });
        continue;
      }
      if (check.warningKey) {
        toast({
          title: t('imageCheck.smallTitle'),
          description: t(check.warningKey, check.params),
        });
      }
      accepted.push({ file, preview: URL.createObjectURL(file) });
    }
    if (accepted.length) setNewGalleryImages(prev => [...prev, ...accepted]);
    // Reset input so same file can be selected again
    e.target.value = '';
  };

  const handleRemoveNewGalleryImage = (index: number) => {
    setNewGalleryImages(prev => {
      // Revoke URL to prevent memory leak
      URL.revokeObjectURL(prev[index].preview);
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleDeleteExistingGalleryImage = async (imageId: number) => {
    try {
      await deleteProductImage(imageId);
      setGalleryImages(prev => prev.filter(img => img.id !== imageId));
      toast({ title: t('products.successTitle'), description: t('products.galleryDeleted') });
    } catch {
      toast({
        title: t('common.error'),
        description: t('products.galleryDeleteFailed'),
        variant: 'destructive',
      });
    }
  };

  const uploadGalleryImages = async (productId: number) => {
    if (newGalleryImages.length === 0) return;
    
    setUploadingGallery(true);
    try {
      for (const img of newGalleryImages) {
        await createProductImage(productId, img.file, '');
      }
      toast({
        title: t('products.successTitle'),
        description: t('products.galleryUploaded', { count: newGalleryImages.length }),
      });
    } catch {
      toast({
        title: t('common.error'),
        description: t('products.galleryUploadFailed'),
        variant: 'destructive',
      });
    } finally {
      setUploadingGallery(false);
    }
  };

  const formatMoney = (value: string | number | undefined) => {
    if (value === undefined || value === null) return null;
    const n = typeof value === 'number' ? value : parseFloat(value);
    if (Number.isNaN(n)) return null;
    return n.toFixed(2);
  };

  // Search/filter/sort run client-side: the admin product list is unpaginated
  // (backend pagination_class=None), so the full catalog is already in memory.
  // "Low" is per-product: each product carries its own low_stock_threshold
  // (backend default 5), matching what the dashboard, digest and low-stock API
  // consider low — so the ?stock=low deep-link shows exactly that set.
  const isLowStock = (p: Product) => p.stock > 0 && p.stock <= (p.low_stock_threshold ?? 5);
  const visibleProducts = useMemo(() => {
    let list = products;
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(p =>
        p.name.toLowerCase().includes(q) ||
        (p.category_name || '').toLowerCase().includes(q)
      );
    }
    if (filterCategory !== 'all') {
      list = list.filter(p => String(p.category) === filterCategory);
    }
    if (filterStock === 'low') list = list.filter(isLowStock);
    if (filterStock === 'out') list = list.filter(p => p.stock === 0);
    const sorted = [...list];
    switch (sortBy) {
      case 'name': sorted.sort((a, b) => a.name.localeCompare(b.name)); break;
      case 'priceLow': sorted.sort((a, b) => Number(a.price) - Number(b.price)); break;
      case 'priceHigh': sorted.sort((a, b) => Number(b.price) - Number(a.price)); break;
      case 'stockLow': sorted.sort((a, b) => a.stock - b.stock); break;
      default: break; // 'newest' — keep server order (-created_at)
    }
    return sorted;
  }, [products, searchQuery, filterCategory, filterStock, sortBy]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('products.title')}</h1>
          <p className="text-muted-foreground">{t('products.subtitle')}</p>
        </div>
        <Button onClick={() => { resetForm(); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> {t('products.addButton')}
        </Button>
      </div>

      <PageHelp>{t('products.pageHelp')}</PageHelp>

      <Card>
        <CardHeader>
          <CardTitle>{t('products.allProducts')}</CardTitle>
          <div className="flex flex-col sm:flex-row gap-2 pt-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('products.searchPlaceholder')}
                className="pl-8"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <Select value={filterCategory} onValueChange={setFilterCategory}>
              <SelectTrigger className="w-full sm:w-44">
                <SelectValue placeholder={t('products.allCategories')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('products.allCategories')}</SelectItem>
                {categories.map(c => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filterStock} onValueChange={(v) => setFilterStock(v as typeof filterStock)}>
              <SelectTrigger className="w-full sm:w-40">
                <SelectValue placeholder={t('products.stockFilter')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('products.anyStock')}</SelectItem>
                <SelectItem value="low">{t('products.lowStock')}</SelectItem>
                <SelectItem value="out">{t('products.outOfStock')}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={sortBy} onValueChange={(v) => setSortBy(v as typeof sortBy)}>
              <SelectTrigger className="w-full sm:w-44">
                <SelectValue placeholder={t('products.sort')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">{t('products.sortNewest')}</SelectItem>
                <SelectItem value="name">{t('products.sortName')}</SelectItem>
                <SelectItem value="priceLow">{t('products.sortPriceLow')}</SelectItem>
                <SelectItem value="priceHigh">{t('products.sortPriceHigh')}</SelectItem>
                <SelectItem value="stockLow">{t('products.sortStockLow')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={8} columns={6} /> : (
          <>
          <Table className="min-w-[600px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('common.image')}</TableHead>
                <TableHead>{t('common.name')}</TableHead>
                <TableHead>{t('common.category')}</TableHead>
                <TableHead>{t('common.price')}</TableHead>
                <TableHead>{t('products.colWeight')}</TableHead>
                <TableHead>{t('common.stock')}</TableHead>
                <TableHead>{t('common.status')}</TableHead>
                <TableHead className="text-right">{t('common.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleProducts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    {products.length === 0
                      ? t('products.emptyNoProducts')
                      : t('products.emptyNoMatch')}
                  </TableCell>
                </TableRow>
              )}
              {visibleProducts.map((product) => {
                const price = formatMoney(product.price);
                const discount = formatMoney(product.discount_price);
                return (
                  <TableRow key={product.id}>
                    <TableCell>
                      {product.image && (
                        <img
                          src={product.image}
                          alt={product.name}
                          className="h-8 w-8 rounded-full object-cover"
                        />
                      )}
                    </TableCell>
                    <TableCell className="font-medium">{product.name}</TableCell>
                    <TableCell>{product.category_name || '—'}</TableCell>
                    <TableCell className="font-mono">
                      {discount !== null ? (
                        <div className="space-y-0.5">
                          <div className="line-through text-xs text-muted-foreground">₹{price}</div>
                          <div className="text-green-600 font-semibold">₹{discount}</div>
                        </div>
                      ) : (
                        `₹${price}`
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      <div>{product.weight ? `${product.weight}${product.unit || ''}` : '—'}</div>
                      {product.variant_count && product.variant_count > 1 ? (
                        <div className="text-[10px] text-primary font-sans">
                          {t('products.sizesCount', { count: product.variant_count })}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <span className={
                        !product.stock ? 'text-red-600 font-semibold'
                          : isLowStock(product) ? 'text-amber-600 font-semibold'
                          : 'text-green-600'
                      }>
                        {product.stock || 0}
                        {!product.stock
                          ? t('products.outSuffix')
                          : isLowStock(product) ? t('products.lowSuffix') : ''}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className={
                        `inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${
                          product.is_active
                            ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                        }`
                      }>
                        {product.is_active ? t('common.active') : t('common.inactive')}
                      </span>
                    </TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => openEditDialog(product)}
                        title={t('products.editTooltip')}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openDuplicateDialog(product)}
                        title={t('products.duplicateTooltip')}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleToggleStatus(product)}
                        title={product.is_active
                          ? t('products.deactivateTooltip')
                          : t('products.activateTooltip')}
                        className={
                          product.is_active
                            ? 'hover:bg-green-500/10 text-green-600 hover:text-green-700'
                            : 'hover:bg-red-500/10 text-red-600 hover:text-red-700'
                        }
                      >
                        {product.is_active
                          ? <ToggleRight className="h-5 w-5" />
                          : <ToggleLeft className="h-5 w-5" />}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {products.length === 0 && (
            <div className="text-center py-12">
              <p className="text-muted-foreground">{t('products.noneFound')}</p>
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
            <DialogTitle>{editingProduct ? t('products.editTitle') : t('products.addTitle')}</DialogTitle>
            <DialogDescription>
              {editingProduct ? t('products.editDescription') : t('products.addDescription')}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="relative h-20 w-20 rounded-full overflow-hidden bg-muted flex items-center justify-center">
                {imagePreview ? (
                  <img src={imagePreview} alt="Product" className="h-full w-full object-cover" />
                ) : (
                  <span className="text-xs text-muted-foreground text-center px-2">
                    {t('products.noImage')}
                  </span>
                )}
              </div>
               <div className="space-y-1">
                <Label htmlFor="image">{t('products.productImage')} {!editingProduct && '*'}</Label>
                <Input
                  id="image"
                  type="file"
                  accept="image/*"
                  onChange={handleImageChange}
                  className="cursor-pointer"
                  required={!editingProduct}
                />
                <p className="text-xs text-muted-foreground">{t('products.imageHint')}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4">
              <div>
                <Label htmlFor="name">{t('products.nameLabel')}</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={e => setFormData({ ...formData, name: e.target.value })}
                  required
                  placeholder={t('products.namePlaceholder')}
                />
              </div>
            </div>

            <div>
              <Label htmlFor="description">{t('products.descriptionLabel')}</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={e => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('products.descriptionPlaceholder')}
                rows={3}
                required
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="category">{t('products.categoryLabel')}</Label>
                <Select
                  value={formData.category}
                  onValueChange={value => setFormData({ ...formData, category: value })}
                >
                  <SelectTrigger id="category">
                    <SelectValue placeholder={t('products.selectCategory')} />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map(category => (
                      <SelectItem key={category.id} value={String(category.id)}>
                        {category.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="spice_form">{t('products.spiceFormLabel')}</Label>
                <Select
                  value={formData.spice_form}
                  onValueChange={value => setFormData({ ...formData, spice_form: value })}
                >
                  <SelectTrigger id="spice_form">
                    <SelectValue placeholder={t('products.selectForm')} />
                  </SelectTrigger>
                  <SelectContent>
                    {spiceForms.map(formChoice => (
                      <SelectItem key={formChoice.value} value={formChoice.value}>
                        {formChoice.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Packaging Sizes (variants) */}
            <div className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-base">{t('products.packagingSizes')}</Label>
                  <p className="text-xs text-muted-foreground">
                    {t('products.packagingHintPrefix')}
                    <strong>{t('products.packagingHintStrong')}</strong>
                    {t('products.packagingHintSuffix')}
                  </p>
                </div>
                <Button type="button" variant="outline" size="sm" onClick={addVariantRow}>
                  <Plus className="mr-2 h-4 w-4" /> {t('products.addSize')}
                </Button>
              </div>

              <div className="space-y-2">
                {variantRows.map((row) => (
                  <div
                    key={row.key}
                    className={`grid grid-cols-12 gap-2 items-end rounded-md border p-2 ${row.is_active ? '' : 'opacity-60'}`}
                  >
                    <div className="col-span-3 sm:col-span-2">
                      <Label className="text-xs">{t('products.weight')}</Label>
                      <Input type="number" step="0.01" min="0" value={row.weight}
                        onChange={e => updateVariantRow(row.key, { weight: e.target.value })}
                        placeholder={t('products.weightPlaceholder')} />
                    </div>
                    <div className="col-span-3 sm:col-span-2">
                      <Label className="text-xs">{t('products.unit')}</Label>
                      <Select value={row.unit} onValueChange={v => updateVariantRow(row.key, { unit: v })}>
                        <SelectTrigger><SelectValue placeholder={t('products.unit')} /></SelectTrigger>
                        <SelectContent>
                          {UNIT_OPTIONS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="col-span-3 sm:col-span-2">
                      <Label className="text-xs">{t('products.price')}</Label>
                      <Input type="number" step="0.01" min="0" value={row.price}
                        onChange={e => updateVariantRow(row.key, { price: e.target.value })}
                        placeholder="0.00" />
                    </div>
                    <div className="col-span-3 sm:col-span-2">
                      <Label className="text-xs">{t('products.discountedPrice')}</Label>
                      <Input type="number" step="0.01" min="0" value={row.discount_price}
                        onChange={e => updateVariantRow(row.key, { discount_price: e.target.value })}
                        placeholder="—" />
                    </div>
                    <div className="col-span-3 sm:col-span-2">
                      <Label className="text-xs">{t('products.stock')}</Label>
                      <Input type="number" min="0" value={row.stock}
                        onChange={e => updateVariantRow(row.key, { stock: e.target.value })}
                        placeholder="0" />
                    </div>
                    <div className="col-span-6 sm:col-span-2 flex items-center gap-3 pb-2 flex-wrap">
                      <label className="flex items-center gap-1 text-xs cursor-pointer" title={t('products.defaultSize')}>
                        <input type="radio" name="default-variant" checked={row.is_default}
                          onChange={() => setDefaultRow(row.key)} />
                        {t('products.default')}
                      </label>
                      <label className="flex items-center gap-1 text-xs cursor-pointer" title={t('products.activeVisible')}>
                        <input type="checkbox" checked={row.is_active}
                          onChange={e => updateVariantRow(row.key, { is_active: e.target.checked })} />
                        {t('products.active')}
                      </label>
                      <Button type="button" variant="ghost" size="icon" className="ml-auto"
                        onClick={() => removeVariantRow(row.key)}
                        disabled={variantRows.length <= 1}
                        title={t('products.removeSize')}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="origin_country">{t('products.originCountry')}</Label>
                <Input
                  id="origin_country"
                  value={formData.origin_country}
                  onChange={e => setFormData({ ...formData, origin_country: e.target.value })}
                  placeholder="India"
                />
              </div>

              <div>
                <Label htmlFor="low_stock_threshold">{t('products.lowStockLevel')}</Label>
                <Input
                  id="low_stock_threshold"
                  type="number"
                  min="0"
                  step="1"
                  value={formData.low_stock_threshold}
                  onChange={e => setFormData({ ...formData, low_stock_threshold: e.target.value })}
                  placeholder="5"
                />
                <p className="text-xs text-muted-foreground mt-1">{t('products.lowStockHint')}</p>
              </div>

              <div>
                <Label htmlFor="tax_rate">{t('products.taxRate')}</Label>
                <Input
                  id="tax_rate"
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={formData.tax_rate}
                  onChange={e => setFormData({ ...formData, tax_rate: e.target.value })}
                  placeholder="5"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  {t('products.taxRateHintPrefix')}
                  <strong>{t('products.taxRateHintStrong')}</strong>
                  {t('products.taxRateHintSuffix')}
                </p>
              </div>
            </div>

            {/* ---- GST classification (HSN) ----
                Its own block rather than another cell in the grid above: the
                code drives what gets filed, and it needs room for the statutory
                rate, the caveat on the chosen heading, and the mismatch warning.
                Nothing here ever writes tax_rate on its own — the "Use N%"
                button is an explicit click, because what we charge is the
                owner's decision and a silent rate change would re-split the GST
                on every future invoice. */}
            <div className="space-y-2 rounded-lg border p-3">
              <div>
                <Label htmlFor="hsn_code" className="text-base">{t('products.hsnLabel')}</Label>
                <p className="text-xs text-muted-foreground">{t('products.hsnHint')}</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <Select
                    value={formData.hsn_code || 'none'}
                    onValueChange={v =>
                      setFormData({ ...formData, hsn_code: v === 'none' ? '' : v })}
                  >
                    <SelectTrigger id="hsn_code">
                      <SelectValue placeholder={t('products.hsnChoose')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t('products.hsnNotClassified')}</SelectItem>
                      {hsnCodes.map(c => (
                        <SelectItem key={c.code} value={c.code}>
                          {c.code} — {c.description} ({c.gst_rate}%)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Input
                    aria-label={t('products.hsnTypedLabel')}
                    value={formData.hsn_code}
                    onChange={e => setFormData({ ...formData, hsn_code: e.target.value })}
                    placeholder={t('products.hsnTypePlaceholder')}
                  />
                </div>
              </div>

              {selectedHsn && (
                <div className="rounded-md bg-muted/50 p-2 text-xs space-y-1">
                  <p>
                    <strong>{selectedHsn.code}</strong> — {selectedHsn.description}.
                    {' '}{t('products.hsnCurrentRate')}{' '}
                    <strong>{selectedHsn.gst_rate}%</strong>
                    {hsnRef?.rates_as_of && <> {t('products.hsnAsOf', { date: hsnRef.rates_as_of })}</>}.
                  </p>
                  {selectedHsn.note && (
                    <p className="text-muted-foreground">{selectedHsn.note}</p>
                  )}
                </div>
              )}

              {rateDiffers && (
                <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-xs space-y-2">
                  <p>
                    {t('products.hsnMismatchPrefix')}
                    <strong>{enteredRate}%</strong>
                    {t('products.hsnMismatchMiddle', { code: selectedHsn!.code })}
                    <strong>{selectedHsn!.gst_rate}%</strong>
                    {t('products.hsnMismatchSuffix')}
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setFormData({
                      ...formData, tax_rate: String(selectedHsn!.gst_rate),
                    })}
                  >
                    {t('products.hsnUseRate', { rate: selectedHsn!.gst_rate })}
                  </Button>
                </div>
              )}

              {!formData.hsn_code && (
                <p className="text-xs text-muted-foreground">{t('products.hsnBlankHint')}</p>
              )}
            </div>

            {/* Homepage Sections */}
            <div className="space-y-2 rounded-lg border p-3">
              <div>
                <Label className="text-base">{t('products.homepageSections')}</Label>
                <p className="text-xs text-muted-foreground">{t('products.homepageSectionsHint')}</p>
              </div>
              {sections.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('products.noSections')}</p>
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
                        <span className="text-xs text-muted-foreground">{t('products.sectionInactive')}</span>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="shelf_life">{t('products.shelfLife')}</Label>
                <Input
                  id="shelf_life"
                  value={formData.shelf_life}
                  onChange={e => setFormData({ ...formData, shelf_life: e.target.value })}
                  placeholder={t('products.shelfLifePlaceholder')}
                />
              </div>

              <div>
                <Label htmlFor="ingredients">{t('products.ingredients')}</Label>
                <Input
                  id="ingredients"
                  value={formData.ingredients}
                  onChange={e => setFormData({ ...formData, ingredients: e.target.value })}
                  placeholder={t('products.ingredientsPlaceholder')}
                />
              </div>
            </div>

            {/* Gallery Images Section */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>{t('products.galleryImages')}</Label>
                <label className="cursor-pointer">
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={handleGalleryImageAdd}
                    className="hidden"
                  />
                  <Button type="button" variant="outline" size="sm" asChild>
                    <span><ImagePlus className="mr-2 h-4 w-4" /> {t('products.addImages')}</span>
                  </Button>
                </label>
              </div>
              
              {/* Image Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {/* Existing gallery images */}
                {galleryImages.map((img) => (
                  <div key={img.id} className="relative group">
                    <img
                      src={img.image}
                      alt={img.alt_text || t('products.galleryAlt')}
                      className="h-24 w-full object-cover rounded-lg border"
                    />
                    <button
                      type="button"
                      onClick={() => handleDeleteExistingGalleryImage(img.id)}
                      className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                      title={t('products.deleteImage')}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
                
                {/* New images to upload */}
                {newGalleryImages.map((img, index) => (
                  <div key={`new-${index}`} className="relative group">
                    <img
                      src={img.preview}
                      alt={t('products.newImageAlt', { index: index + 1 })}
                      className="h-24 w-full object-cover rounded-lg border border-dashed border-primary"
                    />
                    <div className="absolute inset-0 bg-primary/10 rounded-lg flex items-center justify-center">
                      <span className="text-xs font-medium text-primary">{t('products.newBadge')}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemoveNewGalleryImage(index)}
                      className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                      title={t('products.removeImage')}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
                
                {/* Empty state */}
                {galleryImages.length === 0 && newGalleryImages.length === 0 && (
                  <div className="col-span-4 text-center py-6 text-muted-foreground text-sm border rounded-lg border-dashed">
                    {t('products.noGalleryImages')}
                  </div>
                )}
              </div>
              
              {uploadingGallery && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('products.uploadingGallery')}
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-4 sm:gap-6">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="organic"
                  checked={formData.organic}
                  onChange={e => setFormData({ ...formData, organic: e.target.checked })}
                  className="rounded"
                />
                <Label htmlFor="organic" className="cursor-pointer">{t('products.organic')}</Label>
              </div>

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
                <Label htmlFor="is_featured" className="cursor-pointer">{t('products.featured')}</Label>
              </div>
            </div>

            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={() => { setDialogOpen(false); resetForm(); }} disabled={submitting}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {editingProduct ? t('products.updating') : t('products.creating')}
                  </>
                ) : (
                  editingProduct ? t('products.updateProduct') : t('products.createProduct')
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Products;
