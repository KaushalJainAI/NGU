# signals.py - Search KB updates + Cache invalidation
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

from .models import (
    Product, ProductCombo, ProductSearchKB, ProductComboSearchKB, Category,
    ProductSection, ProductVariant, default_variant_for,
    ensure_default_variant_for,
)
from .recommendations import SpiceSearchEngine
from .utils import run_in_background
from .cache import (
    invalidate_product_cache,
    invalidate_category_cache,
    invalidate_combo_cache,
    invalidate_search_cache,
    invalidate_by_prefix,
    CACHE_PREFIX_SECTIONS,
)

logger = logging.getLogger(__name__)
search_engine = SpiceSearchEngine()


# ============== PRODUCT SIGNALS ==============

@receiver(post_save, sender=Product)
def auto_update_product_on_save(sender, instance, created, **kwargs):
    """Guarantee a sellable size, then update search KB and invalidate cache."""
    # INVARIANT: every product has at least one variant. Price and stock live on
    # the variant — a product without one can be listed but never bought, and
    # can't be put in a combo. The product write path doesn't create a size, so
    # this is where the invariant is enforced for every product that appears,
    # from any route (API, Django admin, shell).
    #
    # NOT during `loaddata`: a fixture carries its own variant rows, and minting
    # one here mid-deserialization would collide with the row about to be loaded
    # (or leave a phantom size the fixture never described).
    #
    # Gated on a single covering-index `.exists()` rather than calling
    # ensure_default_variant_for() outright: this fires on EVERY product save
    # (the bulk editor loops over hundreds), and the full resolve costs two
    # queries that fetch whole rows only to discard them. The invariant only
    # needs enforcing when there is genuinely no size at all.
    if not kwargs.get('raw', False):
        if not ProductVariant.objects.filter(product_id=instance.pk).exists():
            ensure_default_variant_for(instance)

    # Update search KB asynchronously in background
    if instance.is_active and instance.stock > 0:
        run_in_background(search_engine.a_ensure_search_kb, instance)

    # Invalidate caches
    invalidate_product_cache()
    invalidate_search_cache()
    logger.info(f"Product cache invalidated for: {instance.name}")


@receiver(post_delete, sender=Product)
def invalidate_product_cache_on_delete(sender, instance, **kwargs):
    """Invalidate product and section caches when a product is deleted."""
    invalidate_product_cache()
    invalidate_search_cache()
    logger.info(f"Product cache invalidated (deleted): {instance.name}")


# ============== VARIANT SIGNALS ==============
# A variant carries the sellable price/stock for a product, so any change must
# bust the product list/section caches that embed variant data.

@receiver(post_save, sender=ProductVariant)
@receiver(post_delete, sender=ProductVariant)
def on_variant_change(sender, instance, **kwargs):
    # A product must always have exactly one active default size, or listings
    # and the combo/cart fallbacks have nothing to resolve to. Repair first, so
    # the mirror below copies from the right row.
    _ensure_default_variant(instance.product_id)
    # Keep the legacy Product fields in sync with the default variant so list
    # cards / cart fallbacks stay correct, then bust the caches.
    _mirror_default_variant_to_product(instance.product_id)
    invalidate_product_cache()
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)
    # A variant's stock/price feeds every combo built from that size
    # (available_stock, total_original_price), so combo payloads go stale too.
    invalidate_combo_cache()
    logger.info(f"Product cache invalidated (variant change): product {instance.product_id}")


def _ensure_default_variant(product_id):
    """Guarantee at most-one / at least-one active default variant.

    Deactivating or unflagging the default would otherwise leave a product with
    sizes but no default — listings then fall back to stale legacy columns.
    Uses .update() to avoid re-entering this signal.
    """
    actives = ProductVariant.objects.filter(product_id=product_id, is_active=True)
    default_ids = list(actives.filter(is_default=True).values_list('pk', flat=True))
    if len(default_ids) == 1:
        return
    if len(default_ids) > 1:
        # Keep the lowest pk, demote the rest (belt-and-braces behind the
        # one_default_variant_per_product constraint).
        ProductVariant.objects.filter(pk__in=default_ids[1:]).update(is_default=False)
        return
    # No active default — promote the smallest active size, if any.
    promote = actives.order_by('weight', 'pk').first()
    if promote is not None:
        # Clear any INACTIVE row still holding the flag first; the partial unique
        # index covers is_default alone, so two rows would collide.
        ProductVariant.objects.filter(
            product_id=product_id, is_default=True
        ).exclude(pk=promote.pk).update(is_default=False)
        ProductVariant.objects.filter(pk=promote.pk).update(is_default=True)


def _mirror_default_variant_to_product(product_id):
    """Copy the product's default (or smallest active) variant's price/stock/
    weight onto the legacy Product fields. Uses .update() to avoid recursion.

    The legacy columns are a DISPLAY MIRROR only — never a write target. Anything
    that changes what a customer pays or what stock exists must write the
    variant; this then follows. See products/bulk_views.py.
    """
    default = default_variant_for(product_id)
    if default is not None:
        Product.objects.filter(pk=product_id).update(
            price=default.price,
            discount_price=default.discount_price,
            weight=default.weight,
            unit=default.unit,
            stock=default.stock,
        )


# ============== COMBO SIGNALS ==============

@receiver(post_save, sender=ProductCombo)
def auto_update_combo_on_save(sender, instance, created, **kwargs):
    """Update search KB and invalidate cache when combo is saved."""
    # Update search KB asynchronously in background
    if instance.is_active:
        run_in_background(search_engine.a_ensure_search_kb, instance)
    
    # Invalidate caches
    invalidate_combo_cache()
    invalidate_search_cache()
    logger.info(f"Combo cache invalidated for: {instance.name}")


@receiver(post_delete, sender=ProductCombo)
def invalidate_combo_cache_on_delete(sender, instance, **kwargs):
    """Invalidate combo and section caches when a combo is deleted."""
    invalidate_combo_cache()
    invalidate_search_cache()
    logger.info(f"Combo cache invalidated (deleted): {instance.name}")


# ============== CATEGORY SIGNALS ==============

@receiver(post_save, sender=Category)
def refresh_category_on_save(sender, instance, **kwargs):
    """Refresh products and invalidate cache when category changes."""
    # Refresh product search KBs asynchronously in background
    for product in instance.products.filter(is_active=True):
        run_in_background(search_engine.a_ensure_search_kb, product)
    
    # Invalidate caches
    invalidate_category_cache()
    invalidate_product_cache()  # Products depend on categories
    invalidate_search_cache()
    logger.info(f"Category cache invalidated for: {instance.name}")


@receiver(post_delete, sender=Category)
def invalidate_category_cache_on_delete(sender, instance, **kwargs):
    """Invalidate category cache when a category is deleted."""
    invalidate_category_cache()
    invalidate_product_cache()
    logger.info(f"Category cache invalidated (deleted): {instance.name}")


# ============== SEARCH KB SIGNALS ==============
# Background LLM regeneration saves KB rows after the product/combo signals
# above have already fired — the corpus must invalidate when the KB lands.

@receiver(post_save, sender=ProductSearchKB)
@receiver(post_delete, sender=ProductSearchKB)
@receiver(post_save, sender=ProductComboSearchKB)
@receiver(post_delete, sender=ProductComboSearchKB)
def invalidate_search_cache_on_kb_change(sender, instance, **kwargs):
    invalidate_search_cache()


# ============== SECTION SIGNALS ==============

@receiver(post_save, sender=ProductSection)
def invalidate_section_cache_on_save(sender, instance, **kwargs):
    """Invalidate section cache when a section is saved."""
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)
    logger.info(f"Section cache invalidated for: {instance.name}")


@receiver(post_delete, sender=ProductSection)
def invalidate_section_cache_on_delete(sender, instance, **kwargs):
    """Invalidate section cache when a section is deleted."""
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)
    logger.info(f"Section cache invalidated (deleted): {instance.name}")
