from decimal import Decimal

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.core.files.base import ContentFile
from spices_backend.validators import validate_file_size, validate_image_extension, validate_image_content
from .hsn import validate_hsn_code
from PIL import Image
import io
import os


def _clear_deactivated_at_if_active(instance, save_kwargs):
    """Keep ``deactivated_at`` consistent with ``is_active`` on every save.

    An active row must never carry a deactivation stamp, or the Recycle Bin
    purge job would delete a product/combo that the admin has restored. Call
    this from ``save()`` just before ``super().save()``: when the instance is
    active it nulls ``deactivated_at`` and, if the caller passed a limited
    ``update_fields`` (e.g. the restore PATCH), extends it so the cleared value
    is actually written. Soft-deletion sets the stamp explicitly in the viewset.
    """
    if instance.is_active and instance.deactivated_at is not None:
        instance.deactivated_at = None
        update_fields = save_kwargs.get('update_fields')
        if update_fields is not None and 'deactivated_at' not in update_fields:
            save_kwargs['update_fields'] = list(update_fields) + ['deactivated_at']


def _generate_unique_slug(model_cls, base_slug, *, fallback, current_pk=None):
    """Return a slug unique within ``model_cls`` using bounded ``exists()`` queries.

    Replaces the previous exception-driven retry loops that ran ``full_clean()`` /
    ``save()`` inside a nested ``transaction.atomic()`` and caught
    ValidationError/IntegrityError to bump the slug. That pattern could deadlock on
    a constraint-validation savepoint when executed inside an outer transaction
    (e.g. a request or test wrapped in ``atomic()``); computing the slug with plain
    SELECTs before any write avoids the nested savepoint entirely.
    """
    base = base_slug or fallback
    slug = base
    counter = 1
    qs = model_cls.objects.all()
    if current_pk is not None:
        qs = qs.exclude(pk=current_pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class ProductSection(models.Model):
    """Model for organizing products into homepage sections"""
    SECTION_TYPE_CHOICES = [
        ('special', 'Our Specials'),
        ('new', 'Newly Launched'),
        ('trending', 'Trending Now'),
        ('bestseller', 'Best Sellers'),
        ('seasonal', 'Seasonal'),
        ('custom', 'Custom Section'),
    ]
    
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    section_type = models.CharField(
        max_length=20,
        choices=SECTION_TYPE_CHOICES,
        default='custom'
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text='Icon class name (e.g., fa-star)')
    display_order = models.PositiveIntegerField(
        default=0,
        help_text='Order in which sections appear on homepage'
    )
    max_products = models.PositiveIntegerField(
        default=12,
        validators=[MinValueValidator(1)],
        help_text='Maximum number of products to display in this section'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'Product Section'
        verbose_name_plural = 'Product Sections'
        indexes = [
            models.Index(fields=['is_active', 'display_order']),
            models.Index(fields=['section_type', 'is_active']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_products(self):
        """Get products for this section in the admin-defined order, limited by
        max_products. Ordered by the through model's position.

        NB: no .only() here — deferring fields hides modeltranslation's
        per-language columns (name_hi, ...), which would make translated
        content silently fall back to English."""
        return self.products.filter(
            is_active=True
        ).select_related('category').prefetch_related('variants').order_by(
            'productsectionplacement__position', 'productsectionplacement__id'
        )[:self.max_products]
    
    def get_combos(self):
        """Get combos for this section, limited by max_products.

        `with_mrp()` because the serializer renders the MRP strike-through, and
        without the annotation each combo would fire its own aggregate query.
        No `.only()`: the MRP is derived from components rather than stored, so
        deferring columns no longer buys the round-trip it used to, and a
        deferred field that the serializer touches costs a query per row.
        """
        return self.combos.filter(
            is_active=True
        ).with_mrp().prefetch_related(
            'productcomboitem_set__variant'
        )[:self.max_products]


class Category(models.Model):
    """Product Category Model for organizing spices"""
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to='categories/', 
        blank=True, 
        null=True,
        validators=[validate_file_size, validate_image_extension, validate_image_content]
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _generate_unique_slug(
                type(self), slugify(self.name), fallback="category", current_pk=self.pk)
        self.full_clean()
        super().save(*args, **kwargs)


class Product(models.Model):
    """Product Model specifically designed for spices"""
    SPICE_FORM_CHOICES = [
        ('whole', 'Whole'),
        ('powder', 'Powder'),
        ('crushed', 'Crushed'),
        ('mixed', 'Mixed/Blend'),
    ]
    
    UNIT_CHOICES = [
        ('g', 'Grams'),
        ('kg', 'Kilograms'),
        ('ml', 'Milliliters'),
        ('l', 'Liters'),
        ('pc', 'Piece'),
        ('box', 'Box'),
        ('pack', 'Pack'),
        ('combo', 'Combo'),
    ]
    
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products'
    )
    # Additional categories this product should also be listed under. `category`
    # stays the single canonical one (breadcrumb, schema.org); these are extra
    # shelves. E.g. Chat Masala is a blended masala AND a sprinkler/seasoning.
    extra_categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name='extra_products',
        help_text='Also list this product under these categories.',
    )
    description = models.TextField()
    spice_form = models.CharField(
        max_length=20, 
        choices=SPICE_FORM_CHOICES,
        help_text='Form of the spice (whole, powder, etc.)'
    )
    
    # Pricing
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)]
    )
    # Tax rate (GST %) applied to this product at checkout. Defaults to 5% for
    # all products; some goods are tax-exempt (e.g. papad / papad katran => 0).
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='GST percentage charged on this product (e.g. 5 for 5%, 0 for exempt items like papad).'
    )
    # HSN classification. `tax_rate` says WHAT we charge; this says WHY, and a
    # GST return needs both — GSTR-1 Table 12 is an HSN-wise summary and no
    # amount of rate data can reconstruct it (5% spans 0904, 0909, 0910, …).
    # Deliberately nullable-as-blank rather than defaulted: an unclassified
    # product must LOOK unclassified, because a plausible wrong code is far more
    # expensive than an obviously missing one. See products/hsn.py.
    hsn_code = models.CharField(
        max_length=8,
        blank=True,
        default='',
        validators=[validate_hsn_code],
        help_text='HSN code (4, 6 or 8 digits) for GST returns. Leave blank if not yet classified.'
    )

    # Inventory
    stock = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text='Warn the admin (dashboard + daily digest) when stock falls to or below this.'
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Numerical value of the weight'
    )
    unit = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=UNIT_CHOICES,
        help_text='e.g., pc, box, kg'
    )
    
    # Product Details
    origin_country = models.CharField(max_length=100, blank=True)
    organic = models.BooleanField(default=False)
    shelf_life = models.CharField(
        max_length=100, 
        blank=True, 
        help_text='e.g., 12 months, 24 months'
    )
    ingredients = models.TextField(blank=True)
    # How-to-use / recipe text shown in a dropdown on the product page.
    # Translatable (see products/translation.py) like description/ingredients.
    recipe = models.TextField(blank=True)
    # Nutritional information table, shown in a dropdown on the product page.
    # Stored as an ordered dict of {label: value} pairs, e.g.
    # {"serving_size": "100g", "protein": "11.5g"}. Values are plain data (not
    # translated); the row LABELS are localised in the frontend i18n files.
    nutrition = models.JSONField(null=True, blank=True)

    # Media
    image = models.ImageField(
        upload_to='products/',
        validators=[validate_file_size, validate_image_extension, validate_image_content]
    )
    thumbnail = models.ImageField(
        upload_to='products/thumbnails/',
        blank=True,
        null=True,
        editable=False
    )
    
    # Flags
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    badge = models.CharField(max_length=20, blank=True)
    
    # Section placement - ManyToMany relationship.
    # Uses an explicit through model so admins can order products WITHIN a
    # section (ProductSectionPlacement.position), not just pick which appear.
    sections = models.ManyToManyField(
        ProductSection,
        through='ProductSectionPlacement',
        related_name='products',
        blank=True,
        help_text='Homepage sections where this product appears'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # When this product was soft-deleted (moved to the admin Recycle Bin, i.e.
    # is_active flipped to False). NULL while active. Stamped on soft-delete and
    # cleared on restore; the recycle-bin purge job deletes rows whose
    # deactivated_at is older than the retention window. See purge_recycle_bin.
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['category', '-created_at']),
            models.Index(fields=['is_featured', '-created_at']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_active', 'stock']),
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['spice_form', 'is_active']),
            models.Index(fields=['is_active', 'deactivated_at']),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(stock__gte=0), name='stock_non_negative'),
        ]

    def __str__(self):
        return f"{self.name} - {self.weight}"

    def clean(self):
        """Validate discount price is less than regular price"""
        if self.discount_price and self.price and self.discount_price >= self.price:
            raise ValidationError({
                'discount_price': 'Discounted price must be less than regular price.'
            })

    # Slug this instance was loaded from the DB with, so save() can detect a
    # rename without re-querying. None for never-saved instances.
    _loaded_slug = None

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        if 'slug' in field_names:
            instance._loaded_slug = values[field_names.index('slug')]
        return instance

    def save(self, *args, **kwargs):
        if not self.slug:
            weight_part = f"-{self.weight}" if self.weight else ""
            self.slug = _generate_unique_slug(
                type(self), slugify(f"{self.name}{weight_part}"),
                fallback="product", current_pk=self.pk)

        # Run validation
        self.full_clean()

        # Generate thumbnail if image exists
        if self.image:
            self.generate_thumbnail()

        # A restored (re-activated) product must not carry a stale deactivation
        # stamp, or the purge job would delete it. Clearing it here covers every
        # reactivation path (admin edit form PATCH, restore action, Django admin).
        _clear_deactivated_at_if_active(self, kwargs)

        super().save(*args, **kwargs)

        # A slug change orphans every indexed/bookmarked URL for this product,
        # so keep the outgoing slug resolvable. _loaded_slug is captured in
        # from_db, so this costs no extra query on the common save path (stock
        # decrements during checkout run inside a transaction — an extra SELECT
        # here widens the lock window for concurrent orders).
        previous_slug = self._loaded_slug
        if previous_slug and previous_slug != self.slug:
            ProductSlugAlias.objects.update_or_create(
                slug=previous_slug, defaults={'product': self})
            # The new slug may itself be a retired alias; a slug can be
            # canonical or an alias, never both.
            ProductSlugAlias.objects.filter(slug=self.slug).delete()
        self._loaded_slug = self.slug

    def generate_thumbnail(self):
        """Generates a 300x300 thumbnail using Pillow"""
        if not self.image:
            return

        try:
            # Open the image using Pillow
            img = Image.open(self.image)
            img = img.convert('RGB')
            
            # Resize while maintaining aspect ratio
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            
            # Save the thumbnail to a BytesIO object
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            
            # Create a ContentFile from the BytesIO object
            filename = os.path.basename(self.image.name)
            thumb_filename = f"thumb_{filename}"
            
            # Save the thumbnail to the field
            self.thumbnail.save(
                thumb_filename, 
                ContentFile(thumb_io.getvalue()), 
                save=False
            )
        except Exception as e:
            print(f"Error generating thumbnail for product {self.name}: {e}")

    @property
    def final_price(self):
        """Returns the final price after discount if applicable"""
        return self.discount_price if self.discount_price else self.price

    @property
    def discount_percentage(self):
        """Calculate discount percentage"""
        if self.discount_price and self.discount_price < self.price:
            return round(((self.price - self.discount_price) / self.price) * 100)
        return 0

    @property
    def in_stock(self):
        """Check if product is in stock"""
        return self.stock > 0

    @property
    def formatted_weight(self):
        """Returns weight with unit, formatted to remove trailing zeros (e.g., '250g')"""
        if self.weight and self.unit:
            w = float(self.weight)
            if w.is_integer():
                w = int(w)
            return f"{w}{self.unit}"
        return str(self.weight or "")


class ProductSlugAlias(models.Model):
    """A slug a Product used to be reachable at.

    Renaming a product rewrites its slug, which 404s every link already in the
    wild (search index, shared URL, bookmark). Product.save() records the
    outgoing slug here and the detail endpoint falls back to it, so old links
    keep resolving to the right product instead of dying.
    """
    slug = models.SlugField(max_length=220, unique=True)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='slug_aliases'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Product slug aliases'

    def __str__(self):
        return f"{self.slug} -> {self.product.slug}"


class ProductVariant(models.Model):
    """A specific packaging/size of a Product (e.g. 100g, 500g, 1kg).

    Lets one spice be offered in multiple packagings. Each variant carries its
    own price / discount / stock / weight; the parent Product holds the shared
    content (name, description, image, category, etc.).

    ADDITIVE ROLLOUT: the legacy per-size fields on Product
    (price/discount_price/stock/weight/unit) are intentionally KEPT for now.
    Every existing Product is backfilled with one is_default variant copying
    those values, so nothing downstream breaks until later phases move
    cart/orders/serializers onto variants.
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants'
    )

    # Per-size attributes (mirror the legacy Product fields)
    weight = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Numerical value of the weight'
    )
    unit = models.CharField(
        max_length=50, blank=True, null=True, choices=Product.UNIT_CHOICES,
        help_text='e.g., g, kg, pc'
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    discount_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(0)]
    )
    stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text='Alert the admin when this size falls to or below this stock level.'
    )

    sku = models.CharField(max_length=64, blank=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    is_default = models.BooleanField(
        default=False,
        help_text='The size shown by default on listings and the product page'
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(
        default=0, help_text='Order of this size on the product page (lower first)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product', 'display_order', 'weight']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock__gte=0), name='variant_stock_non_negative'
            ),
            # At most one default size per product (partial unique index — Postgres).
            models.UniqueConstraint(
                fields=['product'],
                condition=models.Q(is_default=True),
                name='one_default_variant_per_product',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.formatted_weight}"

    def clean(self):
        if self.discount_price and self.price and self.discount_price >= self.price:
            raise ValidationError({
                'discount_price': 'Discounted price must be less than regular price.'
            })

    def save(self, *args, **kwargs):
        if not self.slug:
            weight_part = f"-{self.formatted_weight}" if self.weight else ""
            self.slug = _generate_unique_slug(
                type(self), slugify(f"{self.product.name}{weight_part}"),
                fallback="variant", current_pk=self.pk)
        # Claiming default demotes the incumbent. Every product is auto-given a
        # default size (see signals.auto_update_product_on_save), so without
        # this any second is_default=True row — from the admin, a script, a
        # fixture — would collide with one_default_variant_per_product. Done
        # with .update() so it neither recurses nor touches updated_at.
        #
        # Demotion and the save itself are ONE transaction: demoting first and
        # then failing to write this row (slug collision, a DB-level check)
        # would leave the product with no default at all, and no post_save fires
        # to repair it.
        with transaction.atomic():
            if self.is_default and self.product_id:
                (ProductVariant.objects
                 .filter(product_id=self.product_id, is_default=True)
                 .exclude(pk=self.pk)
                 .update(is_default=False))
            super().save(*args, **kwargs)

    @property
    def final_price(self):
        return self.discount_price if self.discount_price else self.price

    @property
    def discount_percentage(self):
        if self.discount_price and self.discount_price < self.price:
            return round(((self.price - self.discount_price) / self.price) * 100)
        return 0

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def formatted_weight(self):
        """Weight with unit, trailing zeros stripped (e.g. '250g', '1kg')."""
        if self.weight and self.unit:
            w = float(self.weight)
            if w.is_integer():
                w = int(w)
            return f"{w}{self.unit}"
        return str(self.weight or "")


def default_variant_for(product_id, active_only=True):
    """The variant that represents a product when no size is specified.

    Single source of truth for "which size does this product mean by default" —
    used by the legacy-field mirror, the combo write path, and the bulk editor,
    so they can never disagree. Prefers the flagged default, then the smallest
    (cheapest packaging) one. Returns None if the product has no such variant.
    """
    qs = ProductVariant.objects.filter(product_id=product_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.filter(is_default=True).first() or qs.order_by('weight').first()


def ensure_default_variant_for(product):
    """Like ``default_variant_for``, but never returns None for a real product:
    if it has no variant at all, one is minted from its legacy price/stock
    fields — the same shape migrations 0018 and 0038 create.

    Products can still be created without a variant (the product write path
    doesn't make one, and the cart falls back to the legacy columns), so any
    caller that *requires* a size — combos above all — has to be able to
    materialise one rather than fail on a legitimate product.

    A product whose sizes are all DEACTIVATED gets its existing (inactive) size
    back, never a fresh one. This runs on every product save, so minting here
    would resurrect a size the admin deliberately switched off — priced from the
    legacy mirror columns, which by then can be badly stale. Callers that need a
    *sellable* size check `is_active` themselves (see ProductComboSerializer).
    """
    existing = default_variant_for(product.pk)
    if existing is not None:
        return existing
    retired = default_variant_for(product.pk, active_only=False)
    if retired is not None:
        return retired
    return ProductVariant.objects.create(
        product=product,
        weight=product.weight,
        unit=product.unit,
        price=product.price,
        discount_price=product.discount_price,
        stock=product.stock,
        is_default=True,
        is_active=True,
    )


class ProductSectionPlacement(models.Model):
    """Through model for Product.sections: lets an admin order products within
    a homepage section. Reuses the original auto-M2M join table (db_table +
    db_column below) so the conversion preserves existing placements."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    section = models.ForeignKey(
        ProductSection, on_delete=models.CASCADE, db_column='productsection_id'
    )
    position = models.PositiveIntegerField(
        default=0,
        help_text='Order of this product within the section (lower shows first)'
    )

    class Meta:
        db_table = 'products_product_sections'
        ordering = ['position']
        unique_together = (('product', 'section'),)

    def __str__(self):
        return f"{self.product.name} in {self.section.name} @ {self.position}"


class ProductImage(models.Model):
    """Additional images for products (gallery)"""
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='images'
    )
    image = models.ImageField(
        upload_to='products/gallery/',
        validators=[validate_file_size, validate_image_extension, validate_image_content]
    )
    alt_text = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product.name} - Image"


class ProductComboQuerySet(models.QuerySet):
    """Adds `with_mrp()`, which pushes the derived MRP into the database.

    `ProductCombo.price` is a Python property summing the components, so without
    this every serialized combo costs one extra aggregate query, and the API
    could not sort or filter by price at all. The annotation lands in `_mrp`,
    which `total_original_price` picks up.

    Deliberately a correlated Subquery rather than a plain `annotate(Sum(...))`:
    a Sum over the reverse FK adds a JOIN, and any caller that also joins
    (filtering by `sections`, a M2M) would multiply the component rows and
    silently inflate the MRP.
    """

    def with_mrp(self):
        totals = (
            ProductComboItem.objects
            .filter(combo=models.OuterRef('pk'))
            .values('combo')
            .annotate(total=Sum(models.F('variant__price') * models.F('quantity')))
            .values('total')
        )
        money = models.DecimalField(max_digits=12, decimal_places=2)
        return self.annotate(
            _mrp=Coalesce(
                models.Subquery(totals, output_field=money),
                Value(Decimal('0'), output_field=money),
                output_field=money,
            )
        )


class ProductCombo(models.Model):
    """A bundle of specific product SIZES sold as one unit.

    Pricing model: the MRP is DERIVED from the components (`price` property) and
    the admin only types `discount_price`, the amount the bundle actually sells
    for. GST is likewise per component, at each one's own product rate — the
    combo has no rate of its own. The split of the charged amount back across
    components lives in `orders.pricing.allocate_combo_components`.
    """
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)
    
    # Custom titles for combo display
    title = models.CharField(
        max_length=300, 
        blank=True,
        help_text='Custom display title for the combo (e.g., "Ultimate Spice Collection - Save 30%")'
    )
    subtitle = models.CharField(
        max_length=300, 
        blank=True,
        help_text='Subtitle or tagline for the combo'
    )
    
    products = models.ManyToManyField(
        Product,  # Direct reference since Product is defined above
        through='ProductComboItem',
        related_name='combos'
    )
    # NOTE: there is no `price` COLUMN. A combo's MRP is by definition the sum of
    # its components' à-la-carte prices, so it is derived (see the `price`
    # property below) and can never drift from the sizes actually bundled.
    # `discount_price` — the admin-entered amount the bundle actually sells for —
    # is the only price a human types.
    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)]
    )
    # NOTE: there is no `tax_rate` COLUMN either. GST is charged per COMPONENT at
    # its own product's rate — a bundle mixing 0% papad with 5% spices used to be
    # billed at one hand-entered blended rate, which is wrong on a tax invoice.
    # See orders.pricing.allocate_combo_components.
    image = models.ImageField(
        upload_to='combos/',
        blank=True, 
        null=True,
        validators=[validate_file_size, validate_image_extension, validate_image_content]
    )
    thumbnail = models.ImageField(
        upload_to='combos/thumbnails/',
        blank=True,
        null=True,
        editable=False
    )
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    badge = models.CharField(max_length=20, blank=True)
    # A combo has no stock of its own — how many can still be sold is limited by
    # its scarcest component. Alert the admin when that buildable count falls to
    # or below this.
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text='Alert the admin when the number of combos that can still be '
                  'built (limited by the scarcest component) falls to or below this.'
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Numerical value of the weight'
    )
    unit = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=Product.UNIT_CHOICES,
        help_text='e.g., pc, box, kg'
    )
    
    # Section placement - ManyToMany relationship
    sections = models.ManyToManyField(
        ProductSection,
        related_name='combos',
        blank=True,
        help_text='Homepage sections where this combo appears'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # See Product.deactivated_at — soft-delete timestamp driving the Recycle Bin
    # purge. NULL while active; stamped on soft-delete, cleared on restore.
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = ProductComboQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_featured', '-created_at']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['is_active', 'deactivated_at']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate the selling price does not EXCEED the MRP.

        At or below is fine: a bundle priced exactly at the sum of its parts is
        a legitimate curation with no discount, and since the MRP is derived,
        re-pricing a component can move the two together at any time. Only a
        selling price ABOVE the MRP is wrong — that is a "combo" that costs more
        than buying the same sizes separately.

        MRP is derived from the components, so a combo being created for the
        first time has none yet — the serializer writes its ProductComboItem
        rows only after the combo row exists. A zero MRP therefore means
        "components not attached yet", not "free": skip the check rather than
        reject every new combo. Any later save re-runs it for real.
        """
        mrp = self.price
        if self.discount_price and mrp and self.discount_price > mrp:
            raise ValidationError({
                'discount_price': 'Selling price cannot exceed the combo MRP '
                                  f'(₹{mrp}, the sum of its components).'
            })

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _generate_unique_slug(
                type(self), slugify(self.name), fallback="combo", current_pk=self.pk)

        # Run validation
        self.full_clean()

        # Generate thumbnail if image exists
        if self.image:
            self.generate_thumbnail()

        # Restored combos must shed their deactivation stamp (see Product.save).
        _clear_deactivated_at_if_active(self, kwargs)

        super().save(*args, **kwargs)

    def generate_thumbnail(self):
        """Generates a 300x300 thumbnail using Pillow"""
        if not self.image:
            return

        try:
            img = Image.open(self.image)
            img = img.convert('RGB')
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            
            filename = os.path.basename(self.image.name)
            thumb_filename = f"thumb_{filename}"
            
            self.thumbnail.save(
                thumb_filename, 
                ContentFile(thumb_io.getvalue()), 
                save=False
            )
        except Exception as e:
            print(f"Error generating thumbnail for combo {self.name}: {e}")

    @property
    def price(self):
        """MRP — DERIVED, never stored.

        A combo's list price is by definition what its components cost bought
        separately, so it is computed from them rather than typed by an admin
        and left to rot when a component is re-priced. Identical to
        `total_original_price`; both names are kept because the storefront
        already renders one as the strike-through and the other as the label.
        """
        return self.total_original_price

    @property
    def final_price(self):
        """What one combo actually sells for: the admin's `discount_price`, or
        the full MRP if the bundle carries no saving."""
        return self.discount_price if self.discount_price else self.price

    @property
    def discount_percentage(self):
        """Calculate discount percentage"""
        mrp = self.price
        if self.discount_price and mrp and self.discount_price < mrp:
            return round(((mrp - self.discount_price) / mrp) * 100)
        return 0

    @property
    def total_original_price(self):
        """Sum of the à-la-carte prices of the exact SIZES in this combo — what
        the customer would pay buying the components separately. This is the
        combo's MRP (see `price`).

        Prefers the `_mrp` annotation that `with_mrp()` attaches, because
        evaluating the aggregate per row would fire one query per combo on
        every list endpoint.
        """
        annotated = getattr(self, '_mrp', None)
        if annotated is not None:
            return Decimal(str(annotated))
        # An unsaved combo has no pk to hang the reverse relation off, and by
        # definition no components yet. `clean()` runs in exactly that state on
        # the first save, so this has to answer rather than raise.
        if self.pk is None:
            return Decimal('0')
        total = self.productcomboitem_set.aggregate(
            total=Sum(models.F('variant__price') * models.F('quantity'))
        )['total']
        return total or Decimal('0')

    @property
    def total_weight(self):
        """Concat the weights of the exact sizes in the combo, e.g. '250g, 500g'."""
        # .all() so the list endpoint's `productcomboitem_set__variant` prefetch
        # is reused — no N+1 on list.
        weights = [
            item.variant.formatted_weight
            for item in self.productcomboitem_set.all()
            if item.variant_id and item.variant.formatted_weight
        ]
        return ', '.join(weights) if weights else ''
    
    @property
    def display_title(self):
        """Returns custom title if set, otherwise returns name"""
        return self.title if self.title else self.name

    @property
    def available_stock(self):
        """How many of this combo can still be built, limited by the scarcest
        component SIZE (min of each variant's stock // its required quantity).
        An inactive component size makes the combo unbuildable. Returns 0 for an
        empty combo."""
        # .all() (not .select_related) so the list endpoint's existing
        # `productcomboitem_set__variant` prefetch is reused — no N+1 on list.
        items = list(self.productcomboitem_set.all())
        if not items:
            return 0
        counts = []
        for item in items:
            variant = item.variant
            if variant is None or not variant.is_active or not item.quantity:
                return 0
            counts.append(variant.stock // item.quantity)
        return min(counts)


class ProductComboItem(models.Model):
    """One component line of a combo: a specific SIZE of a product, times a qty.

    The unit of sale is the VARIANT, not the product — a combo means "1 x 500g
    Turmeric", never "1 x Turmeric, whichever size is default today". All price
    and stock math reads `variant`; `product` is retained only as the target of
    the `ProductCombo.products` M2M (so `combo.products` / `product.combos` keep
    working) and is kept in sync with `variant.product` on save.

    `variant` is PROTECTed: a size that a combo is built from cannot be deleted
    out from under it. See ProductVariantViewSet.destroy.
    """
    combo = models.ForeignKey(ProductCombo, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)  # M2M through target
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.PROTECT, related_name='combo_items',
        help_text='The exact packaging/size of the product this combo consumes.'
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        # Keyed on the variant, so one combo may hold two different sizes of the
        # same spice (e.g. 100g + 500g Turmeric) as separate lines.
        unique_together = ('combo', 'variant')

    def clean(self):
        if self.variant_id and self.product_id and self.variant.product_id != self.product_id:
            raise ValidationError({
                'variant': 'Selected size does not belong to the selected product.'
            })

    def save(self, *args, **kwargs):
        # Callers that know only the product (Django admin inlines, fixtures,
        # data migrations) get the product's default size resolved for them —
        # the same choice migration 0038 made for pre-existing rows. The API
        # write path asks for the size explicitly; this is the fallback, not the
        # normal route.
        if not self.variant_id and self.product_id:
            # Bind to a local: reading back an unset non-nullable FK raises
            # RelatedObjectDoesNotExist rather than returning None.
            self.variant = ensure_default_variant_for(self.product)
        # `product` is derived — never let it drift from the variant it mirrors.
        if self.variant_id:
            self.product_id = self.variant.product_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.variant} in {self.combo.name}"


class ProductSearchKB(models.Model):
    """LLM-generated search synonyms for products"""
    product = models.OneToOneField(
        Product, 
        on_delete=models.CASCADE, 
        related_name='search_kb'
    )
    synonyms = models.JSONField(default=list)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [models.Index(fields=['last_updated'])]
        verbose_name = 'Product Search KB'
        verbose_name_plural = 'Product Search KBs'
    
    def get_synonyms_list(self):
        return self.synonyms if isinstance(self.synonyms, list) else []


class ProductComboSearchKB(models.Model):
    """LLM-generated search synonyms for combos"""
    combo = models.OneToOneField(
        ProductCombo, 
        on_delete=models.CASCADE, 
        related_name='search_kb'
    )
    synonyms = models.JSONField(default=list)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [models.Index(fields=['last_updated'])]
        verbose_name = 'Combo Search KB'
        verbose_name_plural = 'Combo Search KBs'
    
    def get_synonyms_list(self):
        return self.synonyms if isinstance(self.synonyms, list) else []
