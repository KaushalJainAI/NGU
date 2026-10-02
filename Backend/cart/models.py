from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import (
    Sum, F, Case, When, DecimalField, Value, OuterRef, Subquery,
)
from django.db.models.functions import Coalesce
from products.models import Product, ProductCombo, ProductComboItem, ProductVariant

_MONEY = DecimalField(max_digits=12, decimal_places=2)


def combo_mrp_subquery(combo_ref='combo'):
    """Correlated subquery giving a combo's MRP, for use in cart aggregates.

    `ProductCombo.price` is a Python property (the sum of its component sizes),
    so it cannot appear in an `F()` — but `Cart.total_price` deliberately does
    its sum in the database. This is the same figure expressed in SQL.
    """
    totals = (
        ProductComboItem.objects
        .filter(combo=OuterRef(combo_ref))
        .values('combo')
        .annotate(total=Sum(F('variant__price') * F('quantity')))
        .values('total')
    )
    return Coalesce(
        Subquery(totals, output_field=_MONEY),
        Value(Decimal('0'), output_field=_MONEY),
        output_field=_MONEY,
    )


class Cart(models.Model):
    """Shopping Cart Model"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='cart',
        primary_key=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart - {self.user.email}"

    @property
    def total_price(self):
        """Calculate total price of all items in cart - OPTIMIZED with DB aggregation.
        Product lines price off their selected variant when one is set, falling
        back to the legacy Product price for any variant-less rows."""
        result = self.items.annotate(
            item_price=Case(
                When(
                    item_type='product', variant__isnull=False,
                    then=Coalesce(F('variant__discount_price'), F('variant__price'))
                ),
                When(
                    item_type='product',
                    then=Coalesce(F('product__discount_price'), F('product__price'))
                ),
                When(
                    # A combo has no `price` column — its MRP is derived from
                    # its components (see combo_mrp_subquery), and it sells for
                    # `discount_price` when the admin set one.
                    item_type='combo',
                    then=Coalesce(F('combo__discount_price'), combo_mrp_subquery())
                ),
                default=Value(0),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).aggregate(
            total=Sum(F('item_price') * F('quantity'), output_field=DecimalField())
        )
        return result['total'] or 0

    @property
    def total_items(self):
        """Calculate total number of items in cart - OPTIMIZED with DB aggregation"""
        result = self.items.aggregate(total=Sum('quantity'))
        return result['total'] or 0


class CartItem(models.Model):
    """Individual items in the shopping cart"""
    ITEM_TYPE_CHOICES = [
        ('product', 'Product'),
        ('combo', 'Combo'),
    ]
    
    cart = models.ForeignKey(
        Cart, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    # The specific packaging/size chosen for a product line. Kept nullable for
    # combo rows and for backward compatibility; for product rows it is the unit
    # of sale and is always populated by the cart views (defaulting to the
    # product's default variant when the client doesn't specify one).
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
    )
    combo = models.ForeignKey(
        ProductCombo,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    item_type = models.CharField(
        max_length=10, 
        choices=ITEM_TYPE_CHOICES, 
        default='product'
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        # Improved constraints to prevent any duplicate cart items
        constraints = [
            # Ensure only one line per (cart, variant) for product items, so the
            # same spice in different sizes can coexist as separate cart lines.
            models.UniqueConstraint(
                fields=['cart', 'variant'],
                condition=models.Q(item_type='product', variant__isnull=False),
                name='unique_cart_variant'
            ),
            # Ensure only one combo per cart (when item_type is 'combo')
            models.UniqueConstraint(
                fields=['cart', 'combo'],
                condition=models.Q(item_type='combo', combo__isnull=False),
                name='unique_cart_combo'
            ),
            # Ensure quantity is always positive
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name='positive_quantity'
            ),
            # Ensure either product or combo is set, but not both
            models.CheckConstraint(
                condition=(
                    models.Q(item_type='product', product__isnull=False, combo__isnull=True) |
                    models.Q(item_type='combo', combo__isnull=False, product__isnull=True)
                ),
                name='valid_item_type_reference'
            ),
        ]
        # Add indexes for better query performance
        indexes = [
            models.Index(fields=['cart', 'item_type']),
            models.Index(fields=['cart', 'product']),
            models.Index(fields=['cart', 'variant']),
            models.Index(fields=['cart', 'combo']),
        ]

    def __str__(self):
        item = self.product if self.item_type == 'product' else self.combo
        return f"{item.name if item else 'Unknown'} x {self.quantity}"

    @property
    def unit_price(self):
        """Price per unit for this line, preferring the selected variant."""
        if self.item_type == 'product':
            if self.variant:
                return self.variant.final_price
            if self.product:
                return self.product.final_price
        elif self.item_type == 'combo' and self.combo:
            return self.combo.final_price if hasattr(self.combo, 'final_price') else self.combo.price
        return 0

    @property
    def available_stock(self):
        """Stock available for this line (variant stock when set)."""
        if self.item_type == 'product':
            if self.variant:
                return self.variant.stock
            if self.product:
                return self.product.stock
        elif self.item_type == 'combo' and self.combo:
            # How many can be built from the components' stock.
            return self.combo.available_stock
        return 0

    @property
    def subtotal(self):
        """Calculate subtotal for this cart item"""
        if self.item_type == 'product' and (self.variant or self.product):
            return self.unit_price * self.quantity
        elif self.item_type == 'combo' and self.combo:
            price = self.combo.final_price if hasattr(self.combo, 'final_price') else self.combo.price
            return price * self.quantity
        return 0

    def clean(self):
        """Validate that either product or combo is set based on item_type"""
        errors = {}
        
        # Check item_type specific validations
        if self.item_type == 'product':
            if not self.product:
                errors['product'] = 'Product must be set when item_type is product'
            if self.combo:
                errors['combo'] = 'Combo should be null when item_type is product'
        
        elif self.item_type == 'combo':
            if not self.combo:
                errors['combo'] = 'Combo must be set when item_type is combo'
            if self.product:
                errors['product'] = 'Product should be null when item_type is combo'
        
        # Validate quantity
        if self.quantity and self.quantity < 1:
            errors['quantity'] = 'Quantity must be at least 1'
        
        # Check stock availability (variant stock when a variant is selected)
        if self.item_type == 'product' and (self.variant or self.product):
            avail = self.available_stock
            if self.quantity > avail:
                name = self.product.name if self.product else (self.variant.product.name if self.variant else 'item')
                errors['quantity'] = f'Only {avail} units available for {name}'
        
        elif self.item_type == 'combo' and self.combo:
            combo_stock = self.combo.available_stock
            if self.quantity > combo_stock:
                errors['quantity'] = f'Only {combo_stock} units available for {self.combo.name}'
        
        if errors:
            raise ValidationError(errors)
    



class Favorite(models.Model):
    """User's favorite products"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='favorites'
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Prevent duplicate favorites
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product'],
                name='unique_user_favorite'
            )
        ]
        # Add index for faster lookups
        indexes = [
            models.Index(fields=['user', 'added_at']),
        ]
        ordering = ['-added_at']
        verbose_name = 'Favorite'
        verbose_name_plural = 'Favorites'

    def __str__(self):
        return f"{self.user.email} - {self.product.name}"
