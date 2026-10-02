import { useState } from 'react';
import { useAdminData } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import {
  getCategories, createCategory, updateCategory, deleteCategory, Category,
} from '@/api/categories';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { checkImageFile } from '@/lib/imageCheck';
import { Plus, Edit, EyeOff, Eye } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

const Categories = () => {
  const { t } = useTranslation();
  const {
    data: categories = [], isInitialLoading, refreshing, refetch: fetchCategories,
  } = useAdminData(['categories'], () => getCategories().then(res => res.data));
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [formData, setFormData] = useState({ name: '', description: '' });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const { toast } = useToast();

  const resetForm = () => {
    setEditing(null);
    setFormData({ name: '', description: '' });
    setImageFile(null);
    setImagePreview(null);
  };

  const openEdit = (category: Category) => {
    setEditing(category);
    setFormData({ name: category.name, description: category.description || '' });
    setImageFile(null);
    setImagePreview(category.image || null);
    setDialogOpen(true);
  };

  const handleImageSelect = async (file: File | undefined) => {
    if (!file) return;
    const check = await checkImageFile(file);
    if (!check.ok) {
      toast({
        title: t('imageCheck.problemTitle'),
        description: t(check.errorKey!, check.params),
        variant: 'destructive',
      });
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

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      toast({
        title: t('categories.nameNeededTitle'),
        description: t('categories.nameNeededBody'),
        variant: 'destructive',
      });
      return;
    }
    setSaving(true);
    try {
      const form = new FormData();
      form.append('name', formData.name.trim());
      form.append('description', formData.description);
      if (imageFile) form.append('image', imageFile);
      if (editing) {
        await updateCategory(editing.slug || editing.id, form);
        toast({
          title: t('categories.savedTitle'),
          description: t('categories.savedBody', { name: formData.name }),
        });
      } else {
        await createCategory(form);
        toast({
          title: t('categories.createdTitle'),
          description: t('categories.createdBody', { name: formData.name }),
        });
      }
      setDialogOpen(false);
      resetForm();
      fetchCategories();
    } catch (error) {
      toast({
        title: t('common.error'),
        description: error instanceof Error && error.message
          ? error.message
          : t('categories.saveFailed'),
        variant: 'destructive',
      });
    } finally {
      setSaving(false);
    }
  };

  // "Delete" is a soft hide on the backend (is_active=False) — say so plainly.
  const handleHide = async (category: Category) => {
    if (!confirm(t('categories.confirmHide', { name: category.name }))) return;
    try {
      await deleteCategory(category.slug || category.id);
      toast({
        title: t('categories.hiddenTitle'),
        description: t('categories.hiddenBody', { name: category.name }),
      });
      fetchCategories();
    } catch {
      toast({
        title: t('common.error'),
        description: t('categories.hideFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleShow = async (category: Category) => {
    try {
      await updateCategory(category.slug || category.id, { is_active: true });
      toast({
        title: t('categories.visibleTitle'),
        description: t('categories.visibleBody', { name: category.name }),
      });
      fetchCategories();
    } catch {
      toast({
        title: t('common.error'),
        description: t('categories.updateFailed'),
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('categories.title')}</h1>
          <p className="text-muted-foreground">{t('categories.subtitle')}</p>
        </div>
        <Button onClick={() => { resetForm(); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> {t('categories.addButton')}
        </Button>
      </div>

      <PageHelp>{t('categories.pageHelp')}</PageHelp>

      <Card>
        <CardHeader><CardTitle>{t('categories.allCategories')}</CardTitle></CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={5} columns={5} /> : (
          <Table className="min-w-[500px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('common.image')}</TableHead>
                <TableHead>{t('common.name')}</TableHead>
                <TableHead>{t('common.description')}</TableHead>
                <TableHead>{t('categories.colVisible')}</TableHead>
                <TableHead className="text-right">{t('common.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {categories.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    {t('categories.empty')}
                  </TableCell>
                </TableRow>
              )}
              {categories.map((category) => (
                <TableRow key={category.id}>
                  <TableCell>
                    {category.image && (
                      <img src={category.image} alt={category.name}
                        className="h-8 w-8 rounded-full object-cover" />
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{category.name}</TableCell>
                  <TableCell className="max-w-[300px] truncate text-muted-foreground">
                    {category.description || '—'}
                  </TableCell>
                  <TableCell>
                    {category.is_active !== false
                      ? <span className="text-green-600 text-sm">{t('categories.shown')}</span>
                      : <span className="text-muted-foreground text-sm">{t('categories.hidden')}</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => openEdit(category)} title={t('common.edit')}>
                      <Edit className="h-4 w-4" />
                    </Button>
                    {category.is_active !== false ? (
                      <Button variant="ghost" size="icon" onClick={() => handleHide(category)}
                        title={t('categories.hideTitle')}>
                        <EyeOff className="h-4 w-4 text-amber-600" />
                      </Button>
                    ) : (
                      <Button variant="ghost" size="icon" onClick={() => handleShow(category)}
                        title={t('categories.showTitle')}>
                        <Eye className="h-4 w-4 text-green-600" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) resetForm(); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t('categories.editTitle') : t('categories.addTitle')}</DialogTitle>
            <DialogDescription>
              {editing ? t('categories.editDescription') : t('categories.addDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="cat-name">{t('categories.nameLabel')}</Label>
              <Input
                id="cat-name"
                placeholder={t('categories.namePlaceholder')}
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="cat-desc">{t('categories.descLabel')}</Label>
              <Textarea
                id="cat-desc"
                placeholder={t('categories.descPlaceholder')}
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="cat-image">{t('categories.photoLabel')}</Label>
              <Input
                id="cat-image"
                type="file"
                accept="image/*"
                onChange={(e) => handleImageSelect(e.target.files?.[0])}
              />
              {imagePreview && (
                <img src={imagePreview} alt="Preview" className="mt-2 h-24 w-24 rounded object-cover border" />
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleSubmit} disabled={saving}>
              {saving ? t('common.saving') : editing ? t('categories.saveChanges') : t('categories.addSubmit')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Categories;
