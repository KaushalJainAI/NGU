"""Keeping combos in step with the products they are built from.

Rule (owner's decision, 2026-10-02): **a product that is switched off is removed
from every combo.** Before this a discontinued product went on selling inside
any bundle that contained it, because combo availability and checkout look at
the SIZE, not at whether its product is still on sale.

Removing a line changes what the bundle IS — fewer goods for the same selling
price, under the same photo and description. So a combo that was on sale is
switched OFF at the same moment and waits for the owner to look at it: nothing
is ever sold at a price that was set for a different bundle. It is switched off
without a `deactivated_at` stamp, i.e. "off", not "deleted" — the Recycle Bin
purge never touches it.

All of it is reversible. Every removed line is remembered in
`DetachedComboLine`; switching the product back on restores the lines and
switches back on the combos this module had switched off — unless an admin has
edited or re-activated the combo in the meantime, which is them saying "sell it
as it is now" (see `forget_detached_lines`).

Called from `Product.save()` inside the save's own transaction.
"""
import logging

from .cache import invalidate_combo_cache, invalidate_search_cache
from .models import DetachedComboLine, ProductCombo, ProductComboItem

logger = logging.getLogger(__name__)


def _bust_caches():
    # ProductCombo rows are changed with .update() here (see below), which
    # fires no signals — so the caches those signals would bust are busted here.
    invalidate_combo_cache()
    invalidate_search_cache()


def detach_product_from_combos(product):
    """Take `product` out of every combo. Returns what changed, or None.

    {'removed_from': [combo names], 'switched_off': [combo names]}
    """
    lines = list(ProductComboItem.objects.filter(product=product).select_related('combo'))
    if not lines:
        return None

    removed_from, switched_off = [], []
    for line in lines:
        combo = line.combo
        # "Was on sale" includes a combo that is off only because an EARLIER
        # switched-off product already took a line out of it — otherwise the
        # second product to leave would forget the combo had ever been live.
        was_active = combo.is_active or DetachedComboLine.objects.filter(
            combo=combo, combo_was_active=True).exists()
        DetachedComboLine.objects.update_or_create(
            combo=combo, variant_id=line.variant_id,
            defaults={'product': product, 'quantity': line.quantity,
                      'combo_was_active': was_active},
        )
        if combo.name not in removed_from:
            removed_from.append(combo.name)
        if combo.is_active and combo.name not in switched_off:
            switched_off.append(combo.name)

    combo_ids = {line.combo_id for line in lines}
    ProductComboItem.objects.filter(pk__in=[line.pk for line in lines]).delete()
    # .update(), not save(): ProductCombo.save() runs full_clean(), and a bundle
    # whose selling price now exceeds its (smaller) MRP would refuse to save —
    # which would in turn refuse to let the PRODUCT be switched off.
    ProductCombo.objects.filter(pk__in=combo_ids, is_active=True).update(is_active=False)
    _bust_caches()
    logger.info("Product %s switched off: removed from combos %s; switched off %s",
                product.pk, removed_from, switched_off)
    return {'removed_from': removed_from, 'switched_off': switched_off}


def reattach_product_to_combos(product):
    """Put `product` back into the combos it was taken out of. Returns what
    changed, or None.

    {'restored_to': [combo names], 'switched_on': [combo names]}
    """
    remembered = list(DetachedComboLine.objects.filter(product=product)
                      .select_related('combo', 'variant'))
    if not remembered:
        return None

    restored_to, candidates = [], {}
    for record in remembered:
        if not record.variant.is_active:
            # The size was retired while the product was off. Keep the record:
            # it comes back if the size and the product are both restored.
            continue
        combo = record.combo
        if not ProductComboItem.objects.filter(combo=combo, variant=record.variant).exists():
            ProductComboItem.objects.create(
                combo=combo, product=product, variant=record.variant,
                quantity=record.quantity)
        if combo.name not in restored_to:
            restored_to.append(combo.name)
        if record.combo_was_active:
            candidates[combo.pk] = combo
        record.delete()

    switched_on = []
    for combo in candidates.values():
        # Back on sale only if it is whole again and still simply "off": not
        # sent to the Recycle Bin since, and no other switched-off product
        # still missing from it.
        combo.refresh_from_db()
        if combo.is_active or combo.deactivated_at is not None:
            continue
        still_missing = DetachedComboLine.objects.filter(combo=combo)
        if still_missing.exists():
            # Hand the "we switched this off" fact to the lines still out, so
            # the LAST product to return is the one that switches it back on.
            still_missing.update(combo_was_active=True)
            continue
        ProductCombo.objects.filter(pk=combo.pk).update(is_active=True)
        switched_on.append(combo.name)

    if not restored_to:
        return None
    _bust_caches()
    logger.info("Product %s switched on: restored to combos %s; switched on %s",
                product.pk, restored_to, switched_on)
    return {'restored_to': restored_to, 'switched_on': switched_on}


def forget_detached_lines(combo):
    """An admin has saved this combo by hand, so its remembered lines no longer
    describe what it should contain. Drop them: restoring a product later must
    not push a line back into a bundle the owner has since re-defined."""
    DetachedComboLine.objects.filter(combo=combo).delete()


def waiting_on(combo):
    """Names of switched-off products this combo is currently missing."""
    return list(DetachedComboLine.objects.filter(combo=combo)
                .values_list('product__name', flat=True).distinct())
