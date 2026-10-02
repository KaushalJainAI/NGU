from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from products.models import Product, ProductCombo

# How many reviews the home page testimonials strip shows, and therefore the
# most an admin may flag at once. The strip always renders this many: flagged
# reviews first, topped up with the best recent ones so it is never sparse.
MAX_FEATURED_REVIEWS = 3


class Review(models.Model):
    """Product/Combo Review Model"""
    ITEM_TYPE_CHOICES = [
        ('product', 'Product'),
        ('combo', 'Combo'),
    ]
    
    # Item type and references
    item_type = models.CharField(max_length=10, choices=ITEM_TYPE_CHOICES, default='product')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews', null=True, blank=True)
    combo = models.ForeignKey(ProductCombo, on_delete=models.CASCADE, related_name='reviews', null=True, blank=True)
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    # Optional: the storefront form presents the title as optional and only
    # requires a rating + comment. Without blank=True the serializer inherited
    # required=True and every title-less submission 400'd on a field the
    # customer was told they could skip.
    title = models.CharField(max_length=200, blank=True, default='')
    comment = models.TextField(blank=True, default='')
    is_verified_purchase = models.BooleanField(default=False)
    # Admin moderation: hidden reviews stay in the DB (and the customer can
    # still see their own) but are excluded from public product pages.
    is_hidden = models.BooleanField(default=False)
    # Homepage placement, chosen by an admin. At most MAX_FEATURED_REVIEWS may
    # be set at once (enforced in the API, not the DB — a partial unique
    # constraint can't express "at most N rows"). A hidden review is never
    # rendered even if flagged, so moderation always wins over placement.
    is_featured = models.BooleanField(
        default=False,
        help_text="Show this review in the home page testimonials strip.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        # User can only review each product/combo once
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product'],
                condition=models.Q(item_type='product'),
                name='unique_product_review_per_user'
            ),
            models.UniqueConstraint(
                fields=['user', 'combo'],
                condition=models.Q(item_type='combo'),
                name='unique_combo_review_per_user'
            ),
        ]

    def __str__(self):
        item_name = self.product.name if self.product else (self.combo.name if self.combo else 'Unknown')
        return f"{self.user.email} - {item_name} - {self.rating}★"
    
    @property
    def item_name(self):
        if self.item_type == 'product' and self.product:
            return self.product.name
        elif self.item_type == 'combo' and self.combo:
            return self.combo.name
        return 'Unknown'
