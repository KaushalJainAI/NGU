from decimal import Decimal

from rest_framework import serializers
from .models import Cart, CartItem, Favorite
from products.serializers import ProductListSerializer
from admin_panel.serializers import CouponSerializer
from orders.pricing import (
    allocate_combo_components, blended_rate, combo_line_tax, extract_tax,
    group_tax_by_rate, shipping_tax_for, tax_rate_for,
)
from spices_backend.limits import (
    SHIPPING_CHARGE, SHIPPING_TAX_RATE, FREE_SHIPPING_THRESHOLD, DEFAULT_TAX_RATE,
)


# ---------------------------------------------------------------------------
# Cart Item Serializer (polymorphic: product OR combo)
# ---------------------------------------------------------------------------

class CartItemResponseSerializer(serializers.Serializer):
    """
    Serializer for a single cart item returned in the cart list response.
    Handles both 'product' and 'combo' item types safely.
    All field access uses SerializerMethodField so that missing/null
    attributes never raise AttributeError.
    """
    id = serializers.SerializerMethodField()
    item_type = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    originalPrice = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    quantity = serializers.IntegerField()
    subtotal = serializers.SerializerMethodField()
    stock = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    variant_id = serializers.SerializerMethodField()
    variant_slug = serializers.SerializerMethodField()
    weight = serializers.SerializerMethodField()
    tax_rate = serializers.SerializerMethodField()

    def _get_item(self, obj):
        """Return the underlying Product or ProductCombo instance."""
        item_type = getattr(obj, 'item_type', 'product') or 'product'
        if item_type == 'combo':
            return obj.combo
        return obj.product

    def get_variant_id(self, obj):
        variant = getattr(obj, 'variant', None)
        return variant.id if variant else None

    def get_variant_slug(self, obj):
        variant = getattr(obj, 'variant', None)
        return variant.slug if variant else None

    def get_weight(self, obj):
        variant = getattr(obj, 'variant', None)
        if variant:
            return variant.formatted_weight
        item = self._get_item(obj)
        if item and getattr(item, 'weight', None) and getattr(item, 'unit', None):
            w = float(item.weight)
            if w.is_integer():
                w = int(w)
            return f"{w}{item.unit}"
        return None

    def get_tax_rate(self, obj):
        """GST rate (%) for this line.

        Product lines carry their product's rate. A COMBO has none of its own —
        each component is taxed at its own product's rate — so it reports the
        blended effective rate implied by the split. That keeps the field
        populated for display without pretending a mixed supply has one rate;
        the per-slab truth is in the cart summary's `tax_breakdown`.
        """
        item_type = getattr(obj, 'item_type', 'product') or 'product'
        if item_type == 'combo' and obj.combo:
            return float(blended_rate(obj.subtotal, combo_line_tax(obj.combo, obj.subtotal)))
        item = self._get_item(obj)
        return float(getattr(item, 'tax_rate', DEFAULT_TAX_RATE) or 0) if item else 0.0

    def get_id(self, obj):
        item = self._get_item(obj)
        return str(item.id) if item else None

    def get_item_type(self, obj):
        return getattr(obj, 'item_type', 'product') or 'product'

    def get_name(self, obj):
        item = self._get_item(obj)
        return getattr(item, 'name', '') if item else ''

    def get_image(self, obj):
        item = self._get_item(obj)
        if not item or not getattr(item, 'image', None):
            return ''
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(item.image.url)
        return item.image.url

    def get_price(self, obj):
        variant = getattr(obj, 'variant', None)
        if getattr(obj, 'item_type', 'product') == 'product' and variant:
            return float(variant.final_price)
        item = self._get_item(obj)
        if not item:
            return 0
        if hasattr(item, 'final_price'):
            return float(item.final_price)
        return float(getattr(item, 'price', 0))

    def get_originalPrice(self, obj):
        """
        The original (non-discounted) price (variant price for product lines).
        """
        variant = getattr(obj, 'variant', None)
        if getattr(obj, 'item_type', 'product') == 'product' and variant:
            return float(variant.price)
        item = self._get_item(obj)
        if not item:
            return 0
        return float(getattr(item, 'price', 0))

    def get_badge(self, obj):
        item = self._get_item(obj)
        return getattr(item, 'badge', None) if item else None

    def get_subtotal(self, obj):
        return float(getattr(obj, 'subtotal', 0))

    def get_stock(self, obj):
        item_type = getattr(obj, 'item_type', 'product') or 'product'
        variant = getattr(obj, 'variant', None)
        if item_type == 'product' and variant:
            return variant.stock
        item = self._get_item(obj)
        if not item:
            return 0
        if item_type == 'product':
            return getattr(item, 'stock', 0)
        return getattr(item, 'stock', 999)  # combos default to 999

    def get_in_stock(self, obj):
        item_type = getattr(obj, 'item_type', 'product') or 'product'
        variant = getattr(obj, 'variant', None)
        if item_type == 'product' and variant:
            return variant.stock > 0
        item = self._get_item(obj)
        if not item:
            return False
        if item_type == 'product' and hasattr(item, 'stock'):
            return item.stock > 0
        return True


# ---------------------------------------------------------------------------
# Cart Response Serializer (wraps items + summary)
# ---------------------------------------------------------------------------

class CartResponseSerializer(serializers.Serializer):
    """
    Top-level cart response.  Accepts a dict with 'cart' (Cart instance)
    and 'request' in the serializer context.
    """
    success = serializers.BooleanField(default=True)
    items = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    def get_items(self, obj):
        cart = obj['cart']
        cart_items = cart.items.select_related(
            'product', 'product__category', 'combo', 'variant', 'variant__product'
        ).all()
        return CartItemResponseSerializer(
            cart_items,
            many=True,
            context=self.context,
        ).data

    def get_summary(self, obj):
        cart = obj['cart']
        subtotal = float(cart.total_price)
        # Prices are GST-INCLUSIVE, so this is the tax already contained in the
        # subtotal — reported for disclosure, never added to the total. Papad
        # lines (tax_rate=0) contribute nothing; everything else defaults to 5%.
        tax = Decimal('0.00')
        lines = []
        for ci in cart.items.select_related('product', 'combo', 'variant').all():
            if ci.item_type == 'combo' and ci.combo:
                # A combo is a mixed supply — each component is taxed at its own
                # product's rate, so it contributes one breakdown line PER
                # COMPONENT rather than one blended line. Same allocator the
                # order write path uses, so the cart's quoted GST and the placed
                # order's agree to the paisa.
                for row in allocate_combo_components(ci.combo, ci.subtotal, ci.quantity):
                    tax += row['tax']
                    lines.append((row['allocated'], row['tax_rate']))
                continue
            rate = tax_rate_for(ci.product)
            tax += extract_tax(ci.subtotal, rate)
            lines.append((ci.subtotal, rate))
        tax = float(tax)
        # Per-slab breakdown so the cart can show WHAT was taxed, not just how
        # much — a cart mixing papad (0%) with spices (5%) is the normal case.
        discount = 0
        shipping = 0 if subtotal >= float(FREE_SHIPPING_THRESHOLD) or subtotal == 0 else float(SHIPPING_CHARGE)
        # Delivery is priced NET and taxed on top (SAC 9968, 18%) — the opposite
        # convention to goods, whose MRP already contains their GST. So this one
        # slab is a real addend to the total, and it joins the breakdown as its
        # own row rather than being merged into a goods slab.
        shipping_tax = float(shipping_tax_for(Decimal(str(shipping))))
        if shipping > 0:
            lines.append((Decimal(str(shipping + shipping_tax)), SHIPPING_TAX_RATE))
        # Per-slab breakdown so the cart can show WHAT was taxed, not just how
        # much — a cart mixing papad (0%) with spices (5%) is the normal case.
        # Built AFTER shipping is appended so the delivery slab appears too.
        tax_breakdown = group_tax_by_rate(lines)
        # `tax` (goods) is a component of `subtotal` and does NOT appear in this
        # sum; `shipping_tax` sits outside it and does.
        total = round(subtotal + shipping + shipping_tax - discount, 2)
        return {
            'subtotal': subtotal,
            'tax': tax,
            'tax_breakdown': tax_breakdown,
            # Net of the GST contained in it — the "goods value" the customer is
            # actually paying for, shown above the GST lines on the breakup.
            'taxable_value': round(subtotal - tax, 2),
            'shipping': shipping,
            'shipping_tax': shipping_tax,
            # Everything the customer pays as GST: inside the goods price plus on
            # the delivery fee. The cart must quote this or it under-states the
            # GST the invoice will show.
            'total_tax': round(tax + shipping_tax, 2),
            'free_shipping_threshold': float(FREE_SHIPPING_THRESHOLD),
            'discount': discount,
            'total': total,
        }


# ---------------------------------------------------------------------------
# Favorite Item Serializer
# ---------------------------------------------------------------------------

class FavoriteItemSerializer(serializers.Serializer):
    """
    Serializer for a single favorite item.
    All fields use safe getattr so that missing model attributes never crash.
    """
    id = serializers.SerializerMethodField()
    product_id = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    weight = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    added_at = serializers.SerializerMethodField()

    def get_id(self, obj):
        product = getattr(obj, 'product', None)
        return product.id if product else None

    def get_product_id(self, obj):
        product = getattr(obj, 'product', None)
        return product.id if product else None

    def get_name(self, obj):
        product = getattr(obj, 'product', None)
        return getattr(product, 'name', '') if product else ''

    def get_image(self, obj):
        product = getattr(obj, 'product', None)
        if not product or not getattr(product, 'image', None):
            return ''
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(product.image.url)
        return product.image.url

    def get_price(self, obj):
        product = getattr(obj, 'product', None)
        if not product:
            return 0
        if hasattr(product, 'final_price'):
            return float(product.final_price)
        return float(getattr(product, 'price', 0))

    def get_original_price(self, obj):
        """Original (non-discounted) price = product.price"""
        product = getattr(obj, 'product', None)
        if not product:
            return None
        price = getattr(product, 'price', None)
        return float(price) if price is not None else None

    def get_weight(self, obj):
        product = getattr(obj, 'product', None)
        return getattr(product, 'weight', None) if product else None

    def get_badge(self, obj):
        product = getattr(obj, 'product', None)
        return getattr(product, 'badge', None) if product else None

    def get_added_at(self, obj):
        added_at = getattr(obj, 'added_at', None)
        return added_at.isoformat() if added_at else None


# ---------------------------------------------------------------------------
# Legacy serializers (kept for backward compatibility)
# ---------------------------------------------------------------------------

class CartItemSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    product_id = serializers.IntegerField(write_only=True)
    subtotal = serializers.ReadOnlyField()

    class Meta:
        model = CartItem
        fields = ['id', 'product', 'product_id', 'quantity', 'subtotal', 'created_at', 'item_type']


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_price = serializers.ReadOnlyField()
    total_items = serializers.ReadOnlyField()

    class Meta:
        model = Cart
        fields = ['id', 'items', 'total_price', 'total_items', 'created_at', 'updated_at']


class ValidateCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, required=True)


class FavoriteSerializer(serializers.ModelSerializer):
    """Legacy serializer kept for backward compatibility.
    Uses product.price for originalPrice since Product has no original_price field."""
    id = serializers.CharField(source='product.id')
    name = serializers.CharField(source='product.name')
    image = serializers.ImageField(source='product.image', allow_null=True)
    price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2)
    originalPrice = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, required=False)
    weight = serializers.CharField(source='product.weight', allow_null=True, required=False)
    badge = serializers.CharField(source='product.badge', allow_null=True, required=False)

    class Meta:
        model = Favorite
        fields = ('id', 'name', 'image', 'price', 'originalPrice', 'weight', 'badge')
