from django.contrib import admin
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin
from modeltranslation.admin import TranslationAdmin
from .models import (
    Category, Product, ProductImage, ProductCombo, ProductComboItem,
    ProductSection, ProductSectionPlacement, ProductSearchKB, ProductComboSearchKB,
    ProductVariant,
)


class ProductSectionPlacementInline(SortableInlineAdminMixin, admin.TabularInline):
    """Drag-and-drop ordering of products within a homepage section."""
    model = ProductSectionPlacement
    extra = 1
    autocomplete_fields = ['product']


@admin.register(ProductSection)
class ProductSectionAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ['name', 'section_type', 'display_order', 'max_products', 'is_active', 'created_at']
    list_filter = ['section_type', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['display_order', 'is_active']
    ordering = ['display_order', 'name']
    inlines = [ProductSectionPlacementInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'section_type', 'description')
        }),
        ('Display Settings', {
            'fields': ('icon', 'display_order', 'max_products')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )


@admin.register(Category)
class CategoryAdmin(TranslationAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['name']


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'alt_text']


class ProductVariantInline(admin.TabularInline):
    """Manage the packaging sizes (100g / 500g / 1kg ...) of a product inline.

    A size can be switched off but never removed — untick `is_active`. See
    ProductVariantAdmin.has_delete_permission for why.
    """
    model = ProductVariant
    extra = 1
    fields = ['weight', 'unit', 'price', 'discount_price', 'stock',
              'is_default', 'is_active', 'display_order', 'sku', 'slug']
    readonly_fields = ['slug']
    can_delete = False


@admin.register(Product)
class ProductAdmin(TranslationAdmin):
    list_display = ['name', 'category', 'spice_form', 'price', 'discount_price',
                    'tax_rate', 'hsn_code', 'stock', 'organic', 'is_featured',
                    'is_active', 'created_at']
    list_filter = ['category', 'spice_form', 'organic', 'is_featured', 'is_active',
                   'sections', 'created_at', 'hsn_code']
    search_fields = ['name', 'description', 'ingredients', 'hsn_code']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured', 'is_active']
    ordering = ['-created_at']
    inlines = [ProductVariantInline, ProductImageInline]
    # Section membership + ordering is managed from ProductSectionAdmin's
    # drag-drop inline (a through-M2M can't be edited via filter_horizontal).

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'category', 'description')
        }),
        ('Spice Details', {
            'fields': ('spice_form', 'weight', 'unit', 'origin_country', 'organic', 'shelf_life', 'ingredients')
        }),
        ('Pricing & Stock', {
            'fields': ('price', 'discount_price', 'tax_rate', 'hsn_code', 'stock'),
            'description': (
                'Prices are GST-INCLUSIVE. tax_rate only splits the price for '
                'disclosure — it never changes what the customer pays. hsn_code '
                'is the tariff classification the GST return is filed by; the '
                'admin panel product form shows the statutory rate for each code '
                'next to the rate charged.'
            ),
        }),
        ('Media', {
            'fields': ('image',)
        }),
        ('Flags & Placement', {
            'fields': ('is_active', 'is_featured', 'badge')
        }),
    )


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['product', 'formatted_weight', 'price', 'discount_price',
                    'stock', 'is_default', 'is_active', 'display_order']
    list_filter = ['is_default', 'is_active', 'unit']
    search_fields = ['product__name', 'slug', 'sku']
    list_editable = ['price', 'discount_price', 'stock', 'is_active']
    autocomplete_fields = ['product']
    readonly_fields = ['slug']
    ordering = ['product', 'display_order']

    def has_delete_permission(self, request, obj=None):
        """Sizes are retired, never deleted — same rule as the admin panel API.

        A variant is the row that priced a line on an order and on the tax
        invoice issued for it. Order items and combo items PROTECT it, so a
        delete here would either fail with an opaque 500 or, for a size nothing
        has bought yet, succeed and silently empty the carts holding it. Untick
        `is_active` instead (`ProductVariantViewSet.destroy` does exactly that).
        """
        return False


class ProductComboItemInline(admin.TabularInline):
    """Components of a combo — each one a specific SIZE, not just a product.

    `product` is deliberately absent: it is derived from the variant in
    ``ProductComboItem.save()``. Offering it here would let an admin pick a
    product and get "whichever size is default today", which is exactly the
    ambiguity the variant FK removed. The variant's own label already reads
    "Turmeric Powder - 250g", so nothing is lost.
    """
    model = ProductComboItem
    extra = 1
    fields = ['variant', 'quantity']
    autocomplete_fields = ['variant']


@admin.register(ProductCombo)
class ProductComboAdmin(admin.ModelAdmin):
    # `mrp` is a read-only callable, not a column — see ProductCombo.price.
    list_display = ['name', 'mrp', 'discount_price', 'is_active', 'is_featured',
                    'badge', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductComboItemInline]
    search_fields = ['name', 'slug', 'description', 'title', 'subtitle']
    list_filter = ['is_active', 'is_featured', 'sections', 'created_at']
    list_editable = ['is_featured', 'is_active']
    ordering = ['-created_at']
    filter_horizontal = ['sections']
    readonly_fields = ['mrp']

    @admin.display(description='MRP (from components)')
    def mrp(self, obj):
        """The derived list price. Read-only everywhere: it is the sum of the
        component sizes' prices, so the way to change it is to change the
        components."""
        return obj.price

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description')
        }),
        ('Display Titles', {
            'fields': ('title', 'subtitle'),
            'description': 'Custom titles for marketing and display purposes'
        }),
        ('Pricing & Unit', {
            'fields': ('mrp', 'discount_price', 'unit'),
            'description': 'MRP is the sum of the component sizes below. GST is '
                           'charged per component at its own product rate, so a '
                           'combo has no tax rate of its own.'
        }),
        ('Media', {
            'fields': ('image',)
        }),
        ('Flags & Placement', {
            'fields': ('is_active', 'is_featured', 'badge', 'sections')
        }),
    )


# Optional: Register ProductComboItem if you need standalone access
@admin.register(ProductComboItem)
class ProductComboItemAdmin(admin.ModelAdmin):
    # `variant` is the unit of sale; `product` is shown only as the derived
    # grouping it mirrors.
    list_display = ['combo', 'variant', 'product', 'quantity']
    list_filter = ['combo']
    search_fields = ['combo__name', 'product__name', 'variant__slug']
    autocomplete_fields = ['combo', 'variant']

@admin.register(ProductSearchKB)
class ProductSearchKBAdmin(admin.ModelAdmin):
    list_display = ['product', 'last_updated']
    search_fields = ['product__name', 'synonyms']
    list_filter = ['last_updated']
    autocomplete_fields = ['product']
    ordering = ['-last_updated']
    readonly_fields = ['last_updated']
    
    fieldsets = (
        ('Product Link', {
            'fields': ('product',)
        }),
        ('Search Data', {
            'fields': ('synonyms', 'last_updated')
        }),
    )


@admin.register(ProductComboSearchKB)
class ProductComboSearchKBAdmin(admin.ModelAdmin):
    list_display = ['combo', 'last_updated']
    search_fields = ['combo__name', 'synonyms']
    list_filter = ['last_updated']
    autocomplete_fields = ['combo']
    ordering = ['-last_updated']
    readonly_fields = ['last_updated']
    
    fieldsets = (
        ('Combo Link', {
            'fields': ('combo',)
        }),
        ('Search Data', {
            'fields': ('synonyms', 'last_updated')
        }),
    )
