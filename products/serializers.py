import json
from decimal import Decimal

from rest_framework import serializers
from django.db.models import Avg, Count
from .models import (
    Category, Product, ProductImage, ProductCombo, ProductComboItem,
    ProductSection, ProductVariant,
    default_variant_for as _default_variant_for,
    ensure_default_variant_for as _ensure_default_variant_for,
)


class ProductVariantSerializer(serializers.ModelSerializer):
    """A single packaging/size of a product (read-only nested view)."""
    final_price = serializers.ReadOnlyField()
    discount_percentage = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    formatted_weight = serializers.ReadOnlyField()

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'slug', 'weight', 'unit', 'formatted_weight',
            'price', 'discount_price', 'final_price', 'discount_percentage',
            'stock', 'in_stock', 'low_stock_threshold', 'sku', 'is_default',
            'is_active', 'display_order',
        ]
        read_only_fields = fields


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    """Writable serializer for the /product-variants/ admin CRUD endpoint."""
    final_price = serializers.ReadOnlyField()
    discount_percentage = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    formatted_weight = serializers.ReadOnlyField()
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'product_name', 'slug', 'weight', 'unit',
            'formatted_weight', 'price', 'discount_price', 'final_price',
            'discount_percentage', 'stock', 'in_stock', 'low_stock_threshold',
            'sku', 'is_default', 'is_active', 'display_order',
        ]
        read_only_fields = ['slug', 'formatted_weight', 'final_price',
                            'discount_percentage', 'in_stock', 'product_name']

    def validate(self, data):
        price = data.get('price', getattr(self.instance, 'price', None))
        discount = data.get('discount_price', getattr(self.instance, 'discount_price', None))
        if discount is not None and price is not None and discount >= price:
            raise serializers.ValidationError({
                'discount_price': 'Discounted price must be less than the regular price.'
            })
        return data


# ---------------------------------------------------------------------------
# Lightweight serializers for the /products/sections/ endpoint
# ---------------------------------------------------------------------------

class SectionProductSerializer(serializers.Serializer):
    """Lightweight product representation for homepage sections.
    Uses SerializerMethodField for safe attribute access."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    weight = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    is_featured = serializers.BooleanField()
    variant_count = serializers.SerializerMethodField()

    def get_variant_count(self, obj):
        variants = getattr(obj, 'variants', None)
        if variants is None:
            return 0
        return sum(1 for v in variants.all() if v.is_active)

    def get_image(self, obj):
        if not getattr(obj, 'image', None):
            return ''
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url

    def get_thumbnail(self, obj):
        if not getattr(obj, 'thumbnail', None):
            return self.get_image(obj) # Fallback to full image
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail.url

    def get_price(self, obj):
        if hasattr(obj, 'final_price'):
            return float(obj.final_price)
        return float(getattr(obj, 'price', 0))

    def get_original_price(self, obj):
        return float(getattr(obj, 'price', 0))

    def get_discount(self, obj):
        return getattr(obj, 'discount_percentage', 0)

    def get_weight(self, obj):
        return getattr(obj, 'weight', None)

    def get_badge(self, obj):
        return getattr(obj, 'badge', '') or ''


class SectionComboSerializer(serializers.Serializer):
    """Lightweight combo representation for homepage sections."""
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    slug = serializers.CharField()
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    is_featured = serializers.BooleanField()

    def get_name(self, obj):
        return getattr(obj, 'display_title', None) or getattr(obj, 'name', '')

    def get_image(self, obj):
        if not getattr(obj, 'image', None):
            return ''
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url

    def get_thumbnail(self, obj):
        if not getattr(obj, 'thumbnail', None):
            return self.get_image(obj)
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail.url

    def get_price(self, obj):
        if hasattr(obj, 'final_price'):
            return float(obj.final_price)
        return float(getattr(obj, 'price', 0))

    def get_original_price(self, obj):
        return float(getattr(obj, 'price', 0))

    def get_discount(self, obj):
        return getattr(obj, 'discount_percentage', 0)

    def get_badge(self, obj):
        return getattr(obj, 'badge', '') or 'Combo'


class HomepageSectionSerializer(serializers.Serializer):
    """Full section with nested products and combos for /products/sections/"""
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    section_type = serializers.CharField()
    description = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()
    combos = serializers.SerializerMethodField()

    def get_description(self, obj):
        return getattr(obj, 'description', '')

    def get_products(self, obj):
        products = list(obj.get_products())
        if not products:
            # No curated placements yet -> fill the row with arbitrary active
            # products so it's never empty, still capped at the section's
            # max_products. Rotated by section id so different empty sections
            # don't all show the same products.
            products = self._fallback_products(obj)
        return SectionProductSerializer(
            products,
            many=True,
            context=self.context,
        ).data

    def _fallback_products(self, obj):
        # No .only() — it would defer modeltranslation's per-language columns
        # and make translated names fall back to English.
        all_products = list(
            Product.objects.filter(is_active=True)
            .select_related('category')
            .order_by('-is_featured', 'id')
        )
        if not all_products:
            return []
        limit = obj.max_products or 12
        start = (obj.id or 0) % len(all_products)
        rotated = all_products[start:] + all_products[:start]
        return rotated[:limit]

    def get_combos(self, obj):
        combos_qs = obj.get_combos()
        return SectionComboSerializer(
            combos_qs,
            many=True,
            context=self.context,
        ).data


# ---------------------------------------------------------------------------
# Serializers for the search / recommendation engine
# ---------------------------------------------------------------------------

class SearchProductSerializer(serializers.Serializer):
    """Safe serializer for search result products."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    type = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    spice_form = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    weight = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    is_featured = serializers.BooleanField()

    def get_type(self, obj):
        return 'product'

    def get_category(self, obj):
        cat = getattr(obj, 'category', None)
        return getattr(cat, 'name', '') if cat else ''

    def get_spice_form(self, obj):
        return getattr(obj, 'spice_form', '')

    def get_price(self, obj):
        if hasattr(obj, 'final_price'):
            return float(obj.final_price)
        return float(getattr(obj, 'price', 0))

    def get_original_price(self, obj):
        return float(getattr(obj, 'price', 0))

    def get_discount(self, obj):
        return getattr(obj, 'discount_percentage', 0)

    def get_weight(self, obj):
        return getattr(obj, 'weight', None)

    def get_unit(self, obj):
        return getattr(obj, 'unit', None)

    def get_image(self, obj):
        img = getattr(obj, 'image', None)
        if img:
            return img.url
        return None

    def get_thumbnail(self, obj):
        thumb = getattr(obj, 'thumbnail', None)
        if thumb:
            return thumb.url
        return self.get_image(obj)

    def get_in_stock(self, obj):
        return getattr(obj, 'stock', 0)


class SearchComboSerializer(serializers.Serializer):
    """Safe serializer for search result combos."""
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    slug = serializers.CharField()
    type = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    def get_type(self, obj):
        return 'combo'

    def get_name(self, obj):
        return getattr(obj, 'display_title', None) or getattr(obj, 'name', '')

    def get_price(self, obj):
        if hasattr(obj, 'final_price'):
            return float(obj.final_price)
        return float(getattr(obj, 'price', 0))

    def get_original_price(self, obj):
        return float(getattr(obj, 'price', 0))

    def get_discount(self, obj):
        return getattr(obj, 'discount_percentage', 0)

    def get_products_count(self, obj):
        return obj.products.count() if hasattr(obj, 'products') else 0

    def get_image(self, obj):
        img = getattr(obj, 'image', None)
        if img:
            return img.url
        return None

    def get_thumbnail(self, obj):
        thumb = getattr(obj, 'thumbnail', None)
        if thumb:
            return thumb.url
        return self.get_image(obj)

    def get_products(self, obj):
        if hasattr(obj, 'products'):
            return [p.name for p in obj.products.all()[:3]]
        return []


class ProductSectionSerializer(serializers.ModelSerializer):
    """Serializer for ProductSection"""
    class Meta:
        model = ProductSection
        fields = [
            'id', 'name', 'slug', 'section_type', 'description', 
            'icon', 'display_order', 'max_products', 'is_active'
        ]
        read_only_fields = ['slug']


class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'image', 'is_active', 'products_count']
        read_only_fields = ['slug']

    def get_products_count(self, obj):
        if hasattr(obj, '_products_count'):
            return obj._products_count
        return obj.products.filter(is_active=True).count()


class ProductImageSerializer(serializers.ModelSerializer):
    # Uploads go straight to Cloudinary (metered), so cap size and restrict the
    # type here — the other two upload paths (order delivery bill, assistant
    # audio) already do the equivalent.
    MAX_IMAGE_BYTES = 5 * 1024 * 1024
    ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}

    class Meta:
        model = ProductImage
        fields = ['id', 'product', 'image', 'alt_text']

    def validate_image(self, value):
        size = getattr(value, 'size', None)
        if size and size > self.MAX_IMAGE_BYTES:
            raise serializers.ValidationError(
                f'Image too large (max {self.MAX_IMAGE_BYTES // (1024 * 1024)} MB).'
            )

        content_type = getattr(value, 'content_type', None)
        if content_type and content_type.lower() not in self.ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError(
                'Unsupported image type. Use JPEG, PNG, WebP or GIF.'
            )
        return value


class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    average_rating = serializers.SerializerMethodField(read_only=True)
    reviews_count = serializers.SerializerMethodField(read_only=True)
    discount_percentage = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    sections = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ProductSection.objects.all(),
        required=False
    )
    section_names = serializers.SerializerMethodField(read_only=True)
    variants = serializers.SerializerMethodField(read_only=True)
    variant_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'category', 'category_name', 'spice_form',
            'price', 'discount_price', 'final_price', 'discount_percentage',
            'tax_rate', 'hsn_code',
            'stock', 'in_stock', 'low_stock_threshold', 'weight', 'unit', 'organic',
            'image', 'thumbnail', 'is_featured',
            'average_rating', 'reviews_count', 'created_at', 'badge', 'is_active',
            'sections', 'section_names', 'variants', 'variant_count'
        ]
        read_only_fields = ['slug', 'created_at']

    def get_section_names(self, obj):
        return [section.name for section in obj.sections.all()]

    def get_variants(self, obj):
        variants = [v for v in obj.variants.all() if v.is_active]
        variants.sort(key=lambda v: (v.display_order, v.weight or 0))
        return ProductVariantSerializer(variants, many=True).data

    def get_variant_count(self, obj):
        return sum(1 for v in obj.variants.all() if v.is_active)
    
    def get_average_rating(self, obj):
        """Get average rating using aggregation to avoid N+1 queries"""
        # Use the annotated value when present (set by the viewset queryset),
        # normalized to match the manual-fallback output exactly.
        if hasattr(obj, '_average_rating'):
            return round(obj._average_rating, 1) if obj._average_rating else 0
        # Fallback to manual calculation
        avg = obj.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0

    def get_reviews_count(self, obj):
        """Get reviews count using aggregation to avoid N+1 queries"""
        # Use the annotated value when present (set by the viewset queryset).
        if hasattr(obj, '_reviews_count'):
            return obj._reviews_count or 0
        # Fallback to manual count
        return obj.reviews.count()


class ProductDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    average_rating = serializers.SerializerMethodField(read_only=True)
    reviews_count = serializers.SerializerMethodField(read_only=True)
    discount_percentage = serializers.ReadOnlyField()
    in_stock = serializers.ReadOnlyField()
    sections = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ProductSection.objects.all(),
        required=False
    )
    section_names = serializers.SerializerMethodField(read_only=True)
    variants = serializers.SerializerMethodField(read_only=True)
    variant_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'category', 'category_name', 'description',
            'spice_form', 'price', 'discount_price', 'final_price',
            'discount_percentage', 'tax_rate', 'hsn_code',
            'stock', 'in_stock', 'low_stock_threshold',
            'weight', 'unit',
            'origin_country', 'organic', 'shelf_life', 'ingredients',
            'recipe', 'nutrition',
            'image', 'thumbnail', 'images', 'is_featured', 'average_rating',
            'reviews_count', 'created_at', 'is_active', 'sections', 'section_names',
            'variants', 'variant_count'
        ]
        read_only_fields = ['slug', 'created_at']

    def get_section_names(self, obj):
        return [section.name for section in obj.sections.all()]

    def get_variants(self, obj):
        variants = [v for v in obj.variants.all() if v.is_active]
        variants.sort(key=lambda v: (v.display_order, v.weight or 0))
        return ProductVariantSerializer(variants, many=True).data

    def get_variant_count(self, obj):
        return sum(1 for v in obj.variants.all() if v.is_active)
    
    def get_average_rating(self, obj):
        """Get average rating using aggregation"""
        if hasattr(obj, '_average_rating'):
            return round(obj._average_rating, 1) if obj._average_rating else 0
        avg = obj.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0

    def get_reviews_count(self, obj):
        """Get reviews count using aggregation"""
        if hasattr(obj, '_reviews_count'):
            return obj._reviews_count or 0
        return obj.reviews.count()
    
    def validate(self, data):
        """Validate discount price"""
        price = data.get('price', getattr(self.instance, 'price', None))
        discount_price = data.get('discount_price')

        if discount_price and price and discount_price >= price:
            raise serializers.ValidationError({
                'discount_price': 'Discounted price must be less than the regular price.'
            })

        return data

    def create(self, validated_data):
        # sections is a M2M through ProductSectionPlacement — pop it and set()
        # explicitly after the product exists, rather than letting DRF's default
        # M2M handling touch the intermediary table implicitly.
        sections = validated_data.pop('sections', None)
        product = super().create(validated_data)
        if sections is not None:
            product.sections.set(sections)
        return product

    def update(self, instance, validated_data):
        # `sections` absent from the payload → leave placements untouched
        # (partial update). Present (even as []) → replace the set, so an admin
        # can clear all section placements from the edit form.
        sections = validated_data.pop('sections', None)
        product = super().update(instance, validated_data)
        if sections is not None:
            product.sections.set(sections)
        return product


class ProductComboItemReadSerializer(serializers.ModelSerializer):
    """For reading combo items: the product for display, the variant for the
    size actually bundled (and the price/stock that come with it)."""
    product = serializers.PrimaryKeyRelatedField(read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_slug = serializers.CharField(source='product.slug', read_only=True)
    product_image = serializers.ImageField(source='product.image', read_only=True)
    product_thumbnail = serializers.ImageField(source='product.thumbnail', read_only=True)
    # The component's à-la-carte price is the VARIANT's price — the legacy
    # Product.price is only a mirror of whichever size happens to be default.
    product_price = serializers.DecimalField(
        source='variant.price',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    variant = serializers.PrimaryKeyRelatedField(read_only=True)
    variant_label = serializers.CharField(source='variant.formatted_weight', read_only=True)
    variant_price = serializers.DecimalField(
        source='variant.price', max_digits=10, decimal_places=2, read_only=True
    )
    variant_stock = serializers.IntegerField(source='variant.stock', read_only=True)
    variant_is_active = serializers.BooleanField(source='variant.is_active', read_only=True)
    quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductComboItem
        fields = [
            'product', 'product_name', 'product_slug',
            'product_image', 'product_thumbnail', 'product_price',
            'variant', 'variant_label', 'variant_price', 'variant_stock',
            'variant_is_active', 'quantity'
        ]


class ProductComboSerializer(serializers.ModelSerializer):
    # Accept items as a JSON string (for FormData) or list
    items = serializers.CharField(write_only=True, required=False, allow_blank=True)
    sections = serializers.PrimaryKeyRelatedField(
        many=True, 
        queryset=ProductSection.objects.all(),
        required=False
    )
    section_names = serializers.SerializerMethodField(read_only=True)
    discount_percentage = serializers.ReadOnlyField()
    display_title = serializers.ReadOnlyField()
    # MRP is DERIVED from the components, so `price` is emitted but never
    # accepted — a client that still posts one is ignored rather than rejected,
    # so old admin builds keep working while they roll forward.
    price = serializers.ReadOnlyField()
    final_price = serializers.ReadOnlyField()
    total_original_price = serializers.ReadOnlyField()
    total_weight = serializers.ReadOnlyField()
    available_stock = serializers.ReadOnlyField()

    class Meta:
        model = ProductCombo
        fields = [
            'id', 'name', 'slug', 'description', 'title', 'subtitle',
            'display_title', 'price', 'discount_price', 'final_price',
            'discount_percentage', 'total_original_price', 'total_weight',
            'low_stock_threshold', 'available_stock',
            'weight', 'unit', 'image', 'thumbnail', 'is_active', 'is_featured', 'badge', 'created_at',
            'items', 'sections', 'section_names'
        ]
        read_only_fields = ['slug', 'created_at']

    def get_section_names(self, obj):
        return [section.name for section in obj.sections.all()]

    def to_representation(self, instance):
        """Override to include items in read operations"""
        data = super().to_representation(instance)
        data['items'] = ProductComboItemReadSerializer(
            instance.productcomboitem_set.all(), 
            many=True
        ).data
        return data

    def _parse_items(self, items_raw):
        """Parse items from JSON string or return as-is if already a list"""
        if items_raw is None or items_raw == '':
            return []
        
        if isinstance(items_raw, list):
            return items_raw
        
        if isinstance(items_raw, str):
            try:
                return json.loads(items_raw)
            except json.JSONDecodeError:
                raise serializers.ValidationError({
                    'items': 'Invalid JSON format for items.'
                })
        
        return []

    def _validate_and_get_items(self, items_data):
        """Validate items and return (variant, quantity) pairs.

        A combo line is a SIZE, so each item should carry `variant`. Payloads
        that only send `product` (pre-variant clients) are still accepted and
        resolved to that product's default active size, so old integrations keep
        working — but the resolved variant is what gets stored.
        """
        if not items_data:
            raise serializers.ValidationError({
                'items': 'At least one product must be added to the combo.'
            })

        validated_items = []
        seen_variant_ids = []

        for item in items_data:
            variant_id = item.get('variant')
            product_id = item.get('product')
            quantity = item.get('quantity', 1)

            if not variant_id and not product_id:
                continue

            if variant_id:
                try:
                    variant_id = int(variant_id)
                except (ValueError, TypeError):
                    raise serializers.ValidationError({
                        'items': f'Invalid size ID: {variant_id}'
                    })
                variant = ProductVariant.objects.select_related('product').filter(
                    pk=variant_id).first()
                if variant is None:
                    raise serializers.ValidationError({
                        'items': f'Size with ID {variant_id} does not exist.'
                    })
                # Guard against a mismatched pair arriving from a stale form.
                if product_id and int(product_id) != variant.product_id:
                    raise serializers.ValidationError({
                        'items': f'Size {variant_id} does not belong to product {product_id}.'
                    })
            else:
                try:
                    product_id = int(product_id)
                except (ValueError, TypeError):
                    raise serializers.ValidationError({
                        'items': f'Invalid product ID: {product_id}'
                    })
                product_obj = Product.objects.filter(pk=product_id).first()
                if product_obj is None:
                    raise serializers.ValidationError({
                        'items': f'Product with ID {product_id} does not exist.'
                    })
                # A product with no variant row yet still has a sellable
                # price/stock in its legacy columns — materialise the size
                # rather than reject a legitimate product.
                variant = _ensure_default_variant_for(product_obj)

            if not variant.is_active:
                raise serializers.ValidationError({
                    'items': f'{variant.product.name} ({variant.formatted_weight}) is not an active size.'
                })

            # The same size twice in one combo is a quantity, not two lines.
            if variant.pk in seen_variant_ids:
                raise serializers.ValidationError({
                    'items': 'Cannot add the same product size multiple times.'
                })
            seen_variant_ids.append(variant.pk)

            try:
                quantity = max(1, int(quantity))
            except (ValueError, TypeError):
                raise serializers.ValidationError({
                    'items': f'Invalid quantity for size {variant.pk}'
                })

            validated_items.append({
                'product': variant.product,
                'variant': variant,
                'quantity': quantity
            })

        if not validated_items:
            raise serializers.ValidationError({
                'items': 'At least one valid product must be added to the combo.'
            })

        return validated_items

    def create(self, validated_data):
        items_raw = validated_data.pop('items', '[]')
        sections = validated_data.pop('sections', [])
        items_data = self._parse_items(items_raw)
        validated_items = self._validate_and_get_items(items_data)
        
        combo = ProductCombo.objects.create(**validated_data)
        
        # Add sections
        if sections:
            combo.sections.set(sections)
        
        for item_data in validated_items:
            ProductComboItem.objects.create(
                combo=combo,
                product=item_data['product'],
                variant=item_data['variant'],
                quantity=item_data['quantity']
            )

        return combo

    def update(self, instance, validated_data):
        items_raw = validated_data.pop('items', None)
        sections = validated_data.pop('sections', None)
        
        # Update main combo fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update sections if provided
        if sections is not None:
            instance.sections.set(sections)
        
        # Handle nested items only if items were provided
        if items_raw is not None and items_raw != '':
            items_data = self._parse_items(items_raw)
            validated_items = self._validate_and_get_items(items_data)
            
            # Clear existing items and create new ones
            instance.productcomboitem_set.all().delete()
            
            for item_data in validated_items:
                ProductComboItem.objects.create(
                    combo=instance,
                    product=item_data['product'],
                    variant=item_data['variant'],
                    quantity=item_data['quantity']
                )

        return instance

    def _mrp_for_raw_items(self, items_data):
        """Derived MRP for a payload's items — READ-ONLY, no side effects.

        `validate()` cannot go through `_validate_and_get_items`: that resolves a
        product-only line by *materialising* its default size, so a payload that
        then fails validation would leave a freshly minted ProductVariant behind.
        Validation must not write. Full validation (and that materialisation)
        still happens in create()/update(), where the write is wanted.

        Anything unresolvable is skipped rather than raising — this method
        answers "what do these components add up to", and it is create()/update()
        that rejects a bad line, with the specific message.
        """
        total = Decimal('0')
        for item in items_data or []:
            try:
                quantity = max(1, int(item.get('quantity', 1)))
            except (ValueError, TypeError):
                quantity = 1

            price = None
            if item.get('variant'):
                price = (ProductVariant.objects
                         .filter(pk=item['variant'])
                         .values_list('price', flat=True).first())
            elif item.get('product'):
                variant = _default_variant_for(item['product'])
                # No size yet: the legacy Product.price is what such a product
                # would be sold at, and is exactly what create() will copy onto
                # the variant it mints.
                price = variant.price if variant is not None else (
                    Product.objects.filter(pk=item['product'])
                    .values_list('price', flat=True).first())

            if price:
                total += Decimal(str(price)) * quantity
        return total

    def validate(self, data):
        """Reject a selling price ABOVE the MRP the components imply.

        Equal is allowed: a bundle sold at exactly the sum of its parts is a
        legitimate curation with no discount. Only charging MORE than the à-la-
        carte total is wrong. Note the MRP is derived, so it moves whenever a
        component is re-priced — this is a check at write time, not an invariant
        the catalogue can maintain on its own.

        The MRP has to be computed from the items in THIS payload — not from
        `instance.price`, which still reflects the old components when the same
        request also replaces them. On create there is no instance at all, so the
        payload is the only source. When a request changes only `discount_price`
        and sends no items, the stored components are the right basis and
        `instance.price` is used.
        """
        discount_price = data.get('discount_price')
        if not discount_price:
            return data

        items_raw = data.get('items')
        if items_raw not in (None, ''):
            mrp = self._mrp_for_raw_items(self._parse_items(items_raw))
        else:
            mrp = getattr(self.instance, 'price', None)

        if mrp and Decimal(str(discount_price)) > mrp:
            raise serializers.ValidationError({
                'discount_price': 'Selling price cannot exceed the combo MRP '
                                  f'(₹{mrp}, the sum of its components).'
            })

        return data
