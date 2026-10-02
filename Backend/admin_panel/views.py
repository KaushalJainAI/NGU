from django.shortcuts import get_object_or_404

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from decimal import Decimal

from .models import DeletedRecord, Expense, ReceivableAccount, Coupon, Policy
from .recycle import RecycleBinDestroyMixin, RestoreConflict, restore_record
from .serializers import (
    ExpenseSerializer,
    ReceivableAccountSerializer,
    CouponSerializer,
    RecentOrderSerializer,
    PolicySerializer
)
from orders.models import Order
from products.models import Product, ProductCombo
from spices_backend.timeranges import range_filter


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

class ReceivableAccountViewSet(RecycleBinDestroyMixin, viewsets.ModelViewSet):
    """
    ViewSet to manage receivable accounts - admin only for security
    Protects payment collection accounts from unauthorized access
    """
    queryset = ReceivableAccount.objects.all()
    serializer_class = ReceivableAccountSerializer
    permission_classes = [IsAdminUser]
    recycle_kind = 'receivable_account'

    def recycle_label(self, instance):
        return f"{instance.account_holder_name} — {instance.upi_id}"


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


class CouponViewSet(RecycleBinDestroyMixin, viewsets.ModelViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]
    # Admin management list with no pagination UI: return every coupon so the
    # 13th+ isn't silently hidden by the global PAGE_SIZE. (Small, admin-only.)
    pagination_class = None
    # DELETE bins the coupon. `Order.coupon` is SET_NULL, so the orders that
    # used it are recorded in the snapshot and re-attached on restore.
    recycle_kind = 'coupon'

    def recycle_label(self, instance):
        if instance.discount_type == 'fixed':
            worth = f"₹{instance.discount_amount or 0} off"
        else:
            worth = f"{instance.discount_percent or 0}% off"
        return f"{instance.code} — {worth}"

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


class ExpenseViewSet(RecycleBinDestroyMixin, viewsets.ModelViewSet):
    """Admin-entered business expenses (no courier/gateway here — those come
    from orders/payments automatically, and entering them too would count them
    twice)."""

    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]
    # Small, admin-only list: return everything like coupons, not page 1 of N.
    pagination_class = None
    recycle_kind = 'expense'

    def recycle_label(self, instance):
        parts = [instance.date.isoformat(), instance.get_category_display(),
                 f"₹{instance.amount}"]
        if instance.vendor:
            parts.append(instance.vendor)
        return ' · '.join(parts)

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('category'):
            qs = qs.filter(category=params['category'])
        date_from = params.get('from')
        date_to = params.get('to')
        if date_from or date_to:
            from datetime import date as date_cls
            try:
                start = date_cls.fromisoformat(date_from) if date_from else None
            except ValueError:
                start = None
            try:
                end = date_cls.fromisoformat(date_to) if date_to else None
            except ValueError:
                end = None
            qs = qs.filter(**range_filter('date', start, end))
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        from .utils import csv_response
        from django.utils import timezone

        header = ['Date', 'Category', 'Vendor', 'Description', 'Amount',
                  'GST', 'ITC Eligible', 'Bill No', 'Payment Mode']

        def rows():
            for e in self.get_queryset():
                yield [e.date.isoformat(), e.get_category_display(), e.vendor,
                       e.description, f"{e.amount:.2f}", f"{e.gst_amount:.2f}",
                       'Yes' if e.itc_eligible else 'No', e.bill_number,
                       e.get_payment_mode_display()]

        return csv_response(
            f"expenses-{timezone.now().strftime('%Y%m%d')}.csv", header, rows())


class RecycleBinView(APIView):
    """GET the Recycle Bin entries for rows that were hard-deleted.

    Soft-deleted products, combos and orders are NOT here — they never left
    their own tables and the panel reads them from their own endpoints. This is
    everything else: coupons, reviews, expenses, gallery images, payment
    accounts and contact messages (see admin_panel/recycle.py).

    The `payload` is deliberately not returned: it can hold bank details and
    customer messages, and the list only needs enough to recognise the row.
    """

    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        from datetime import timedelta
        from django.conf import settings

        retention = getattr(settings, 'RECYCLE_BIN_RETENTION_DAYS', 30)
        records = DeletedRecord.objects.select_related('deleted_by')
        items = []
        for record in records:
            purge_at = (record.deleted_at + timedelta(days=retention)
                        if retention > 0 else None)
            items.append({
                'id': record.id,
                'kind': record.kind,
                'label': record.label,
                'preview_url': record.preview_url,
                'deleted_at': record.deleted_at,
                'deleted_by': getattr(record.deleted_by, 'email', None),
                'purge_at': purge_at,
            })
        return Response({'retention_days': retention, 'items': items})


class RecycleBinRestoreView(APIView):
    """POST: put one binned row back under its original id."""

    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    def post(self, request, pk):
        record = get_object_or_404(DeletedRecord, pk=pk)
        try:
            restore_record(record)
        except RestoreConflict as exc:
            return Response({'success': False, 'error': str(exc)},
                            status=status.HTTP_409_CONFLICT)
        return Response({'success': True, 'kind': record.kind, 'label': record.label})


class BooksSummaryView(APIView):
    """Monthly books estimate: net sales, cash, costs, profit, GST to pay."""

    permission_classes = [IsAdminUser]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        from datetime import date as date_cls
        from django.utils import timezone
        from .books import monthly_summary

        today = timezone.localdate()
        try:
            date_from = date_cls.fromisoformat(request.query_params['from'])
        except (KeyError, ValueError):
            date_from = today.replace(day=1)
        try:
            date_to = date_cls.fromisoformat(request.query_params['to'])
        except (KeyError, ValueError):
            date_to = today
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return Response({'from': date_from.isoformat(), 'to': date_to.isoformat(),
                         **monthly_summary(date_from, date_to)})


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

        recent_orders_qs = Order.objects.order_by('-created_at')[:8]
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
        from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
        from django.utils import timezone
        from datetime import timedelta
        from assistant.models import AssistantConversation, AssistantMessage
        from support.models import ContactSubmission

        cache_key = 'ngu:dashboard:actions:v2'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        now = timezone.now()
        # localdate(), NOT now.date(). `timezone.now()` is UTC-aware, so .date()
        # yields the UTC calendar date while range_filter interprets the bounds
        # in TIME_ZONE (Asia/Kolkata). Between 00:00 and 05:30 IST the two
        # disagree, and every "today" figure on this dashboard — revenue, GST,
        # delivery margin — silently reported the PREVIOUS day.
        today = timezone.localdate()

        # New orders the admin can act on: pending AND actually payable/paid
        # (an ONLINE order still waiting for payment isn't confirmable yet).
        confirmable = Order.objects.filter(
            is_deleted=False, status='pending',
        ).filter(Q(payment_method='COD') | Q(payment_status='paid'))

        to_ship = Order.objects.filter(
            is_deleted=False, status__in=['confirmed', 'processing'])

        # Per SIZE (products.availability): a 500 g pack running out is low stock
        # even while the default size is healthy. The headline counts PRODUCTS so
        # it matches the Products page filter the dashboard links to; the list
        # names the five lowest sizes.
        from products.availability import low_stock_sizes
        low_sizes = low_stock_sizes()
        low_stock_items = [
            {'id': v.product_id, 'variant_id': v.id, 'name': v.product.name,
             'size': v.formatted_weight, 'stock': v.stock}
            for v in low_sizes[:5]
        ]
        low_stock_count = low_sizes.order_by().values('product_id').distinct().count()

        chats_waiting = AssistantConversation.objects.filter(
            needs_human=True, status='active').count()

        # "Unread" chats: nobody has answered the customer's last message yet.
        # There is no per-thread read flag, so this is derived — an active thread
        # whose most recent visible turn is the customer's. Threads already
        # counted in chats_waiting are excluded so the two cards don't overlap.
        last_role = AssistantMessage.objects.filter(
            conversation=OuterRef('pk'),
            role__in=['user', 'assistant', 'admin'],
        ).order_by('-created_at', '-id').values('role')[:1]
        unread_chats = AssistantConversation.objects.filter(
            status='active', needs_human=False,
        ).annotate(last_role=Subquery(last_role)).filter(last_role='user').count()

        new_contacts = ContactSubmission.objects.filter(status='new').count()

        ttl = getattr(settings, 'PAYMENT_STUCK_TTL_MINUTES', 15)
        stuck_payments = Order.objects.filter(
            is_deleted=False,
            payment_method='ONLINE',
            payment_status__in=['pending', 'processing'],
            status='pending',
            created_at__lt=now - timedelta(minutes=ttl),
        ).count()

        today_orders = Order.objects.filter(
            is_deleted=False, **range_filter('created_at', today, today),
        ).exclude(status='cancelled')
        # Revenue stays GROSS (what was actually collected) so it reconciles
        # against Razorpay settlements. The GST and delivery components are
        # surfaced ALONGSIDE it rather than deducted from it.
        today_stats = today_orders.aggregate(
            revenue=Sum('total_amount'),
            # Output tax = goods GST + the 18% on delivery. `tax` alone
            # under-reports every order that paid for shipping.
            gst=Sum(F('tax') + F('shipping_tax')),
            shipping_collected=Sum('shipping_charge'),
            shipping_cost=Sum('shipping_cost'),
        )
        # Month-to-date GST, because GST is filed monthly — a today-only figure
        # is useless for the return the owner actually has to file.
        month_start = today.replace(day=1)
        mtd_agg = Order.objects.filter(
            is_deleted=False, **range_filter('created_at', month_start),
        ).exclude(status='cancelled').aggregate(
            gst=Sum(F('tax') + F('shipping_tax')), revenue=Sum('total_amount'))
        mtd_gst = mtd_agg['gst'] or 0
        mtd_revenue = mtd_agg['revenue'] or 0

        # COD cash the couriers are still holding: dispatched or delivered COD
        # orders nobody has confirmed payment on. A point-in-time figure, so it
        # is computed live rather than rolled up. `aged` is the slice past a week,
        # which is the part worth chasing.
        cod_pending_qs = Order.objects.filter(
            is_deleted=False, payment_method='COD', cod_paid_at__isnull=True,
            status__in=['shipped', 'delivering', 'delivered'],
        )
        cod_pending = cod_pending_qs.aggregate(
            amount=Sum('total_amount'), n=Count('id'))
        cod_aged = cod_pending_qs.filter(
            created_at__lt=now - timedelta(days=7)).count()
        cod_collected_today = Order.objects.filter(
            is_deleted=False, **range_filter('cod_paid_at', today, today),
        ).aggregate(amount=Sum('total_amount'))['amount'] or 0

        # Razorpay's cut, month to date. Two separate reasons this is here:
        # the fee is a real expense that was invisible (margin was overstated by
        # it), and `gateway_tax` is GST WE paid on a service — input tax credit,
        # deductible from the output tax below. Reported gross so the ITC figure
        # can be carried into whatever books actually file the return.
        from payments.models import Payment
        mtd_gw = Payment.objects.filter(
            status__in=['completed', 'refunded'],
            order__is_deleted=False,
            **range_filter('order__created_at', month_start),
        ).aggregate(fee=Sum('gateway_fee'), tax=Sum('gateway_tax'))
        mtd_gateway_fee = mtd_gw['fee'] or 0
        mtd_gateway_tax = mtd_gw['tax'] or 0
        # Refunds reverse output tax in the period the refund happened, so they
        # are counted by REFUND date — not by the date of the order being
        # refunded, which may sit in an already-filed month.
        from orders.refunds import refunded_totals_between
        mtd_ref = refunded_totals_between(month_start, today)
        today_ref = refunded_totals_between(today, today)
        mtd_gst_refunded = mtd_ref['tax'] or 0
        today_gst_refunded = today_ref['tax'] or 0
        shipping_collected = today_stats['shipping_collected'] or 0
        shipping_cost = today_stats['shipping_cost'] or 0
        delivered_count = today_orders.filter(shipping_cost__gt=0).count()

        # WP5 — "real" sales: an ONLINE order counts only once it is paid; a
        # COD order counts from placement.
        from decimal import ROUND_HALF_UP
        PAISA = Decimal('0.01')
        TENTH = Decimal('0.1')
        ONLINE = ['ONLINE', 'razorpay']

        def real_orders(start, end):
            return (Order.objects
                    .filter(is_deleted=False, **range_filter('created_at', start, end))
                    .exclude(status='cancelled')
                    .exclude(payment_method__in=ONLINE,
                             payment_status__in=['pending', 'processing', 'failed', 'rejected']))

        def _money(value):
            return Decimal(str(value or 0)).quantize(PAISA, rounding=ROUND_HALF_UP)

        def _pct(current, earlier):
            if Decimal(str(earlier or 0)) == 0:
                return None
            cur = Decimal(str(current or 0))
            prev = Decimal(str(earlier or 0))
            return float(((cur - prev) / prev * 100).quantize(TENTH, rounding=ROUND_HALF_UP))

        real_today_qs = real_orders(today, today)
        today_sales = _money(real_today_qs.aggregate(s=Sum('total_amount'))['s'])
        today_real_orders = real_today_qs.count()
        if today_real_orders:
            today_aov = (today_sales / today_real_orders).quantize(PAISA, rounding=ROUND_HALF_UP)
        else:
            today_aov = Decimal('0.00')
        today_online_received = _money(
            real_today_qs.filter(payment_method__in=ONLINE).aggregate(s=Sum('total_amount'))['s'])
        today_cod_booked = _money(
            real_today_qs.filter(payment_method='COD').aggregate(s=Sum('total_amount'))['s'])
        last_week_day = today - timedelta(days=7)
        last_week_same_day_sales = _money(
            real_orders(last_week_day, last_week_day).aggregate(s=Sum('total_amount'))['s'])
        today_sales_delta_pct = _pct(today_sales, last_week_same_day_sales)
        mtd_sales = _money(real_orders(month_start, today).aggregate(s=Sum('total_amount'))['s'])
        prev_month_last = month_start - timedelta(days=1)
        prev_month_start = prev_month_last.replace(day=1)
        prev_mtd_end = prev_month_start + timedelta(days=(today - month_start).days)
        if prev_mtd_end > prev_month_last:
            prev_mtd_end = prev_month_last
        prev_mtd_sales = _money(
            real_orders(prev_month_start, prev_mtd_end).aggregate(s=Sum('total_amount'))['s'])
        mtd_sales_delta_pct = _pct(mtd_sales, prev_mtd_sales)
        orders_unshipped_aged = Order.objects.filter(
            is_deleted=False, status__in=['confirmed', 'processing'],
            created_at__lt=now - timedelta(hours=48),
        ).filter(Q(payment_method='COD') | Q(payment_status='paid')).count()
        from products.availability import out_of_stock_sizes
        out_of_stock_count = (
            out_of_stock_sizes().order_by().values('product_id').distinct().count())
        invoices_missing = Order.objects.filter(
            is_deleted=False, invoice__isnull=True,
        ).exclude(status='cancelled').filter(
            Q(payment_status__in=['paid', 'refunded'])
            | Q(status__in=['shipped', 'delivering', 'delivered'])).count()
        failed_payments_today = Order.objects.filter(
            is_deleted=False, **range_filter('created_at', today, today),
            payment_method__in=ONLINE, payment_status__in=['failed', 'rejected']).count()
        from orders.gst_reports import unclassified_products
        unclassified_hsn_count = unclassified_products().count()
        week_start = today - timedelta(days=6)
        from orders.models import OrderItem
        top_rows = (OrderItem.objects
                    .filter(order__in=real_orders(week_start, today))
                    .values('product_name')
                    .annotate(units=Sum('quantity'), revenue=Sum('final_price'))
                    .order_by('-revenue')[:5])
        top_products_7d = [
            {'name': r['product_name'], 'units': r['units'],
             'revenue': str(_money(r['revenue']))}
            for r in top_rows
        ]
        # WP6 — GST on the INVOICE basis: what was invoiced this month, what
        # credit notes reversed, and the net held. Invoices by issue date, not
        # orders by order date.
        from orders.gst_ledger import period_summary as _gst_period_summary
        _mtd_ledger = _gst_period_summary(month_start, today)
        mtd_gst_collected = _mtd_ledger['invoices']['tax']
        mtd_gst_refunded = _mtd_ledger['credit_notes']['tax']
        mtd_gst_net_collected = _mtd_ledger['net']['tax']

        data = {
            'orders_to_confirm': confirmable.count(),
            'orders_to_ship': to_ship.count(),
            'low_stock_count': low_stock_count,
            'low_stock_items': low_stock_items,
            'chats_waiting': chats_waiting,
            'unread_chats': unread_chats,
            'new_contacts': new_contacts,
            'stuck_payments': stuck_payments,
            'today_orders': today_orders.count(),
            'today_revenue': str(today_stats['revenue'] or 0),
            # Gross revenue beside a separate refunds figure reads as net to
            # almost everyone, so the netted number is given explicitly.
            # `today_revenue` stays GROSS — it is what reconciles against
            # gateway settlements.
            'today_net_revenue': str(
                (today_stats['revenue'] or 0) - (today_ref['amount'] or 0)),
            'mtd_net_revenue': str(mtd_revenue - (mtd_ref['amount'] or 0)),
            'mtd_revenue': str(mtd_revenue),
            # What was SOLD, net of the tax collected on it — revenue minus
            # output tax. This is the taxable value of the period's supplies
            # (goods plus the net delivery charge), and it reconciles with the
            # taxable-value total on the HSN summary screen.
            'today_taxable_sales': str(
                (today_stats['revenue'] or 0) - (today_stats['gst'] or 0)),
            'mtd_taxable_sales': str(mtd_revenue - mtd_gst),
            # GST COLLECTED from customers on those sales (output tax). This is
            # a fact about money we took, and it is deliberately the ONLY kind
            # of tax number this system reports. What is finally REMITTED is
            # output tax minus input credit on purchases (ingredients,
            # packaging, courier, rent, gateway fees) — NGU tracks no purchase
            # ledger, so that figure is the owner's/accountant's to compute in
            # their books. Nothing here should be named or read as "payable".
            'today_gst_collected': str(today_stats['gst'] or 0),
            'mtd_gst_collected': str(mtd_gst_collected),
            # GST reversed by credit notes, counted on the day the note was issued.
            'today_gst_refunded': str(today_gst_refunded),
            'mtd_gst_refunded': str(mtd_gst_refunded),
            # Collected − reversed: the net tax actually held for the period.
            # The number the GST tile leads with.
            'today_gst_net_collected': str(
                (today_stats['gst'] or 0) - today_gst_refunded),
            'mtd_gst_net_collected': str(mtd_gst_net_collected),
            'today_refunds': str(today_ref['amount'] or 0),
            'mtd_refunds': str(mtd_ref['amount'] or 0),
            # Delivery economics. `shipping_cost` is admin-entered per order, so
            # the average covers only orders where it was actually recorded —
            # averaging over all orders would understate it with silent zeros.
            'today_shipping_collected': str(shipping_collected),
            'today_shipping_cost': str(shipping_cost),
            'today_shipping_margin': str(shipping_collected - shipping_cost),
            'today_avg_shipping_cost': str(
                round(shipping_cost / delivered_count, 2) if delivered_count else 0
            ),
            'today_shipping_cost_recorded': delivered_count,
            # COD cash ledger. Separate from revenue/GST above, which accrue at
            # order date: this is purely "has the money arrived yet".
            'cod_pending_amount': str(cod_pending['amount'] or 0),
            'cod_pending_count': cod_pending['n'] or 0,
            'cod_pending_aged_count': cod_aged,
            'cod_collected_today': str(cod_collected_today),
            # Gateway cost MTD. `mtd_gateway_tax` is GST WE PAID on Razorpay's
            # fee — one line of input credit that happens to be evidenced in
            # this system. It is reported on its OWN, not folded into a
            # payable: it is a single input among many we don't see, so netting
            # it off here would produce a number that looks filed-ready and
            # isn't. Carry it into the books that do the return.
            'mtd_gateway_fee': str(mtd_gateway_fee),
            'mtd_gateway_tax': str(mtd_gateway_tax),
            # WP5 — rebuilt dashboard: real (paid/booked) sales with comparisons.
            'today_sales': str(today_sales),
            'today_real_orders': today_real_orders,
            'today_aov': str(today_aov),
            'today_online_received': str(today_online_received),
            'today_cod_booked': str(today_cod_booked),
            'last_week_same_day_sales': str(last_week_same_day_sales),
            'today_sales_delta_pct': today_sales_delta_pct,
            'mtd_sales': str(mtd_sales),
            'prev_mtd_sales': str(prev_mtd_sales),
            'mtd_sales_delta_pct': mtd_sales_delta_pct,
            'orders_unshipped_aged': orders_unshipped_aged,
            'out_of_stock_count': out_of_stock_count,
            'invoices_missing': invoices_missing,
            'failed_payments_today': failed_payments_today,
            'unclassified_hsn_count': unclassified_hsn_count,
            'top_products_7d': top_products_7d,
        }
        # Deprecated aliases, kept only so a panel build from before the
        # "collected, not payable" rename keeps rendering during a rolling
        # deploy. Delete once the admin image is rolled out everywhere.
        data['today_gst_payable'] = data['today_gst_net_collected']
        data['mtd_gst_payable'] = data['mtd_gst_net_collected']
        data['mtd_gst_payable_after_known_itc'] = str(
            mtd_gst_net_collected - mtd_gateway_tax)
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
        from django.db.models import Count, F, Sum, Q as DQ
        from django.contrib.auth import get_user_model

        User = get_user_model()
        not_cancelled = DQ(orders__is_deleted=False) & ~DQ(orders__status='cancelled')
        qs = User.objects.annotate(
            order_count=Count('orders', filter=not_cancelled, distinct=True),
            # GROSS lifetime spend — what the customer actually paid us.
            total_spent=Sum('orders__total_amount', filter=not_cancelled),
            # How much of that was GST passed through to the government, so the
            # "best customer" figure can be read net of tax when that matters.
            # Goods GST + delivery GST: `tax` alone misses every delivery fee.
            total_gst=Sum(F('orders__tax') + F('orders__shipping_tax'),
                          filter=not_cancelled),
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
             'total_spent': str(u.total_spent or 0),
             'total_gst': str(u.total_gst or 0),
             'total_spent_ex_gst': str((u.total_spent or 0) - (u.total_gst or 0))}
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
