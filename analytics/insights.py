"""
Read-time aggregation for the admin Insights dashboard.

Pure query functions (no HTTP) so they're easy to unit-test. They read the
pre-computed rollup tables where possible, and fall back to live queries for
things not rolled up (top products, viewed-not-bought, geo). Each returns a
plain dict ready to serialize.

Date handling: ``date_from``/``date_to`` are inclusive calendar dates.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from orders.models import Order, OrderItem
from spices_backend.timeranges import range_filter
from .models import (
    DailyAnonStat, DailyFunnelRollup, DailySalesRollup, SearchTermStat, UserEvent, UserGeo,
)

EXCLUDED_ORDER_STATUSES = ['cancelled']

# Soft-deleted orders (admin Recycle Bin) are excluded everywhere alongside
# cancelled ones — see `rollup_analytics.countable_orders()` for why. The live
# queries below must apply the same filter as the rollups, or the "top products"
# panel and the revenue chart on the same screen disagree.

# Ordered funnel stages we surface (logged-in journey).
FUNNEL_STAGES = ['view', 'add_to_cart', 'checkout_started', 'purchase']
ANON_FUNNEL_STAGES = ['page_view', 'product_view', 'add_to_cart', 'checkout_started', 'checkout_completed']


# -- helpers ----------------------------------------------------------------

def default_range():
    """Last 30 days, inclusive."""
    today = timezone.localdate()
    return today - timedelta(days=29), today


def _bucket_key(day, granularity):
    if granularity == 'month':
        return day.replace(day=1).isoformat()
    if granularity == 'week':
        return (day - timedelta(days=day.weekday())).isoformat()
    return day.isoformat()


def _previous_range(date_from, date_to):
    """The immediately preceding window of equal length (for PoP deltas)."""
    span = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)
    return prev_from, prev_to


def _pct_delta(current, previous):
    if not previous:
        return None  # undefined (no prior baseline)
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def _f(value):
    return float(value or 0)


# -- sales ------------------------------------------------------------------

def sales(date_from, date_to, granularity='day'):
    rows = DailySalesRollup.objects.filter(date__gte=date_from, date__lte=date_to)

    buckets = defaultdict(lambda: {'revenue': 0.0, 'orders': 0, 'units': 0,
                                   'gst_collected': 0.0})
    # `revenue` stays GROSS. gst_collected / shipping_* are reported alongside
    # it (not deducted) so the figure still ties out to gateway settlements.
    totals = {'revenue': 0.0, 'orders': 0, 'units': 0,
              'coupon_orders': 0, 'coupon_discount': 0.0,
              'new_customers': 0, 'returning_customers': 0,
              'gst_collected': 0.0, 'shipping_collected': 0.0, 'shipping_cost': 0.0,
              'refunds': 0.0, 'gst_refunded': 0.0}
    for r in rows:
        b = buckets[_bucket_key(r.date, granularity)]
        b['revenue'] += _f(r.revenue)
        b['orders'] += r.orders
        b['units'] += r.units
        b['gst_collected'] += _f(r.gst_collected)
        totals['revenue'] += _f(r.revenue)
        totals['orders'] += r.orders
        totals['units'] += r.units
        totals['coupon_orders'] += r.coupon_orders
        totals['coupon_discount'] += _f(r.coupon_discount)
        totals['new_customers'] += r.new_customers
        totals['returning_customers'] += r.returning_customers
        totals['gst_collected'] += _f(r.gst_collected)
        totals['shipping_collected'] += _f(r.shipping_collected)
        totals['shipping_cost'] += _f(r.shipping_cost)
        totals['refunds'] += _f(r.refunds)
        totals['gst_refunded'] += _f(r.gst_refunded)

    series = [
        {'bucket': k, 'revenue': round(v['revenue'], 2),
         'orders': v['orders'], 'units': v['units'],
         'gst_collected': round(v['gst_collected'], 2)}
        for k, v in sorted(buckets.items())
    ]
    totals['shipping_margin'] = round(
        totals['shipping_collected'] - totals['shipping_cost'], 2)
    aov = round(totals['revenue'] / totals['orders'], 2) if totals['orders'] else 0

    # Period-over-period deltas against the preceding equal window.
    prev_from, prev_to = _previous_range(date_from, date_to)
    prev = DailySalesRollup.objects.filter(
        date__gte=prev_from, date__lte=prev_to
    ).aggregate(revenue=Sum('revenue'), orders=Sum('orders'))
    prev_rev, prev_orders = _f(prev['revenue']), prev['orders'] or 0

    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat(),
                  'granularity': granularity},
        'kpis': {
            'revenue': round(totals['revenue'], 2),
            # GROSS revenue with refunds sitting in a separate field reads as NET
            # to almost everyone, so the netted figure is computed here rather
            # than left as an exercise. `revenue` stays gross because it is what
            # reconciles against gateway settlements; this is what the business
            # actually kept.
            'net_revenue': round(totals['revenue'] - totals['refunds'], 2),
            'orders': totals['orders'],
            'units': totals['units'],
            'aov': aov,
            'coupon_orders': totals['coupon_orders'],
            'coupon_discount': round(totals['coupon_discount'], 2),
            'revenue_delta_pct': _pct_delta(totals['revenue'], prev_rev),
            'orders_delta_pct': _pct_delta(totals['orders'], prev_orders),
            # What was sold, net of the tax collected on it — the taxable value
            # of the period's supplies. Pairs with `gst_collected` to answer
            # "how much did we sell, and how much tax did we take on it".
            'taxable_sales': round(totals['revenue'] - totals['gst_collected'], 2),
            # Reported ALONGSIDE gross revenue, never deducted from it.
            # `gst_collected` is output tax collected from customers — a
            # money-taken fact, not an amount to remit (that is this minus
            # input credit on purchases, which we deliberately don't model).
            'gst_collected': round(totals['gst_collected'], 2),
            'refunds': round(totals['refunds'], 2),
            'gst_refunded': round(totals['gst_refunded'], 2),
            # Net tax held for the period: collected − reversed by refunds.
            'net_gst_collected': round(totals['gst_collected'] - totals['gst_refunded'], 2),
            'shipping_collected': round(totals['shipping_collected'], 2),
            'shipping_cost': round(totals['shipping_cost'], 2),
            'shipping_margin': totals['shipping_margin'],
        },
        'series': series,
        'top_products': _top_products(date_from, date_to),
        'top_categories': _top_categories(date_from, date_to),
    }


def _order_items_in_range(date_from, date_to):
    return (
        OrderItem.objects
        .filter(**range_filter('order__created_at', date_from, date_to))
        .filter(order__is_deleted=False)
        .exclude(order__status__in=EXCLUDED_ORDER_STATUSES)
    )


def _top_products(date_from, date_to, limit=10):
    rows = (
        _order_items_in_range(date_from, date_to)
        .values('product_id', 'product_name')
        .annotate(units=Sum('quantity'), revenue=Sum('final_price'))
        .order_by('-revenue')[:limit]
    )
    return [
        {'product_id': r['product_id'], 'name': r['product_name'],
         'units': r['units'] or 0, 'revenue': round(_f(r['revenue']), 2)}
        for r in rows
    ]


def _top_categories(date_from, date_to, limit=10):
    rows = (
        _order_items_in_range(date_from, date_to)
        .filter(product__category__isnull=False)
        .values('product__category_id', 'product__category__name')
        .annotate(units=Sum('quantity'), revenue=Sum('final_price'))
        .order_by('-revenue')[:limit]
    )
    return [
        {'category_id': r['product__category_id'], 'name': r['product__category__name'],
         'units': r['units'] or 0, 'revenue': round(_f(r['revenue']), 2)}
        for r in rows
    ]


# -- funnel (logged-in) -----------------------------------------------------

def funnel(date_from, date_to):
    rows = (
        DailyFunnelRollup.objects
        .filter(date__gte=date_from, date__lte=date_to)
        .values('event_type')
        .annotate(c=Sum('count'))
    )
    counts = {r['event_type']: r['c'] for r in rows}
    stages = []
    base = counts.get(FUNNEL_STAGES[0], 0)
    prev = None
    for stage in FUNNEL_STAGES:
        n = counts.get(stage, 0)
        stages.append({
            'stage': stage,
            'count': n,
            'pct_of_top': round(n / base * 100, 1) if base else None,
            'step_conversion_pct': round(n / prev * 100, 1) if prev else None,
        })
        prev = n if n else prev
    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'stages': stages,
        'all_event_counts': counts,
    }


# -- search -----------------------------------------------------------------

def search(date_from, date_to, limit=20):
    base = SearchTermStat.objects.filter(date__gte=date_from, date__lte=date_to)
    top = (
        base.values('term')
        .annotate(c=Sum('count'))
        .order_by('-c')[:limit]
    )
    zero = (
        base.filter(zero_result=True)
        .values('term')
        .annotate(c=Sum('count'))
        .order_by('-c')[:limit]
    )
    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'top_terms': [{'term': r['term'], 'count': r['c']} for r in top],
        'zero_result_terms': [{'term': r['term'], 'count': r['c']} for r in zero],
        'viewed_not_bought': _viewed_not_bought(date_from, date_to, limit),
    }


def _viewed_not_bought(date_from, date_to, limit=10):
    """Products with view events but no purchase events over the window."""
    events = (
        UserEvent.objects
        .filter(product__isnull=False, event_type__in=['view', 'purchase'],
                **range_filter('created_at', date_from, date_to))
        .values('product_id', 'product__name', 'event_type')
        .annotate(c=Count('id'))
    )
    views, purchases, names = defaultdict(int), defaultdict(int), {}
    for r in events:
        names[r['product_id']] = r['product__name']
        if r['event_type'] == 'view':
            views[r['product_id']] += r['c']
        else:
            purchases[r['product_id']] += r['c']
    rows = [
        {'product_id': pid, 'name': names.get(pid, ''), 'views': v}
        for pid, v in views.items() if purchases.get(pid, 0) == 0
    ]
    rows.sort(key=lambda x: x['views'], reverse=True)
    return rows[:limit]


# -- customers (logged-in) --------------------------------------------------

def customers(date_from, date_to, granularity='day'):
    rows = DailySalesRollup.objects.filter(date__gte=date_from, date__lte=date_to)
    buckets = defaultdict(lambda: {'new': 0, 'returning': 0})
    total_new = total_returning = 0
    for r in rows:
        b = buckets[_bucket_key(r.date, granularity)]
        b['new'] += r.new_customers
        b['returning'] += r.returning_customers
        total_new += r.new_customers
        total_returning += r.returning_customers

    series = [
        {'bucket': k, 'new': v['new'], 'returning': v['returning']}
        for k, v in sorted(buckets.items())
    ]
    total_buyers = total_new + total_returning
    repeat_rate = round(total_returning / total_buyers * 100, 1) if total_buyers else 0

    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat(),
                  'granularity': granularity},
        'kpis': {
            'new_customers': total_new,
            'returning_customers': total_returning,
            'repeat_rate_pct': repeat_rate,
        },
        'series': series,
        'geo': _customer_geo(),
        'top_customers': _top_customers(date_from, date_to),
    }


def _customer_geo(limit=15):
    rows = (
        UserGeo.objects.exclude(state='')
        .values('state')
        .annotate(c=Count('user_id'))
        .order_by('-c')[:limit]
    )
    return [{'state': r['state'], 'users': r['c']} for r in rows]


def _top_customers(date_from, date_to, limit=10):
    rows = (
        Order.objects
        .filter(**range_filter('created_at', date_from, date_to), is_deleted=False)
        .exclude(status__in=EXCLUDED_ORDER_STATUSES)
        .values('user_id', 'user__email')
        .annotate(revenue=Sum('total_amount'), orders=Count('id'))
        .order_by('-revenue')[:limit]
    )
    return [
        {'user_id': r['user_id'], 'email': r['user__email'],
         'revenue': round(_f(r['revenue']), 2), 'orders': r['orders']}
        for r in rows
    ]


# -- anonymous (potential customers) ----------------------------------------

def anonymous(date_from, date_to):
    rows = DailyAnonStat.objects.filter(date__gte=date_from, date__lte=date_to)

    # metric -> total (dimension_key == '') and per-dimension breakdowns.
    metric_totals = defaultdict(int)
    by_device = defaultdict(int)
    by_state = defaultdict(int)
    by_source = defaultdict(int)
    for r in rows:
        if r.dimension_key == '':
            metric_totals[r.metric] += r.count
            continue
        prefix, _, value = r.dimension_key.partition(':')
        # Attribute breakdowns against page_view as the volume baseline.
        if r.metric == 'page_view':
            if prefix == 'device':
                by_device[value] += r.count
            elif prefix == 'state':
                by_state[value] += r.count
            elif prefix == 'source':
                by_source[value] += r.count

    # Macro funnel: ratios of aggregate stage counts (no per-visit path).
    base = metric_totals.get(ANON_FUNNEL_STAGES[0], 0)
    stages = []
    prev = None
    for stage in ANON_FUNNEL_STAGES:
        n = metric_totals.get(stage, 0)
        stages.append({
            'stage': stage,
            'count': n,
            'pct_of_top': round(n / base * 100, 1) if base else None,
            'step_conversion_pct': round(n / prev * 100, 1) if prev else None,
        })
        prev = n if n else prev

    def _top(d, key):
        return [{key: k, 'count': v} for k, v in sorted(d.items(), key=lambda x: -x[1])]

    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'totals': dict(metric_totals),
        'macro_funnel': stages,
        'by_device': _top(by_device, 'device'),
        'by_state': _top(by_state, 'state'),
        'by_source': _top(by_source, 'source'),
    }


# -- overview (landing tab: one round-trip headline) ------------------------

def overview(date_from, date_to, granularity='day'):
    """
    Compact headline for the dashboard landing tab. Composes the existing
    aggregations so the Overview is a single cached request instead of five.
    """
    s = sales(date_from, date_to, granularity)
    f = funnel(date_from, date_to)
    c = customers(date_from, date_to, granularity)
    a = anonymous(date_from, date_to)
    return {
        'range': {'from': date_from.isoformat(), 'to': date_to.isoformat(),
                  'granularity': granularity},
        'kpis': {
            'revenue': s['kpis']['revenue'],
            'revenue_delta_pct': s['kpis']['revenue_delta_pct'],
            'orders': s['kpis']['orders'],
            'orders_delta_pct': s['kpis']['orders_delta_pct'],
            'aov': s['kpis']['aov'],
            'repeat_rate_pct': c['kpis']['repeat_rate_pct'],
            'anon_page_views': a['totals'].get('page_view', 0),
        },
        'revenue_series': s['series'],
        'funnel': f['stages'],
        'top_products': s['top_products'][:5],
        'anon_by_device': a['by_device'],
        'anon_by_source': a['by_source'],
    }
