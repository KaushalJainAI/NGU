"""Read-only reporting tools for the ADMIN assistant persona.

These deliberately do what the customer tools (tools.py) must never do: read
ACROSS all customers and orders and expose business aggregates. That is safe
here ONLY because the admin-chat endpoint is gated by IsAdminUser AND the agent
is constructed with persona='admin', so a customer conversation can never reach
these functions.

Every tool is a parameterized ORM query — no raw SQL, no writes, no mutations.
The registry is read-only: there are NO action builders for the admin persona,
so the assistant can answer questions but never change anything.
"""
import logging
from datetime import timedelta

from django.db.models import Sum, Count, Q, F
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_LIST = 20
DEFAULT_LIST = 8

# Named reporting periods → number of days back (None = all time).
_PERIODS = {'today': 0, '7d': 6, '30d': 29, '90d': 89, 'all': None}


def _period_start(period):
    """Return the inclusive start date for a named period, or None for 'all'."""
    days = _PERIODS.get((period or '7d').strip().lower(), 6)
    if days is None:
        return None
    return timezone.now().date() - timedelta(days=days)


def _coerce_limit(args, default=DEFAULT_LIST):
    try:
        n = int(args.get('limit', default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, MAX_LIST))


def _order_number(order_id):
    return f'ORD-{order_id:06d}'


def admin_sales_summary(user, args):
    """Revenue, order count and average order value for a period (from the
    sales rollups, which already exclude cancelled orders)."""
    from analytics.models import DailySalesRollup

    period = args.get('period', '7d')
    start = _period_start(period)
    qs = DailySalesRollup.objects.all()
    if start is not None:
        qs = qs.filter(date__gte=start)
    agg = qs.aggregate(revenue=Sum('revenue'), orders=Sum('orders'), units=Sum('units'))
    revenue = float(agg['revenue'] or 0)
    orders = int(agg['orders'] or 0)
    return {
        'period': period,
        'revenue': revenue,
        'orders': orders,
        'units_sold': int(agg['units'] or 0),
        'average_order_value': round(revenue / orders, 2) if orders else 0,
    }


def admin_count_orders(user, args):
    """How many orders match a status and/or period. Use for "how many orders
    are unshipped", "how many pending", "orders today"."""
    from orders.models import Order

    period = args.get('period', 'all')
    status = (args.get('status') or '').strip().lower()
    qs = Order.objects.filter(is_deleted=False)
    start = _period_start(period)
    if start is not None:
        qs = qs.filter(created_at__date__gte=start)
    valid = {'pending', 'confirmed', 'processing', 'shipped', 'delivering', 'delivered', 'cancelled'}
    if status in valid:
        qs = qs.filter(status=status)
    elif status in ('unshipped', 'to_ship'):
        qs = qs.filter(status__in=['confirmed', 'processing'])
    return {'period': period, 'status': status or 'any', 'count': qs.count()}


def admin_list_recent_orders(user, args):
    """Recent orders (optionally filtered by status) with number, customer,
    status and total. Read-only summary — no addresses or payment details."""
    from orders.models import Order

    limit = _coerce_limit(args)
    status = (args.get('status') or '').strip().lower()
    qs = Order.objects.filter(is_deleted=False).select_related('user')
    valid = {'pending', 'confirmed', 'processing', 'shipped', 'delivering', 'delivered', 'cancelled'}
    if status in valid:
        qs = qs.filter(status=status)
    elif status in ('unshipped', 'to_ship'):
        qs = qs.filter(status__in=['confirmed', 'processing'])
    orders = qs.order_by('-created_at')[:limit]
    rows = []
    for o in orders:
        name = ((getattr(o.user, 'name', '') or '').strip()
                or getattr(o.user, 'email', '') if o.user_id else 'Guest')
        rows.append({
            'order_number': _order_number(o.id),
            'customer': name,
            'status': o.status,
            'payment': o.payment_method,
            'total': float(o.total_amount),
            'placed_on': o.created_at.strftime('%Y-%m-%d'),
        })
    return {'orders': rows, 'count': len(rows)}


def admin_low_stock(user, args):
    """Products at or below their low-stock threshold, lowest first."""
    from products.models import Product

    limit = _coerce_limit(args, default=15)
    base = Product.objects.filter(is_active=True, stock__lte=F('low_stock_threshold'))
    # Count the FULL match set before slicing — .count() on a sliced queryset
    # would cap at `limit` and under-report how many products are actually low.
    total = base.count()
    qs = base.order_by('stock')[:limit]
    return {
        'products': [
            {'name': p.name, 'stock': p.stock, 'threshold': p.low_stock_threshold}
            for p in qs
        ],
        'count': total,
    }


def admin_top_products(user, args):
    """Best-selling products by units over a period (excludes cancelled)."""
    from orders.models import OrderItem

    period = args.get('period', '30d')
    limit = _coerce_limit(args)
    start = _period_start(period)
    qs = OrderItem.objects.filter(order__is_deleted=False).exclude(order__status='cancelled')
    if start is not None:
        qs = qs.filter(order__created_at__date__gte=start)
    top = (qs.values('product_name')
           .annotate(units=Sum('quantity'), revenue=Sum('final_price'))
           .order_by('-units')[:limit])
    return {
        'period': period,
        'products': [
            {'name': t['product_name'], 'units': int(t['units'] or 0),
             'revenue': float(t['revenue'] or 0)}
            for t in top
        ],
    }


def admin_product_stock(user, args):
    """Stock level of a product by name (partial match)."""
    from products.models import Product

    name = (args.get('name') or '').strip()
    if not name:
        return {'error': 'bad_args', 'message': 'name is required'}
    matches = Product.objects.filter(name__icontains=name)[:MAX_LIST]
    if not matches:
        return {'error': 'not_found', 'message': f'No product matching "{name}".'}
    return {
        'products': [
            {'name': p.name, 'stock': p.stock, 'price': float(p.price),
             'active': p.is_active}
            for p in matches
        ],
    }


def admin_find_customer(user, args):
    """Look up customers by name, email or phone, with their order count and
    total spend. Admin-only cross-user read."""
    from django.contrib.auth import get_user_model

    query = (args.get('query') or '').strip()
    if not query:
        return {'error': 'bad_args', 'message': 'query is required'}
    User = get_user_model()
    not_cancelled = Q(orders__is_deleted=False) & ~Q(orders__status='cancelled')
    qs = (User.objects.filter(
            Q(email__icontains=query) | Q(name__icontains=query) |
            Q(first_name__icontains=query) | Q(last_name__icontains=query) |
            Q(phone__icontains=query))
          .annotate(order_count=Count('orders', filter=not_cancelled, distinct=True),
                    total_spent=Sum('orders__total_amount', filter=not_cancelled))
          [:MAX_LIST])
    rows = []
    for u in qs:
        rows.append({
            'name': (getattr(u, 'name', '') or f"{u.first_name} {u.last_name}".strip() or u.email),
            'email': u.email,
            'phone': getattr(u, 'phone', '') or '',
            'orders': int(u.order_count or 0),
            'total_spent': float(u.total_spent or 0),
        })
    if not rows:
        return {'error': 'not_found', 'message': f'No customer matching "{query}".'}
    return {'customers': rows, 'count': len(rows)}


def admin_search_report(user, args):
    """Top search terms and zero-result searches over a period (what customers
    looked for, and what they wanted but couldn't find)."""
    from analytics.models import SearchTermStat

    period = args.get('period', '30d')
    start = _period_start(period)
    qs = SearchTermStat.objects.all()
    if start is not None:
        qs = qs.filter(date__gte=start)
    top = (qs.values('term').annotate(n=Sum('count')).order_by('-n')[:10])
    zero = (qs.filter(zero_result=True).values('term')
            .annotate(n=Sum('count')).order_by('-n')[:10])
    return {
        'period': period,
        'top_searches': [{'term': t['term'], 'count': int(t['n'] or 0)} for t in top],
        'not_found_searches': [{'term': z['term'], 'count': int(z['n'] or 0)} for z in zero],
    }


# Registry — READ ONLY. No action builders for the admin persona.
ADMIN_READ_TOOLS = {
    'sales_summary': admin_sales_summary,
    'count_orders': admin_count_orders,
    'list_recent_orders': admin_list_recent_orders,
    'low_stock_products': admin_low_stock,
    'top_products': admin_top_products,
    'product_stock': admin_product_stock,
    'find_customer': admin_find_customer,
    'search_report': admin_search_report,
}


def run_admin_read_tool(name, user, args):
    handler = ADMIN_READ_TOOLS.get(name)
    if handler is None:
        return {'error': 'unknown_tool', 'message': f'No such tool: {name}'}
    if not isinstance(args, dict):
        args = {}
    try:
        return handler(user, args)
    except Exception:
        logger.exception("Admin assistant read tool %s failed", name)
        return {'error': 'tool_error', 'message': 'That lookup failed, please try again.'}
