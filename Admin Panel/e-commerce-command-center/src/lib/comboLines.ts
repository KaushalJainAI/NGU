import type { TFunction } from 'i18next';
import { ComboChanges, Product, ProductVariant } from '@/api/products';

/** One component line of a combo: an exact SIZE of a product, times a quantity. */
export interface ComboLine {
  product: string;
  variant: string;
  quantity: number;
  /** Names as the server last reported them. The product list only carries
   *  ACTIVE sizes, so a line whose size has since been retired (or whose
   *  product is gone) can still say what it used to be. */
  productName?: string;
  variantLabel?: string;
}

export const activeSizes = (product?: Product): ProductVariant[] =>
  (product?.variants || []).filter(v => v.is_active);

/** What is wrong with a line, as a translation key — or null if it can be saved.
 *  Shared by the editor (to flag the line) and the form (to refuse to submit
 *  what the server would refuse anyway). */
export const lineProblem = (line: ComboLine, products: Product[]): string | null => {
  const product = products.find(p => String(p.id) === line.product);
  if (!product) return 'combos.lineProductGone';
  const sizes = activeSizes(product);
  if (sizes.length === 0) return 'combos.noActiveSize';
  if (!line.variant) return 'combos.lineNoSize';
  if (!sizes.some(v => String(v.id) === line.variant)) return 'combos.lineSizeRetired';
  return null;
};

/** One sentence telling the admin what a product switch did to combos, or null
 *  if it touched none. Used wherever a product is switched off or restored. */
export const comboChangesMessage = (changes: ComboChanges | undefined, t: TFunction): string | null => {
  if (!changes) return null;
  const parts: string[] = [];
  if (changes.removed_from?.length) {
    parts.push(t('combos.changeRemovedFrom', { combos: changes.removed_from.join(', ') }));
  }
  if (changes.switched_off?.length) {
    parts.push(t('combos.changeSwitchedOff', { combos: changes.switched_off.join(', ') }));
  }
  if (changes.restored_to?.length) {
    parts.push(t('combos.changeRestoredTo', { combos: changes.restored_to.join(', ') }));
  }
  if (changes.switched_on?.length) {
    parts.push(t('combos.changeSwitchedOn', { combos: changes.switched_on.join(', ') }));
  }
  return parts.length ? parts.join(' ') : null;
};
