from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from .models import Review
from .serializers import ReviewSerializer
from orders.models import OrderItem

# An order only counts as a purchase once it has left the pending/payment stage.
PURCHASED_ORDER_STATUSES = ['confirmed', 'processing', 'shipped', 'delivered', 'delivering']


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


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        is_staff = user.is_authenticated and user.is_staff
        queryset = Review.objects.all().select_related('user', 'product', 'combo')

        # Moderation: hidden reviews vanish from public listings but stay
        # visible to staff (to moderate) and to their own author.
        if not is_staff:
            if user.is_authenticated:
                from django.db.models import Q
                queryset = queryset.filter(Q(is_hidden=False) | Q(user=user))
            else:
                queryset = queryset.filter(is_hidden=False)

        # Filter by product or combo
        product_id = self.request.query_params.get('product')
        combo_id = self.request.query_params.get('combo')

        if product_id:
            queryset = queryset.filter(product_id=product_id, item_type='product')
        elif combo_id:
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
        review.save(update_fields=['is_hidden'])
        return Response({"id": review.id, "is_hidden": review.is_hidden})

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
