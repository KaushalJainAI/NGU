"""One place that answers "can this be bought?".

Something being switched off, retired or sold out used to be re-derived by every
surface that cared (cart, checkout, search, dashboard...), and each derived it a
little differently. Everything now asks here, so the rules cannot drift apart.

The public never gets a COUNT from these helpers' callers (rule AP8/S12) — only
booleans. The counts are for the server's own checks and for staff.
"""
from django.db.models import Exists, F, OuterRef, Q

from .models import ProductVariant

# Reason codes for `line_problem`, in the order they are checked.
PRODUCT_OFF = 'product_off'
SIZE_RETIRED = 'size_retired'
COMBO_OFF = 'combo_off'
COMBO_UNAVAILABLE = 'combo_unavailable'
OUT_OF_STOCK = 'out_of_stock'
INSUFFICIENT_STOCK = 'insufficient_stock'


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def in_stock_products(queryset):
    """Keep products with at least one ACTIVE size that has stock.

    A subquery rather than a join, so a product with three stocked sizes is still
    one row. A legacy product with no size rows at all falls back to its own stock
    column — the same rule as `product_has_stock`.
    """
    has_stocked_size = Exists(ProductVariant.objects.filter(
        product=OuterRef('pk'), is_active=True, stock__gt=0,
    ))
    has_any_size = Exists(ProductVariant.objects.filter(product=OuterRef('pk')))
    return queryset.filter(has_stocked_size | (~has_any_size & Q(stock__gt=0)))


def product_has_stock(product):
    """The same rule for one product instance.

    Reads `product.variants.all()` so an existing `prefetch_related('variants')`
    is reused (no query per product on a list). A legacy product with no size rows
    at all falls back to its own stock column.
    """
    variants = list(product.variants.all())
    if not variants:
        return (product.stock or 0) > 0
    return any(v.is_active and v.stock > 0 for v in variants)


# ---------------------------------------------------------------------------
# Combos
# ---------------------------------------------------------------------------

def combo_can_be_built(combo, quantity=1):
    """True when the combo is on sale and every component can cover `quantity`.

    `available_stock` already returns 0 for a retired size, a switched-off
    component product, or an empty combo.
    """
    return bool(combo.is_active) and combo.available_stock >= quantity


# ---------------------------------------------------------------------------
# Cart lines
# ---------------------------------------------------------------------------

def line_max_quantity(cart_item):
    """How many of this line can be bought right now (0 when none)."""
    if cart_item.item_type == 'combo':
        combo = cart_item.combo
        return combo.available_stock if combo else 0
    if cart_item.variant_id:
        return cart_item.variant.stock
    product = cart_item.product
    return product.stock if product else 0


def line_problem(cart_item):
    """Why this cart line cannot be bought as it stands — or None when it can.

    First match wins:
      product_off, size_retired, combo_off, combo_unavailable,
      out_of_stock, insufficient_stock
    """
    if cart_item.item_type == 'combo':
        combo = cart_item.combo
        if combo is None or not combo.is_active:
            return COMBO_OFF
        if combo.available_stock == 0:
            return COMBO_UNAVAILABLE
    else:
        product = cart_item.product
        if product is None or not product.is_active:
            return PRODUCT_OFF
        if cart_item.variant_id and not cart_item.variant.is_active:
            return SIZE_RETIRED
    available = line_max_quantity(cart_item)
    if available <= 0:
        return OUT_OF_STOCK
    if available < cart_item.quantity:
        return INSUFFICIENT_STOCK
    return None


# ---------------------------------------------------------------------------
# Low stock (staff reporting)
# ---------------------------------------------------------------------------

def _live_sizes():
    return (ProductVariant.objects
            .filter(is_active=True, product__is_active=True)
            .select_related('product'))


def low_stock_sizes():
    """Sizes at or below their PRODUCT's alert level, lowest stock first.

    The product form's "Low-stock alert level" is the only level the owner can set,
    so it applies to each of the product's sizes. A retired size or a switched-off
    product is not reported.
    """
    return (_live_sizes()
            .filter(stock__lte=F('product__low_stock_threshold'))
            .order_by('stock', 'product__name', 'display_order'))


def out_of_stock_sizes():
    return _live_sizes().filter(stock__lte=0)
