"""
Recompute the analytics rollup tables from source signals.

Idempotent by design: for each target date it deletes that day's rollup rows
and recomputes them, so it is safe to run as often as you like (e.g. every few
minutes for "today" plus a nightly full pass). It also drains the anonymous
Redis counters into DailyAnonStat.

Usage:
    python manage.py rollup_analytics                 # yesterday + today
    python manage.py rollup_analytics --date 2026-06-20
    python manage.py rollup_analytics --days 30       # backfill last 30 days
"""
from datetime import date as date_cls, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, F, Min, Sum
from django.utils import timezone

from analytics.anon import flush_anon_to_db
from analytics.models import (
    DailyFunnelRollup, DailySalesRollup, SearchTermStat, UserEvent,
)
from orders.models import Order, OrderItem
from spices_backend.timeranges import day_range

# Orders in these statuses are excluded from sales KPIs (not realised revenue).
EXCLUDED_ORDER_STATUSES = ['cancelled']


def countable_orders():
    """Orders that count towards sales KPIs.

    Excludes cancelled orders (never realised) AND soft-deleted ones. The latter
    matters more than it looks: an order in the admin Recycle Bin is already
    hidden from every dashboard query (`admin_panel/views.py` filters
    `is_deleted=False`), so counting it here made Insights and the dashboard
    report different revenue for the same day. Worse, `purge_recycle_bin` hard-
    deletes the row 30 days later, so the revenue would silently disappear from
    any period recomputed after that while surviving in periods already stored.
    """
    return Order.objects.filter(is_deleted=False).exclude(
        status__in=EXCLUDED_ORDER_STATUSES)


class Command(BaseCommand):
    help = "Recompute analytics rollup tables (sales, funnel, search) for given dates."

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Single date to roll up (YYYY-MM-DD).')
        parser.add_argument('--days', type=int,
                            help='Backfill: roll up the last N days (inclusive of today).')

    def handle(self, *args, **options):
        dates = self._target_dates(options)
        for day in dates:
            with transaction.atomic():
                sales = self._rollup_sales(day)
                funnel = self._rollup_funnel(day)
                search = self._rollup_search(day)
            flushed = flush_anon_to_db(day)
            self.stdout.write(
                f"{day}: sales(orders={sales['orders']}, revenue={sales['revenue']}) "
                f"funnel={funnel} search_terms={search} anon_counters={flushed}"
            )
        self.stdout.write(self.style.SUCCESS(f"Rolled up {len(dates)} day(s)."))

    # -- date selection ------------------------------------------------------

    def _target_dates(self, options):
        today = timezone.localdate()
        if options.get('date'):
            try:
                return [date_cls.fromisoformat(options['date'])]
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")
        if options.get('days'):
            n = options['days']
            return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]
        # Default: yesterday (now final) + today (partial).
        return [today - timedelta(days=1), today]

    def _day_range(self, day):
        """Timezone-aware [start, end) bounds for a local calendar day."""
        return day_range(day)

    # -- rollups -------------------------------------------------------------

    def _rollup_sales(self, day):
        start, end = self._day_range(day)
        orders_qs = countable_orders().filter(
            created_at__gte=start, created_at__lt=end)

        agg = orders_qs.aggregate(
            orders=Count('id'),
            revenue=Sum('total_amount'),
            coupon_discount=Sum('discount_amount'),
            # Output tax is goods GST PLUS the 18% on delivery. Summing `tax`
            # alone silently under-reports the liability by the shipping GST on
            # every order under the free-shipping threshold.
            gst_collected=Sum(F('tax') + F('shipping_tax')),
            shipping_collected=Sum('shipping_charge'),
            shipping_tax_collected=Sum('shipping_tax'),
            shipping_cost=Sum('shipping_cost'),
        )
        orders_count = agg['orders'] or 0
        revenue = agg['revenue'] or 0
        coupon_discount = agg['coupon_discount'] or 0
        gst_collected = agg['gst_collected'] or 0
        shipping_collected = agg['shipping_collected'] or 0
        shipping_cost = agg['shipping_cost'] or 0

        units = (
            OrderItem.objects
            .filter(order__in=orders_qs)
            .aggregate(u=Sum('quantity'))['u'] or 0
        )
        coupon_orders = orders_qs.filter(coupon__isnull=False).count()
        aov = (revenue / orders_count) if orders_count else 0

        # New vs returning: a customer is "new" on the day their *first ever*
        # (non-excluded) order falls. Everyone else who ordered today is returning.
        buyer_ids = list(orders_qs.values_list('user_id', flat=True).distinct())
        new_customers = 0
        if buyer_ids:
            first_order = (
                countable_orders()
                .filter(user_id__in=buyer_ids)
                .values('user_id')
                .annotate(first=Min('created_at'))
            )
            new_customers = sum(1 for r in first_order if start <= r['first'] < end)
        returning_customers = max(len(buyer_ids) - new_customers, 0)

        # Refunds are bucketed by the day the REFUND happened, not the day of the
        # sale — the order being refunded may be months old, and its GST was
        # already reported (possibly filed) in that earlier period.
        from orders.refunds import refunded_totals_between
        refunded = refunded_totals_between(day, day)

        # COD cash is bucketed by the day it was CONFIRMED, for the same reason
        # as refunds: the courier usually remits days after delivery, so the
        # order being settled is normally not one of today's. This is the cash
        # ledger, deliberately independent of the revenue/GST figures above,
        # which accrue at order date and do not move when the money arrives.
        cod_collected = (
            countable_orders()
            .filter(cod_paid_at__gte=start, cod_paid_at__lt=end)
            .aggregate(amt=Sum('total_amount'))['amt'] or 0
        )

        DailySalesRollup.objects.update_or_create(
            date=day,
            defaults={
                'refunds': refunded['amount'] or 0,
                'gst_refunded': refunded['tax'] or 0,
                'orders': orders_count,
                'units': units,
                'revenue': revenue,
                'gst_collected': gst_collected,
                'shipping_collected': shipping_collected,
                'shipping_tax_collected': agg['shipping_tax_collected'] or 0,
                'cod_collected': cod_collected,
                'shipping_cost': shipping_cost,
                'aov': aov,
                'coupon_orders': coupon_orders,
                'coupon_discount': coupon_discount,
                'new_customers': new_customers,
                'returning_customers': returning_customers,
            },
        )
        return {'orders': orders_count, 'revenue': revenue}

    def _rollup_funnel(self, day):
        start, end = self._day_range(day)
        DailyFunnelRollup.objects.filter(date=day).delete()
        rows = (
            UserEvent.objects
            .filter(created_at__gte=start, created_at__lt=end)
            .values('event_type')
            .annotate(c=Count('id'))
        )
        objs = [
            DailyFunnelRollup(date=day, event_type=r['event_type'], count=r['c'])
            for r in rows
        ]
        DailyFunnelRollup.objects.bulk_create(objs)
        return len(objs)

    def _rollup_search(self, day):
        start, end = self._day_range(day)
        SearchTermStat.objects.filter(date=day).delete()
        events = (
            UserEvent.objects
            .filter(event_type='search', created_at__gte=start, created_at__lt=end)
            .values_list('query', 'metadata')
        )
        # Aggregate in Python so we can read zero-result from the JSON metadata.
        agg = {}
        for query, metadata in events:
            term = (query or '').strip().lower()
            if not term:
                continue
            meta = metadata or {}
            zero = bool(meta.get('zero')) or meta.get('result_count') == 0
            entry = agg.setdefault(term, {'count': 0, 'zero': False})
            entry['count'] += 1
            # A term is flagged zero-result if any of its occurrences had none.
            entry['zero'] = entry['zero'] or zero
        objs = [
            SearchTermStat(date=day, term=term, count=v['count'], zero_result=v['zero'])
            for term, v in agg.items()
        ]
        SearchTermStat.objects.bulk_create(objs)
        return len(objs)
