from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.db.models import Sum, Avg, Count
from django.core.files.base import ContentFile
from spices_backend.validators import validate_file_size, validate_image_extension
from PIL import Image
import io
import os


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
        """Get combos for this section, limited by max_products - OPTIMIZED"""
        return self.combos.filter(
            is_active=True
        ).only(
            'id', 'name', 'slug', 'title', 'image', 'price', 'discount_price',
            'badge', 'weight', 'unit', 'is_featured'
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
        validators=[validate_file_size, validate_image_extension]
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

    # Inventory
    stock = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
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
        validators=[validate_file_size, validate_image_extension]
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
                'discount_price': 'Discount price must be less than regular price.'
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
                'discount_price': 'Discount price must be less than regular price.'
            })

    def save(self, *args, **kwargs):
        if not self.slug:
            weight_part = f"-{self.formatted_weight}" if self.weight else ""
            self.slug = _generate_unique_slug(
                type(self), slugify(f"{self.product.name}{weight_part}"),
                fallback="variant", current_pk=self.pk)
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
        validators=[validate_file_size, validate_image_extension]
    )
    alt_text = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product.name} - Image"


class ProductCombo(models.Model):
    """Model to represent a combo/bundle of multiple products"""
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
    # Tax rate (GST %) applied to this combo at checkout. Defaults to 5%.
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='GST percentage charged on this combo (e.g. 5 for 5%, 0 for exempt).'
    )
    image = models.ImageField(
        upload_to='combos/',
        blank=True, 
        null=True,
        validators=[validate_file_size, validate_image_extension]
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

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_featured', '-created_at']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_active', '-created_at']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate discount price is less than regular price"""
        if self.discount_price and self.price and self.discount_price >= self.price:
            raise ValidationError({
                'discount_price': 'Discount price must be less than regular price.'
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
    def final_price(self):
        """Returns final price after discount if applicable"""
        return self.discount_price if self.discount_price else self.price

    @property
    def discount_percentage(self):
        """Calculate discount percentage"""
        if self.discount_price and self.discount_price < self.price:
            return round(((self.price - self.discount_price) / self.price) * 100)
        return 0

    @property
    def total_original_price(self):
        """Sum of original prices of products in the combo"""
        total = self.productcomboitem_set.aggregate(
            total=Sum(models.F('product__price') * models.F('quantity'))
        )['total']
        return total or 0

    @property
    def total_weight(self):
        """Concat weights of products in the combo"""
        # Formatted string like "250g, 500g"
        weights = []
        for product in self.products.all():
            if product.weight and product.unit:
                # Format to remove trailing zeros if it's an integer
                w = float(product.weight)
                if w.is_integer():
                    w = int(w)
                weights.append(f"{w}{product.unit}")
        return ', '.join(weights) if weights else ''
    
    @property
    def display_title(self):
        """Returns custom title if set, otherwise returns name"""
        return self.title if self.title else self.name


class ProductComboItem(models.Model):
    """Intermediate model for combo items with quantity"""
    combo = models.ForeignKey(ProductCombo, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)  # Direct reference
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = ('combo', 'product')

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in {self.combo.name}"


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
