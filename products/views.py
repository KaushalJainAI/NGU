from rest_framework import viewsets, filters, status
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.decorators import api_view, action, throttle_classes
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Avg, Count
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.conf import settings
from django.utils.translation import get_language
from django.utils import timezone

from spices_backend.limits import (
    MAX_SEARCH_Q, SEARCH_TOP_K_MAX, SEARCH_THRESHOLD_MIN, SEARCH_THRESHOLD_MAX, clamp,
)
from django.db import transaction
from .models import (
    Category, Product, ProductCombo, ProductImage, ProductSection,
    ProductSectionPlacement, ProductSlugAlias, ProductVariant,
)
from .serializers import (
    CategorySerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductComboSerializer,
    ProductImageSerializer,
    HomepageSectionSerializer,
    ProductSectionSerializer,
    ProductVariantWriteSerializer,
)
from .cache import (
    make_cache_key,
    get_cached_or_set,
    CACHE_PREFIX_PRODUCTS,
    CACHE_PREFIX_CATEGORIES,
    CACHE_PREFIX_COMBOS,
    CACHE_PREFIX_SECTIONS,
    CACHE_PREFIX_SEARCH,
    TTL_MEDIUM,
)

# Cache TTLs from settings
CACHE_TTL = getattr(settings, 'CACHE_TTL_MEDIUM', 300)
CACHE_TTL_CATEGORIES = getattr(settings, 'CACHE_TTL_LONG', 900)


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


@api_view(['GET'])
def get_spice_forms(request):
    from .models import Product
    spice_forms = [
        {'value': choice[0], 'label': choice[1]}
        for choice in Product.SPICE_FORM_CHOICES
    ]
    return Response(spice_forms)


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        # Annotate the active-product count so the serializer doesn't run a
        # COUNT(*) per category. distinct=True guards against row multiplication.
        qs = Category.objects.annotate(
            _products_count=Count('products', filter=Q(products__is_active=True), distinct=True)
        )
        user = self.request.user
        if not (user and user.is_staff):
            qs = qs.filter(is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        """Cached category list for non-admin users."""
        # Skip cache for staff users - they need to see fresh data
        if request.user and request.user.is_staff:
            return super().list(request, *args, **kwargs)
        
        # Include the active language so translated content isn't served stale
        # across languages.
        cache_key = make_cache_key(CACHE_PREFIX_CATEGORIES, 'list', lang=get_language())
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        
        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(cache_key, response.data, CACHE_TTL_CATEGORIES)
        return response

    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to support both ID and slug lookup
        """
        lookup_value = kwargs.get('slug')
        qs = self.get_queryset()
        
        try:
            if lookup_value and lookup_value.isdigit():
                # Numeric ID lookup
                instance = get_object_or_404(qs, id=int(lookup_value))
            else:
                # Slug lookup
                instance = get_object_or_404(qs, slug=lookup_value)
        except Category.DoesNotExist:
            return Response(
                {"detail": "No Category matches the given query."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductSectionViewSet(viewsets.ModelViewSet):
    """Homepage sections: flat list for everyone, full CRUD for staff.

    Powers the section multi-select on the admin product/combo edit forms AND
    the admin panel's Sections page (create/edit/hide sections + order the
    products inside each one without touching the Django admin). The
    storefront's rich nested payload still lives at /products/sections/.
    Public read is harmless (section names aren't sensitive); writes are
    admin-only via IsAdminOrReadOnly.
    """
    queryset = ProductSection.objects.all().order_by('display_order', 'name')
    serializer_class = ProductSectionSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        # Soft-hide, mirroring CategoryViewSet: placements survive so the
        # section can be switched back on without rebuilding it.
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'put'])
    def products(self, request, pk=None):
        """The ordered products of one section.

        GET → [{id, name, image, position}] in display order.
        PUT {"product_ids": [3, 1, 7]} → replace the section's product list
        with exactly these products, positioned in the given order.
        """
        section = self.get_object()

        if request.method == 'PUT':
            ids = request.data.get('product_ids')
            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
                return Response(
                    {'error': 'Send {"product_ids": [<product id>, …]} in display order.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            valid_ids = set(Product.objects.filter(id__in=ids).values_list('id', flat=True))
            unknown = [i for i in ids if i not in valid_ids]
            if unknown:
                return Response(
                    {'error': f'Unknown product ids: {unknown}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            with transaction.atomic():
                ProductSectionPlacement.objects.filter(section=section).delete()
                ProductSectionPlacement.objects.bulk_create([
                    ProductSectionPlacement(section=section, product_id=pid, position=pos)
                    for pos, pid in enumerate(ids)
                ])

        placements = (
            ProductSectionPlacement.objects.filter(section=section)
            .select_related('product').order_by('position')
        )
        return Response([
            {
                'id': p.product.id,
                'name': p.product.name,
                'image': (p.product.image.url if getattr(p.product, 'image', None) else None),
                'position': p.position,
                'is_active': p.product.is_active,
            }
            for p in placements
        ])


class ProductFilter(django_filters.FilterSet):
    """`category` matches the canonical FK OR any secondary category, so a
    product listed on several shelves (e.g. Chat Masala is both a blended
    masala and a sprinkler) shows up under each of them."""
    category = django_filters.CharFilter(method='filter_category')

    class Meta:
        model = Product
        fields = ['category', 'spice_form', 'organic', 'is_featured', 'is_active']

    def filter_category(self, queryset, name, value):
        if not value:
            return queryset
        # The storefront passes an id; accept a slug too.
        key = 'id' if str(value).isdigit() else 'slug'
        return queryset.filter(
            Q(**{f'category__{key}': value}) | Q(**{f'extra_categories__{key}': value})
        ).distinct()


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None
    lookup_field = 'slug'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'ingredients']
    ordering_fields = ['price', 'created_at', 'name']
    ordering = ['-created_at']

    def get_queryset(self):
        """Optimized queryset with review annotations and related prefetching."""
        user = self.request.user
        is_staff = user and user.is_staff

        # Annotate rating/review aggregates so the serializer's
        # `_average_rating` / `_reviews_count` fast-path is actually hit instead
        # of running two review queries per product. distinct=True guards the
        # count against row multiplication if another join is ever added.
        qs = Product.objects.select_related('category').annotate(
            _average_rating=Avg('reviews__rating', filter=Q(reviews__is_hidden=False)),
            _reviews_count=Count('reviews', filter=Q(reviews__is_hidden=False), distinct=True),
        )

        # Filter for non-staff users
        if not is_staff:
            qs = qs.filter(is_active=True)

        # No .only() on list: it deferred fields the serializer emits
        # (tax_rate, unit, thumbnail) causing per-instance queries, and deferred
        # modeltranslation's per-language columns so translated names fell back
        # to English. sections is prefetched because the list serializer emits
        # both `sections` and `section_names`.
        if self.action == 'list':
            qs = qs.prefetch_related('variants', 'sections')
        else:
            qs = qs.prefetch_related('images', 'sections', 'variants')
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        return ProductDetailSerializer

    def list(self, request, *args, **kwargs):
        """Cached product list for non-admin users."""
        # Skip cache for staff users
        if request.user and request.user.is_staff:
            return super().list(request, *args, **kwargs)
        
        # Build cache key from query params — include language so Hindi/Gujarati/etc.
        # requests don't get served the cached English product names.
        query_params = dict(request.query_params)
        cache_key = make_cache_key(CACHE_PREFIX_PRODUCTS, 'list', lang=get_language(), **query_params)
        
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        
        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(cache_key, response.data, CACHE_TTL)
        return response


    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to support both ID and slug lookup
        """
        lookup_value = kwargs.get('slug')
        qs = self.get_queryset()
        
        selected_variant_id = None
        if lookup_value and lookup_value.isdigit():
            # Numeric ID lookup
            instance = qs.filter(id=int(lookup_value)).first()
        else:
            # Slug lookup — first as a product, then fall back to a variant slug
            # so per-size URLs (e.g. /products/jeeravan-500g) resolve to the
            # parent product with that size pre-selected.
            instance = qs.filter(slug=lookup_value).first()
            if instance is None:
                from .models import ProductVariant
                variant = (
                    ProductVariant.objects.select_related('product')
                    .filter(slug=lookup_value, is_active=True)
                    .first()
                )
                if variant is not None:
                    selected_variant_id = variant.id
                    instance = qs.filter(id=variant.product_id).first()

            # Finally, fall back to a retired slug. Re-slugging a product would
            # otherwise 404 every link to it already in the wild.
            if instance is None:
                alias = (
                    ProductSlugAlias.objects
                    .filter(slug=lookup_value)
                    .values_list('product_id', flat=True)
                    .first()
                )
                if alias is not None:
                    # Go through qs so is_active / staff visibility still apply.
                    instance = qs.filter(id=alias).first()

        if instance is None:
            return Response(
                {"detail": "No Product matches the given query."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(instance)
        data = serializer.data
        if selected_variant_id is not None:
            data = dict(data)
            data['selected_variant_id'] = selected_variant_id
        return Response(data)

    def destroy(self, request, *args, **kwargs):
        # Soft-delete into the Recycle Bin: deactivate and stamp the deletion
        # time so the purge job can age it out. Restoring (is_active=True) clears
        # the stamp in Product.save().
        instance = self.get_object()
        instance.is_active = False
        instance.deactivated_at = timezone.now()
        instance.save(update_fields=['is_active', 'deactivated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def sections(self, request):
        """Get all active product sections with their products and combos - CACHED & SERIALIZED"""
        # Check cache for non-staff users (keyed by language for translations)
        cache_key = make_cache_key(CACHE_PREFIX_SECTIONS, 'all', lang=get_language())
        if not (request.user and request.user.is_staff):
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)
        
        sections = ProductSection.objects.filter(is_active=True).order_by('display_order')
        
        serializer = HomepageSectionSerializer(
            sections,
            many=True,
            context={'request': request},
        )
        response_data = {'results': serializer.data}
        
        # Cache for non-staff users
        if not (request.user and request.user.is_staff):
            cache.set(cache_key, response_data, CACHE_TTL)
        
        return Response(response_data)


class MRPOrderingFilter(filters.OrderingFilter):
    """Lets `?ordering=price` keep working on combos after MRP became derived.

    `ProductCombo.price` is now a property (the sum of its component sizes), so
    it cannot be handed to `order_by()`. `ProductComboQuerySet.with_mrp()` puts
    the identical figure in the `_mrp` annotation; this maps the public name
    onto it *after* DRF has validated the term against `ordering_fields`, so the
    API contract is unchanged and an unknown field is still rejected.
    """

    ALIASES = {'price': '_mrp', '-price': '-_mrp'}

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        return [self.ALIASES.get(term, term) for term in ordering]


class ComboProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductComboSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None
    lookup_field = 'slug'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, MRPOrderingFilter]
    filterset_fields = ['is_featured', 'is_active']
    search_fields = ['name', 'description']
    # `price` stays a public ordering field even though it is no longer a column:
    # MRPOrderingFilter rewrites it onto the `_mrp` annotation from with_mrp().
    ordering_fields = ['price', 'created_at', 'name']
    ordering = ['-created_at']
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        """Queryset with related prefetching for the combo serializer."""
        user = self.request.user
        is_staff = user and user.is_staff

        # Base queryset. `with_mrp()` annotates the derived MRP (sum of the
        # component sizes' prices) so the serializer doesn't fire one aggregate
        # per combo, and so ?ordering=price can sort on it.
        # Same review aggregates as ProductViewSet: without them the combo
        # serializer falls back to two queries per combo, and `distinct=True`
        # guards the count against row multiplication from with_mrp()'s joins.
        qs = ProductCombo.objects.with_mrp().annotate(
            _average_rating=Avg('reviews__rating', filter=Q(reviews__is_hidden=False)),
            _reviews_count=Count('reviews', filter=Q(reviews__is_hidden=False), distinct=True),
        )

        # Filter for non-staff users
        if not is_staff:
            qs = qs.filter(is_active=True)

        # No .only() on list: ProductComboSerializer serializes many fields
        # outside the old minimal set (description, title, subtitle, tax_rate,
        # weight, unit, thumbnail, sections) and to_representation always
        # serializes productcomboitem_set — both were N+1 on list. Prefetch the
        # items and sections that the serializer walks.
        # `variant` is walked by available_stock / total_weight / the item
        # serializer, so prefetch it alongside the product used for display.
        qs = qs.prefetch_related(
            'productcomboitem_set__product', 'productcomboitem_set__variant',
            'sections',
        )

        return qs

    def list(self, request, *args, **kwargs):
        """Cached combo list for non-admin users."""
        # Skip cache for staff users
        if request.user and request.user.is_staff:
            return super().list(request, *args, **kwargs)
        
        # Build cache key from query params — include language so combos return
        # translated names per language.
        query_params = dict(request.query_params)
        cache_key = make_cache_key(CACHE_PREFIX_COMBOS, 'list', lang=get_language(), **query_params)
        
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        
        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to support both ID and slug lookup
        """
        lookup_value = kwargs.get('slug')
        qs = self.get_queryset()
        
        try:
            if lookup_value and lookup_value.isdigit():
                # Numeric ID lookup
                instance = get_object_or_404(qs, id=int(lookup_value))
            else:
                # Slug lookup
                instance = get_object_or_404(qs, slug=lookup_value)
        except ProductCombo.DoesNotExist:
            return Response(
                {"detail": "No ProductCombo matches the given query."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        # Soft-delete into the Recycle Bin (see ProductViewSet.destroy).
        instance = self.get_object()
        instance.is_active = False
        instance.deactivated_at = timezone.now()
        instance.save(update_fields=['is_active', 'deactivated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductImageViewSet(viewsets.ModelViewSet):
    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer
    permission_classes = [IsAdminOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        qs = ProductImage.objects.select_related('product')
        product_id = self.request.query_params.get('product', None)
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs


class ProductVariantViewSet(viewsets.ModelViewSet):
    """Admin CRUD for product packaging sizes (variants).

    GET is public (so the admin panel can list); writes are staff-only.
    Filter by ?product=<id>. Ensures a single default per product and NEVER
    hard-deletes a variant — DELETE retires it (is_active=False) instead."""
    serializer_class = ProductVariantWriteSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None

    def get_queryset(self):
        qs = ProductVariant.objects.select_related('product')
        product_id = self.request.query_params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs.order_by('product_id', 'display_order', 'weight')

    def _unset_other_defaults(self, product_id, exclude_pk=None):
        qs = ProductVariant.objects.filter(product_id=product_id, is_default=True)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        qs.update(is_default=False)

    def perform_create(self, serializer):
        product = serializer.validated_data.get('product')
        if serializer.validated_data.get('is_default') and product:
            self._unset_other_defaults(product.id)
        serializer.save()

    def perform_update(self, serializer):
        if serializer.validated_data.get('is_default'):
            self._unset_other_defaults(
                serializer.instance.product_id, exclude_pk=serializer.instance.pk
            )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        """RETIRE a size. A variant row is NEVER removed from the database.

        A size is a priced, stocked, invoiced thing: it is named on order items,
        on issued tax invoices, in combos, and in live carts. Deleting the row
        would either be refused by the DB (order items and combo items are
        PROTECTed) or succeed and quietly take history and carts with it. One of
        those outcomes is destructive and neither is what an admin means by
        "remove this size from the shop", so DELETE just flips `is_active` off:

          * it stops being sellable and leaves the storefront,
          * every past order, invoice and report still resolves it,
          * it can be switched back on if it was retired by mistake.

        Two guards still run first, because retiring the wrong size breaks the
        catalog in ways deactivation alone does not fix:

        1. The last active size cannot go. A product with no sellable size still
           lists and still shows a (now stale) mirrored price, but nothing can be
           added to a cart — a silent dead product. Deactivate the product.
        2. A size a combo is built from cannot go. The combo consumes that exact
           packaging, so retiring it makes the bundle unbuildable (available
           stock 0) rather than repricing it. Fix the combos first.

        Live carts holding the size are reported back so the admin knows how many
        customers are about to hit "no longer available" at checkout. Those rows
        are left alone — nothing is yanked out of a cart by an admin edit.
        """
        instance = self.get_object()

        if not instance.is_active:
            return Response(
                {'detail': 'This size is already retired.',
                 'carts_affected': 0, 'is_active': False},
                status=status.HTTP_200_OK,
            )

        # 1. Never strand a product without a sellable size.
        siblings = ProductVariant.objects.filter(
            product_id=instance.product_id, is_active=True
        ).exclude(pk=instance.pk).count()
        if siblings == 0:
            return Response(
                {'detail': 'This is the only active size for this product. '
                           'Add another size first, or deactivate the whole '
                           'product instead of removing its last size.'},
                status=status.HTTP_409_CONFLICT,
            )

        # 2. Combos are built from this exact size — retiring it would silently
        #    make the bundle unbuildable.
        combo_names = list(
            ProductCombo.objects.filter(productcomboitem__variant=instance)
            .values_list('name', flat=True).distinct()
        )
        if combo_names:
            return Response(
                {'detail': 'This size is part of the combo(s): '
                           f"{', '.join(combo_names)}. Remove it from them first.",
                 'combos': combo_names},
                status=status.HTTP_409_CONFLICT,
            )

        # Retire, never delete. Dropping is_default lets the post_save signal
        # promote a surviving sibling as the product's default size.
        instance.is_active = False
        instance.is_default = False
        instance.save(update_fields=['is_active', 'is_default'])

        from cart.models import CartItem
        affected_carts = CartItem.objects.filter(variant=instance).count()
        detail = ('Size retired. It is no longer sellable, but past orders and '
                  'invoices still reference it.')
        if affected_carts:
            detail += f' It is still sitting in {affected_carts} customer cart(s).'
        return Response(
            {'detail': detail, 'carts_affected': affected_carts, 'is_active': False},
            status=status.HTTP_200_OK,
        )


from .recommendations import SpiceSearchEngine
search_engine = SpiceSearchEngine()

@api_view(['GET'])
def unified_search(request):
    """SINGLE ENDPOINT: Search + All Recommendations (Products + Combos ranked)"""
    query = request.GET.get('q', '').strip()

    # Bound the query length so a giant string can't drive a slow/expensive search.
    if len(query) > MAX_SEARCH_Q:
        return Response({'success': False, 'error': f'Query too long (max {MAX_SEARCH_Q} characters).'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        top_k = int(request.GET.get('top_k', 20))
    except (ValueError, TypeError):
        return Response({'success': False, 'error': 'top_k must be a valid integer'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        threshold = int(request.GET.get('threshold', 70))
    except (ValueError, TypeError):
        return Response({'success': False, 'error': 'threshold must be a valid integer'},
                        status=status.HTTP_400_BAD_REQUEST)

    if not query:
        return Response({'success': False, 'error': 'Query "q" required'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Clamp into safe ranges (negative / huge values would waste CPU/memory).
    top_k = clamp(top_k, 1, SEARCH_TOP_K_MAX)
    threshold = clamp(threshold, SEARCH_THRESHOLD_MIN, SEARCH_THRESHOLD_MAX)

    results = search_engine.unified_search(query, top_k, threshold)
    return Response(results)


class SearchSuggestThrottle(SimpleRateThrottle):
    """Dedicated autocomplete limit (per user, or per IP when anonymous), so the
    keystroke-frequency endpoint doesn't share the generic anon/user budget."""
    scope = 'search_suggest'

    def get_cache_key(self, request, view):
        ident = request.user.pk if request.user and request.user.is_authenticated \
            else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


@api_view(['GET'])
@throttle_classes([SearchSuggestThrottle])
def search_suggest(request):
    """Lightweight autocomplete suggestions over the cached search corpus."""
    query = request.GET.get('q', '').strip().lower()

    try:
        limit = int(request.GET.get('limit', 8))
    except (ValueError, TypeError):
        limit = 8
    limit = max(1, min(limit, 15))

    if len(query) < 2:
        return Response({'query': query, 'suggestions': []})

    from .recommendations import build_suggestions
    cache_key = make_cache_key(CACHE_PREFIX_SEARCH, 'suggest', get_language(), query, limit)
    payload = get_cached_or_set(cache_key, lambda: build_suggestions(query, limit), TTL_MEDIUM)
    return Response(payload)


@api_view(['GET'])
def recommendations(request):
    """
    Personalized product recommendations for the logged-in user.

    Anonymous callers get 401 — the frontend treats that as "show the static
    sections". Cold-start / no-signal users get a featured-popular fallback.
    """
    if not request.user or not request.user.is_authenticated:
        return Response({'detail': 'Authentication required'},
                        status=status.HTTP_401_UNAUTHORIZED)

    try:
        limit = int(request.GET.get('limit', 12))
    except (ValueError, TypeError):
        limit = 12
    limit = max(1, min(limit, 30))
    context = request.GET.get('context', 'home')

    from .personalization import get_recommendations
    products = get_recommendations(request.user, limit=limit, context=context)
    return Response({
        'context': context,
        'count': len(products),
        'products': products,
    })
