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
        
        from django.db.models import F, Q as DQ
        from django.utils import timezone

        total_orders = Order.objects.count()
        total_products = Product.objects.count()
        total_combos = ProductCombo.objects.count()
        # "Active" = redeemable right now: switched on, not expired, and not at
        # its global usage limit (mirrors Coupon.get_invalid_reason()).
        active_coupons = Coupon.objects.filter(is_active=True).filter(
            DQ(valid_until__isnull=True) | DQ(valid_until__gte=timezone.now())
        ).filter(
            DQ(max_usage__isnull=True) | DQ(usage_count__lt=F('max_usage'))
        ).count()

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

    @action(detail=False, methods=['get'])
    def actions(self, request):
        """Action inbox for the 'Today' dashboard: everything that currently
        needs the store owner's attention, as counts + a few example items.
        Cached briefly — this is polled by the panel landing page."""
        from django.core.cache import cache
        from django.conf import settings
        from django.db.models import F, Q, Sum
        from django.utils import timezone
        from datetime import timedelta
        from assistant.models import AssistantConversation

        cache_key = 'ngu:dashboard:actions'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        now = timezone.now()
        today = now.date()

        # New orders the admin can act on: pending AND actually payable/paid
        # (an ONLINE order still waiting for payment isn't confirmable yet).
        confirmable = Order.objects.filter(
            is_deleted=False, status='pending',
        ).filter(Q(payment_method='COD') | Q(payment_status='paid'))

        to_ship = Order.objects.filter(
            is_deleted=False, status__in=['confirmed', 'processing'])

        low_stock_qs = Product.objects.filter(
            is_active=True, stock__lte=F('low_stock_threshold'),
        ).order_by('stock')
        low_stock_items = [
            {'id': p.id, 'name': p.name, 'stock': p.stock}
            for p in low_stock_qs[:5]
        ]

        chats_waiting = AssistantConversation.objects.filter(
            needs_human=True, status='active').count()

        ttl = getattr(settings, 'PAYMENT_STUCK_TTL_MINUTES', 15)
        stuck_payments = Order.objects.filter(
            is_deleted=False,
            payment_method='ONLINE',
            payment_status__in=['pending', 'processing'],
            status='pending',
            created_at__lt=now - timedelta(minutes=ttl),
        ).count()

        today_orders = Order.objects.filter(
            is_deleted=False, created_at__date=today,
        ).exclude(status='cancelled')
        today_stats = today_orders.aggregate(revenue=Sum('total_amount'))

        data = {
            'orders_to_confirm': confirmable.count(),
            'orders_to_ship': to_ship.count(),
            'low_stock_count': low_stock_qs.count(),
            'low_stock_items': low_stock_items,
            'chats_waiting': chats_waiting,
            'stuck_payments': stuck_payments,
            'today_orders': today_orders.count(),
            'today_revenue': str(today_stats['revenue'] or 0),
        }
        cache.set(cache_key, data, 60)
        return Response(data)

    @action(detail=False, methods=['post'], url_path='send-report')
    def send_report(self, request):
        """Manually trigger the daily digest or weekly summary email so the admin
        can preview it on demand (also used to test email delivery). Body:
        {"type": "daily" | "weekly"}."""
        from django.core.management import call_command

        report = (request.data.get('type') or 'weekly').strip()
        command = {'daily': 'send_daily_digest', 'weekly': 'send_weekly_summary'}.get(report)
        if not command:
            return Response({'error': 'type must be "daily" or "weekly".'},
                            status=status.HTTP_400_BAD_REQUEST)
        call_command(command)
        return Response({'sent': True, 'type': report})


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


# ==================== GLOBAL ADMIN SEARCH ====================

class GlobalAdminSearchView(APIView):
    """One search box for the whole admin panel: matches orders, products,
    customers and coupons in a single call, capped per group. Read-only."""
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    GROUP_CAP = 5

    def get(self, request):
        from django.db.models import Q
        from django.contrib.auth import get_user_model

        q = (request.query_params.get('q') or '').strip()
        empty = {'orders': [], 'products': [], 'customers': [], 'coupons': []}
        if len(q) < 2:
            return Response(empty)

        User = get_user_model()

        # --- Orders: same vocabulary as the order-list search, incl. ORD-000123.
        cond = (Q(user__email__icontains=q) |
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(user__name__icontains=q) |
                Q(phone_number__icontains=q))
        # Cap at 9 digits: anything longer can't be a real order id and would
        # overflow Postgres's integer type (DataError → 500).
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits and len(digits) <= 9:
            cond |= Q(id=int(digits))
        orders = [
            {
                'id': o.id,
                'order_number': f"ORD-{o.id:06d}",
                'customer': (getattr(o.user, 'name', '') or getattr(o.user, 'email', '') or 'Guest') if o.user_id else 'Guest',
                'status': o.status,
                'total': str(o.total_amount),
            }
            for o in Order.objects.filter(is_deleted=False).filter(cond)
            .select_related('user').order_by('-created_at')[:self.GROUP_CAP]
        ]

        products = [
            {'id': p.id, 'slug': p.slug, 'name': p.name, 'stock': p.stock,
             'price': str(p.price), 'is_active': p.is_active}
            for p in Product.objects.filter(name__icontains=q).order_by('name')[:self.GROUP_CAP]
        ]

        customers = [
            {'id': u.id,
             'name': (getattr(u, 'name', '') or f"{u.first_name} {u.last_name}".strip() or u.email),
             'email': u.email, 'phone': getattr(u, 'phone', '') or ''}
            for u in User.objects.filter(
                Q(email__icontains=q) | Q(name__icontains=q) |
                Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                Q(phone__icontains=q)
            ).order_by('-created_at')[:self.GROUP_CAP]
        ]

        coupons = [
            {'id': c.id, 'code': c.code, 'is_active': c.is_active}
            for c in Coupon.objects.filter(code__icontains=q)[:self.GROUP_CAP]
        ]

        return Response({'orders': orders, 'products': products,
                         'customers': customers, 'coupons': coupons})


# ==================== ADMIN CUSTOMER DIRECTORY ====================

class AdminCustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only customer directory for the admin panel: list with search and
    per-customer order totals, plus a detail view with full order history."""
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        from django.db.models import Count, Sum, Q as DQ
        from django.contrib.auth import get_user_model

        User = get_user_model()
        not_cancelled = DQ(orders__is_deleted=False) & ~DQ(orders__status='cancelled')
        qs = User.objects.annotate(
            order_count=Count('orders', filter=not_cancelled, distinct=True),
            total_spent=Sum('orders__total_amount', filter=not_cancelled),
        ).order_by('-created_at')

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                DQ(email__icontains=search) | DQ(name__icontains=search) |
                DQ(first_name__icontains=search) | DQ(last_name__icontains=search) |
                DQ(phone__icontains=search)
            )
        return qs

    def list(self, request):
        from .serializers import AdminCustomerListSerializer
        page = self.paginate_queryset(self.get_queryset())
        rows = [
            {**AdminCustomerListSerializer(u).data,
             'total_spent': str(u.total_spent or 0)}
            for u in page
        ]
        return self.get_paginated_response(rows)

    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        """Download the (optionally searched) customer list as CSV."""
        from .utils import csv_response
        from django.utils import timezone

        header = ['Name', 'Email', 'Phone', 'City', 'State',
                  'Orders', 'Total Spent', 'Customer Since']

        def rows():
            for u in self.get_queryset():
                name = (getattr(u, 'name', '') or
                        f"{u.first_name} {u.last_name}".strip() or u.email)
                yield [
                    name, u.email, getattr(u, 'phone', '') or '',
                    getattr(u, 'city', '') or '', getattr(u, 'state', '') or '',
                    u.order_count, u.total_spent or 0,
                    u.created_at.strftime('%Y-%m-%d') if u.created_at else '',
                ]

        return csv_response(
            f"customers-{timezone.now().strftime('%Y%m%d')}.csv", header, rows())

    def retrieve(self, request, pk=None):
        from .serializers import AdminCustomerListSerializer, AdminCustomerOrderSerializer

        user = get_object_or_404(self.get_queryset(), pk=pk)
        orders = Order.objects.filter(
            user=user, is_deleted=False).order_by('-created_at')[:50]
        data = AdminCustomerListSerializer(user).data
        data['total_spent'] = str(user.total_spent or 0)
        data['address'] = getattr(user, 'full_address', '') or getattr(user, 'address', '') or ''
        data['orders'] = AdminCustomerOrderSerializer(orders, many=True).data
        return Response(data)
