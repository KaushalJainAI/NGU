from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from .models import MAX_FEATURED_REVIEWS, Review
from .serializers import ReviewSerializer
from orders.models import OrderItem
from admin_panel.recycle import RecycleBinDestroyMixin

# An order only counts as a purchase once it has left the pending/payment stage.
PURCHASED_ORDER_STATUSES = ['confirmed', 'processing', 'shipped', 'delivered', 'delivering']


# A review of something that is switched off is not shown to shoppers: the home
# page would link to a product that no longer exists for them. Nothing is deleted
# or edited — the review is back the moment the product or combo is.
ITEM_IS_LIVE = (Q(item_type='product', product__is_active=True)
                | Q(item_type='combo', combo__is_active=True))


def has_purchased(user, item_type, product=None, combo=None):
    """True if `user` has an order containing this product/combo that reached a purchased status."""
    if item_type == 'product' and product:
        return OrderItem.objects.filter(
            order__user=user,
            product=product,
            order__status__in=PURCHASED_ORDER_STATUSES,
        ).exists()
    if item_type == 'combo' and combo:
        return OrderItem.objects.filter(
            order__user=user,
            combo=combo,
            order__status__in=PURCHASED_ORDER_STATUSES,
        ).exists()
    return False


class ReviewViewSet(RecycleBinDestroyMixin, viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    recycle_kind = 'review'

    def should_recycle(self, instance):
        # An ADMIN removing a review can be a mis-click on the moderation table,
        # so it goes to the Recycle Bin. A customer deleting their own words is
        # a decision about their own content and is honoured outright.
        user = self.request.user
        return bool(user.is_authenticated and user.is_staff)

    def recycle_label(self, instance):
        author = getattr(instance.user, 'email', '') or 'customer'
        return f"{instance.rating}★ on {instance.item_name} — {author}"

    def get_queryset(self):
        user = self.request.user
        is_staff = user.is_authenticated and user.is_staff
        queryset = Review.objects.all().select_related('user', 'product', 'combo')

        # Moderation: hidden reviews vanish from public listings but stay
        # visible to staff (to moderate) and to their own author.
        if not is_staff:
            public = Q(is_hidden=False) & ITEM_IS_LIVE
            if user.is_authenticated:
                queryset = queryset.filter(public | Q(user=user))
            else:
                queryset = queryset.filter(public)

        # Filter by product or combo
        product_id = self.request.query_params.get('product')
        combo_id = self.request.query_params.get('combo')

        # `?featured=true` — the admin panel's "which three are on the home
        # page?" lookup. It must span every page of the moderation table, so it
        # can't be derived from the rows currently on screen.
        if self.request.query_params.get('featured') in ('1', 'true', 'True'):
            queryset = queryset.filter(is_featured=True)

        # A non-numeric id names no product; answer with an empty list rather
        # than letting the ORM raise on it.
        if product_id:
            if not str(product_id).isascii() or not str(product_id).isdigit():
                return queryset.none()
            queryset = queryset.filter(product_id=product_id, item_type='product')
        elif combo_id:
            if not str(combo_id).isascii() or not str(combo_id).isdigit():
                return queryset.none()
            queryset = queryset.filter(combo_id=combo_id, item_type='combo')
        elif is_staff and self.action == 'list' and self.request.query_params.get('all') in ('1', 'true', 'True'):
            pass  # admin moderation view: every review, all products
        elif user.is_authenticated and self.action == 'list':
            queryset = queryset.filter(user=user)

        # SECURITY: If not staff, ensure user can only edit/delete their own reviews
        if not (user.is_authenticated and user.is_staff) and self.action not in ['list', 'retrieve']:
            if user.is_authenticated:
                queryset = queryset.filter(user=user)
            else:
                queryset = queryset.none()
            
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        item_type = serializer.validated_data.get('item_type', 'product')
        product = serializer.validated_data.get('product')
        combo = serializer.validated_data.get('combo')
        
        # Check for duplicate review
        if item_type == 'product' and product:
            if Review.objects.filter(user=self.request.user, product=product, item_type='product').exists():
                raise serializers.ValidationError({"error": "You have already reviewed this product"})
        elif item_type == 'combo' and combo:
            if Review.objects.filter(user=self.request.user, combo=combo, item_type='combo').exists():
                raise serializers.ValidationError({"error": "You have already reviewed this combo"})
        
        # ENFORCE verified purchase - user must have a confirmed/shipped/delivered order with this item
        if not has_purchased(self.request.user, item_type, product=product, combo=combo):
            raise serializers.ValidationError({
                "error": "You can only review items from orders that have been confirmed or delivered"
            })

        serializer.save(user=self.request.user, is_verified_purchase=True)

    @action(detail=False, methods=['get'], url_path='can-review',
            permission_classes=[IsAuthenticated])
    def can_review(self, request):
        """Whether the current user may review a given product/combo.

        Lets the storefront hide the review form instead of letting the user
        write a review and only fail on submit. This is a UX hint only — the
        real gate stays in perform_create.
        """
        product_id = request.query_params.get('product')
        combo_id = request.query_params.get('combo')
        if bool(product_id) == bool(combo_id):
            return Response(
                {"error": "Provide exactly one of 'product' or 'combo'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item_type = 'product' if product_id else 'combo'
        try:
            item_id = int(product_id or combo_id)
        except (TypeError, ValueError):
            return Response(
                {"error": f"'{item_type}' must be a numeric id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        filters = {'user': request.user, 'item_type': item_type, f'{item_type}_id': item_id}

        if Review.objects.filter(**filters).exists():
            return Response({"can_review": False, "reason": "already_reviewed"})
        if not has_purchased(
            request.user,
            item_type,
            product=item_id if item_type == 'product' else None,
            combo=item_id if item_type == 'combo' else None,
        ):
            return Response({"can_review": False, "reason": "not_purchased"})
        return Response({"can_review": True, "reason": None})

    @action(detail=False, methods=['get'], url_path='featured',
            permission_classes=[AllowAny])
    def featured(self, request):
        """The home page testimonials strip — always MAX_FEATURED_REVIEWS long.

        Admin-flagged reviews come first; if fewer than three are flagged (or a
        flagged one has since been hidden or deleted) the rest are topped up
        with the best recent reviews, so the strip is never sparse or empty.
        Public: no auth, hidden reviews and reviews of switched-off products
        excluded unconditionally.
        """
        visible = Review.objects.filter(is_hidden=False).filter(
            ITEM_IS_LIVE).select_related('user', 'product', 'combo')

        chosen = list(visible.filter(is_featured=True).order_by('-created_at')[:MAX_FEATURED_REVIEWS])

        if len(chosen) < MAX_FEATURED_REVIEWS:
            # Top up with the most favourable recent reviews, skipping any
            # already chosen. Ordering by rating first keeps the strip a
            # showcase rather than a random sample.
            fillers = (visible.exclude(pk__in=[r.pk for r in chosen])
                              .order_by('-rating', '-created_at')[:MAX_FEATURED_REVIEWS])
            chosen.extend(fillers[:MAX_FEATURED_REVIEWS - len(chosen)])

        return Response({
            'count': len(chosen),
            'results': ReviewSerializer(chosen, many=True).data,
        })

    @action(detail=True, methods=['post'], url_path='set-featured')
    def set_featured(self, request, pk=None):
        """Staff-only homepage placement: POST {"featured": true|false}.

        Caps the selection at MAX_FEATURED_REVIEWS. Rejecting the fourth (rather
        than silently dropping the oldest) keeps the admin in control of which
        three the shopper sees.
        """
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return Response({"error": "Only staff can feature reviews."},
                            status=status.HTTP_403_FORBIDDEN)
        review = self.get_object()
        featured = request.data.get('featured')
        if not isinstance(featured, bool):
            return Response({"error": 'Send {"featured": true} or {"featured": false}.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Check the property of THIS review before the global cap, so a hidden
        # review reports why it specifically can't be picked rather than
        # blaming the slot count.
        if featured and review.is_hidden:
            return Response(
                {"error": "A hidden review can't be featured. Make it visible first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = review.product if review.item_type == 'product' else review.combo
        if featured and (subject is None or not subject.is_active):
            return Response(
                {"error": "This review's product is switched off, so it can't be featured. "
                          "Switch the product back on first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            if featured and not review.is_featured:
                # Lock the flagged rows so two admins can't each pass the count
                # check and push the total to four.
                current = Review.objects.select_for_update().filter(is_featured=True).count()
                if current >= MAX_FEATURED_REVIEWS:
                    return Response(
                        {"error": f"Only {MAX_FEATURED_REVIEWS} reviews can be featured on the "
                                  f"home page. Unpick one first."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            review.is_featured = featured
            review.save(update_fields=['is_featured'])

        return Response({
            "id": review.id,
            "is_featured": review.is_featured,
            "featured_count": Review.objects.filter(is_featured=True).count(),
            "max_featured": MAX_FEATURED_REVIEWS,
        })

    @action(detail=True, methods=['post'], url_path='set-hidden')
    def set_hidden(self, request, pk=None):
        """Staff-only moderation switch: POST {"hidden": true|false}."""
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return Response({"error": "Only staff can moderate reviews."},
                            status=status.HTTP_403_FORBIDDEN)
        review = self.get_object()
        hidden = request.data.get('hidden')
        if not isinstance(hidden, bool):
            return Response({"error": 'Send {"hidden": true} or {"hidden": false}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        review.is_hidden = hidden
        fields = ['is_hidden']
        # Hiding retires the homepage slot too, so it frees up for another pick
        # instead of being held by a review no shopper can see.
        if hidden and review.is_featured:
            review.is_featured = False
            fields.append('is_featured')
        review.save(update_fields=fields)
        return Response({"id": review.id, "is_hidden": review.is_hidden,
                         "is_featured": review.is_featured})

    def perform_update(self, serializer):
        # A review's subject is fixed at creation. Without this, a user could
        # PATCH a verified review onto a DIFFERENT product/combo they never
        # bought (is_verified_purchase is read-only and would stay True),
        # manufacturing fake "verified" reviews. Only rating/title/comment may
        # change; to review another item, create a new (verified) review.
        instance = serializer.instance
        new_type = serializer.validated_data.get('item_type', instance.item_type)
        new_product = serializer.validated_data.get('product', instance.product)
        new_combo = serializer.validated_data.get('combo', instance.combo)
        if (new_type != instance.item_type
                or new_product != instance.product
                or new_combo != instance.combo):
            raise serializers.ValidationError({
                "error": "The reviewed item cannot be changed. Please create a new review instead."
            })
        serializer.save()
