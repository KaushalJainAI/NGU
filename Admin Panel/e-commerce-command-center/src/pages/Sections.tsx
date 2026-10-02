import { useState } from 'react';
import { useAdminData } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import {
  getSections, createSection, updateSection, hideSection,
  getSectionProducts, setSectionProducts,
  ProductSection, SectionProduct,
} from '@/api/sections';
import { getProducts, Product } from '@/api/products';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import { Plus, Edit, EyeOff, Eye, ArrowUp, ArrowDown, X, ListOrdered } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

// The stored value is the API's slug; the label is looked up at render time so
// switching language re-labels existing sections.
const SECTION_TYPE_VALUES = [
  'special', 'new', 'trending', 'bestseller', 'seasonal', 'custom',
] as const;

const Sections = () => {
  const { t } = useTranslation();
  const { toast } = useToast();
  const typeLabel = (value: string) =>
    t(`sections.type.${value}`, { defaultValue: value });
  // Products are shared with the Products page — same cache key, so opening
  // this page after that one costs nothing.
  const { data: allProducts = [] } =
    useAdminData(['products'], () => getProducts().then(r => r.data));
  const {
    data: sections = [], isInitialLoading, refreshing, refetch: fetchAll,
  } = useAdminData(['sections'], () => getSections());

  // Create/edit dialog
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProductSection | null>(null);
  const [formData, setFormData] = useState({ name: '', section_type: 'custom', max_products: '12' });
  const [saving, setSaving] = useState(false);

  // "Arrange products" dialog
  const [arrangeOpen, setArrangeOpen] = useState(false);
  const [arrangeSection, setArrangeSection] = useState<ProductSection | null>(null);
  const [items, setItems] = useState<SectionProduct[]>([]);
  const [addProductId, setAddProductId] = useState('');
  const [savingOrder, setSavingOrder] = useState(false);

  const openCreate = () => {
    setEditing(null);
    setFormData({ name: '', section_type: 'custom', max_products: '12' });
    setDialogOpen(true);
  };

  const openEdit = (section: ProductSection) => {
    setEditing(section);
    setFormData({
      name: section.name,
      section_type: section.section_type,
      max_products: String(section.max_products ?? 12),
    });
    setDialogOpen(true);
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      toast({
        title: t('sections.nameNeededTitle'),
        description: t('sections.nameNeededBody'),
        variant: 'destructive',
      });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: formData.name.trim(),
        section_type: formData.section_type,
        max_products: parseInt(formData.max_products) || 12,
      };
      if (editing) {
        await updateSection(editing.id, payload);
        toast({
          title: t('sections.savedTitle'),
          description: t('sections.savedBody', { name: payload.name }),
        });
      } else {
        await createSection(payload);
        toast({
          title: t('sections.createdTitle'),
          description: t('sections.createdBody', { name: payload.name }),
        });
      }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error && error.message
          ? error.message
          : t('sections.saveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  const handleHide = async (section: ProductSection) => {
    if (!confirm(t('sections.confirmHide', { name: section.name }))) return;
    try {
      await hideSection(section.id);
      toast({
        title: t('sections.hiddenTitle'),
        description: t('sections.hiddenBody', { name: section.name }),
      });
      fetchAll();
    } catch {
      toast({
        title: t('common.error'),
        description: t('sections.hideFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleShow = async (section: ProductSection) => {
    try {
      await updateSection(section.id, { is_active: true });
      toast({
        title: t('sections.visibleTitle'),
        description: t('sections.visibleBody', { name: section.name }),
      });
      fetchAll();
    } catch {
      toast({
        title: t('common.error'),
        description: t('sections.updateFailed'),
        variant: 'destructive',
      });
    }
  };

  // ---- Arrange products ----
  const openArrange = async (section: ProductSection) => {
    setArrangeSection(section);
    setArrangeOpen(true);
    setItems(await getSectionProducts(section.id));
  };

  const move = (index: number, delta: -1 | 1) => {
    setItems(prev => {
      const next = [...prev];
      const j = index + delta;
      if (j < 0 || j >= next.length) return prev;
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
  };

  const removeItem = (id: number) => setItems(prev => prev.filter(i => i.id !== id));

  const addItem = () => {
    const pid = parseInt(addProductId);
    if (!pid) return;
    if (items.some(i => i.id === pid)) {
      toast({
        title: t('sections.alreadyAddedTitle'),
        description: t('sections.alreadyAddedBody'),
      });
      return;
    }
    const p = allProducts.find(pr => pr.id === pid);
    if (!p) return;
    setItems(prev => [...prev, {
      id: p.id, name: p.name, image: p.image || null,
      position: prev.length, is_active: p.is_active !== false,
    }]);
    setAddProductId('');
  };

  const saveOrder = async () => {
    if (!arrangeSection) return;
    setSavingOrder(true);
    try {
      await setSectionProducts(arrangeSection.id, items.map(i => i.id));
      toast({
        title: t('sections.savedTitle'),
        description: t('sections.orderSavedBody', {
          name: arrangeSection.name, count: items.length,
        }),
      });
      setArrangeOpen(false);
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error && error.message
          ? error.message
          : t('sections.orderSaveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSavingOrder(false);
    }
  };

  if (isInitialLoading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-9 w-64" />
        <TableSkeleton rows={4} columns={2} />
      </div>
    );
  }

  return (
    <div className={`space-y-6 p-6 transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('sections.title')}</h1>
          <p className="text-muted-foreground">{t('sections.subtitle')}</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> {t('sections.addButton')}
        </Button>
      </div>

      <PageHelp>{t('sections.pageHelp')}</PageHelp>

      <div className="grid gap-4 md:grid-cols-2">
        {sections.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              {t('sections.empty')}
            </CardContent>
          </Card>
        )}
        {sections.map(section => (
          <Card key={section.id} className={section.is_active ? undefined : 'opacity-60'}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <div>
                <CardTitle className="text-base">{section.name}</CardTitle>
                <p className="text-xs text-muted-foreground mt-1">
                  {typeLabel(section.section_type)}
                  {' · '}{t('sections.showsUpTo', { count: section.max_products })}
                  {!section.is_active && ` · ${t('sections.hiddenSuffix')}`}
                </p>
              </div>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => openArrange(section)}>
                <ListOrdered className="mr-2 h-4 w-4" /> {t('sections.arrangeButton')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => openEdit(section)}>
                <Edit className="mr-2 h-4 w-4" /> {t('common.edit')}
              </Button>
              {section.is_active ? (
                <Button variant="ghost" size="sm" className="text-amber-600" onClick={() => handleHide(section)}>
                  <EyeOff className="mr-2 h-4 w-4" /> {t('sections.hideButton')}
                </Button>
              ) : (
                <Button variant="ghost" size="sm" className="text-green-600" onClick={() => handleShow(section)}>
                  <Eye className="mr-2 h-4 w-4" /> {t('sections.showButton')}
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Create / edit section */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t('sections.editTitle') : t('sections.addTitle')}</DialogTitle>
            <DialogDescription>{t('sections.dialogDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="sec-name">{t('sections.nameLabel')}</Label>
              <Input
                id="sec-name"
                placeholder={t('sections.namePlaceholder')}
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>
            <div>
              <Label>{t('sections.typeLabel')}</Label>
              <Select
                value={formData.section_type}
                onValueChange={(v) => setFormData({ ...formData, section_type: v })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SECTION_TYPE_VALUES.map(value => (
                    <SelectItem key={value} value={value}>{typeLabel(value)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="sec-max">{t('sections.maxLabel')}</Label>
              <Input
                id="sec-max"
                type="number"
                min={1}
                value={formData.max_products}
                onChange={(e) => setFormData({ ...formData, max_products: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleSubmit} disabled={saving}>
              {saving ? t('common.saving') : editing ? t('sections.saveChanges') : t('sections.addSubmit')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Arrange products */}
      <Dialog open={arrangeOpen} onOpenChange={setArrangeOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('sections.arrangeTitle', { name: arrangeSection?.name ?? '' })}</DialogTitle>
            <DialogDescription>{t('sections.arrangeDescription')}</DialogDescription>
          </DialogHeader>

          <div className="flex gap-2">
            <Select value={addProductId} onValueChange={setAddProductId}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={t('sections.addProductPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {allProducts
                  .filter(p => !items.some(i => i.id === p.id))
                  .map(p => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={addItem} disabled={!addProductId}>{t('common.add')}</Button>
          </div>

          <div className="space-y-1">
            {items.length === 0 && (
              <p className="text-center text-muted-foreground py-6 text-sm">
                {t('sections.noProducts')}
              </p>
            )}
            {items.map((item, index) => (
              <div key={item.id} className="flex items-center gap-2 rounded border p-2">
                <span className="w-6 text-center text-sm text-muted-foreground">{index + 1}</span>
                {item.image && (
                  <img src={item.image} alt="" className="h-8 w-8 rounded object-cover" />
                )}
                <span className="flex-1 truncate text-sm font-medium">
                  {item.name}
                  {!item.is_active && (
                    <span className="ml-1 text-xs text-amber-600">{t('sections.hiddenProduct')}</span>
                  )}
                </span>
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={index === 0}
                  onClick={() => move(index, -1)}>
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={index === items.length - 1}
                  onClick={() => move(index, 1)}>
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                  onClick={() => removeItem(item.id)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setArrangeOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={saveOrder} disabled={savingOrder}>
              {savingOrder ? t('common.saving') : t('sections.saveOrder')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Sections;
