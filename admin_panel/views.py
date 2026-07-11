from django.shortcuts import render, get_object_or_404

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, SAFE_METHODS
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from decimal import Decimal

from .utils import generate_upi_qr_code
from .models import ReceivableAccount, Coupon, Policy
from .serializers import (
    ReceivableAccountSerializer, 
    CouponSerializer, 
    RecentOrderSerializer,
    PolicySerializer
)
from cart.models import Cart
from orders.models import Order
from products.models import Product, ProductCombo, ProductComboItem


# ==================== PERMISSIONS ====================

class IsAdminUser(permissions.BasePermission):
    """
    Custom permission to allow only admin users (is_staff=True)
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_staff


class IsReadOnlyOrAdmin(permissions.BasePermission):
    """
    - Read-only access for everyone (including unauthenticated users)
    - Write access only for admin users (is_staff=True)
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff


# ==================== VIEWSETS ====================

class ReceivableAccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet to manage receivable accounts - admin only for security
    Protects payment collection accounts from unauthorized access
    """
    queryset = ReceivableAccount.objects.all()
    serializer_class = ReceivableAccountSerializer
    permission_classes = [IsAdminUser]


class PaymentAccountView(APIView):
    """
    Returns the default payment account for authenticated users.
    This is a safe endpoint that only returns the necessary info for checkout.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def get(self, request):
        # Get the default active account, fallback to any active account
        account = ReceivableAccount.objects.filter(is_active=True, is_default=True).first() or \
                  ReceivableAccount.objects.filter(is_active=True).first()
        
        if not account:
            return Response(
                {'error': 'No payment account configured'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        return Response({
            'id': account.id,
            'account_name': account.account_holder_name,
            'upi_id': account.upi_id,
        })


class CouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]
    # Admin management list with no pagination UI: return every coupon so the
    # 13th+ isn't silently hidden by the global PAGE_SIZE. (Small, admin-only.)
    pagination_class = None

    @action(detail=False, methods=['post'])
    def validate(self, request):
        """Admin utility: check whether a coupon code exists and is redeemable.

        Reports the *structural* validity an admin cares about — active, not
        expired, usage limit not reached. Per-checkout concerns (single-user
        assignment, minimum-order amount) are intentionally NOT treated as
        failures here, since they depend on who is buying and what's in the cart;
        the coupon's configured limits are returned so the admin can see them.
        """
        from django.utils import timezone

        code = (request.data.get('code') or '').strip()
        if not code:
            return Response(
                {'valid': False, 'error': 'Coupon code is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            coupon = Coupon.objects.get(code__iexact=code)
        except Coupon.DoesNotExist:
            return Response(
                {'valid': False, 'error': f"Coupon '{code}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        reasons = []
        if not coupon.is_active:
            reasons.append('inactive')
        if coupon.valid_until and coupon.valid_until < timezone.now():
            reasons.append('expired')
        if coupon.max_usage is not None and coupon.usage_count >= coupon.max_usage:
            reasons.append('usage limit reached')

        valid = not reasons
        return Response({
            'valid': valid,
            'reason': None if valid else ', '.join(reasons),
            'coupon': CouponSerializer(coupon).data,
        })


class DashboardViewSet(viewsets.ViewSet):
    """
    Dashboard ViewSet - admin only
    Contains sales statistics and business data (cached for 2 minutes)
    """
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    def list(self, request):
        from django.core.cache import cache
        from django.conf import settings
        
        cache_key = 'ngu:dashboard:stats'
        cache_ttl = getattr(settings, 'CACHE_TTL_DASHBOARD', 120)  # 2 minutes
        
        # Try to get from cache
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)
        
        total_orders = Order.objects.count()
        total_products = Product.objects.count()
        total_combos = ProductCombo.objects.count()
        active_coupons = Coupon.objects.count()

        recent_orders_qs = Order.objects.order_by('-created_at')[:5]
        recent_orders = RecentOrderSerializer(recent_orders_qs, many=True).data

        data = {
            "totalProducts": total_products,
            "totalCombos": total_combos,
            "totalOrders": total_orders,
            "activeCoupons": active_coupons,
            "recentOrders": recent_orders
        }
        
        # Cache the result
        cache.set(cache_key, data, cache_ttl)

        return Response(data)


class PolicyViewSet(viewsets.ModelViewSet):
    """
    Policy ViewSet:
    - Read-only (retrieve/list) for all users including anonymous
    - Update/Create/Delete only for admin users
    """
    queryset = Policy.objects.all()
    serializer_class = PolicySerializer
    permission_classes = [IsReadOnlyOrAdmin]
    lookup_field = 'type'

    def get_object(self):
        policy_type = self.kwargs.get('type')
        try:
            return Policy.objects.get(type=policy_type)
        except Policy.DoesNotExist:
            return None

    def retrieve(self, request, *args, **kwargs):
        policy = self.get_object()
        policy_type = self.kwargs.get('type')
        
        if policy is None:
            # Check if it's a valid policy type
            valid_types = [choice[0] for choice in Policy.POLICY_TYPES]
            if policy_type not in valid_types:
                return Response(
                    {"error": f"Invalid policy type. Valid types are: {', '.join(valid_types)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Return helpful message for admins
            return Response(
                {
                    "error": "Policy not configured",
                    "message": f"The '{policy_type}' policy has not been created yet. Please create it in the admin panel.",
                    "type": policy_type,
                    "content": None
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(policy)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        policy = self.get_object()
        policy_type = self.kwargs.get('type')
        
        # If policy doesn't exist, create it (for admins)
        if policy is None:
            valid_types = [choice[0] for choice in Policy.POLICY_TYPES]
            if policy_type not in valid_types:
                return Response(
                    {"error": f"Invalid policy type. Valid types are: {', '.join(valid_types)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create new policy
            serializer = self.get_serializer(data={'type': policy_type, **request.data})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        if hasattr(policy, 'can_edit_by') and not policy.can_edit_by(request.user):
            return Response(
                {"error": "No permission to edit"},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        policy = self.get_object()
        policy_type = self.kwargs.get('type')
        
        # If policy doesn't exist, create it (for admins)
        if policy is None:
            valid_types = [choice[0] for choice in Policy.POLICY_TYPES]
            if policy_type not in valid_types:
                return Response(
                    {"error": f"Invalid policy type. Valid types are: {', '.join(valid_types)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create new policy
            serializer = self.get_serializer(data={'type': policy_type, **request.data})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        if hasattr(policy, 'can_edit_by') and not policy.can_edit_by(request.user):
            return Response(
                {"error": "No permission to edit"},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().partial_update(request, *args, **kwargs)
