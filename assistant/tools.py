"""Closed tool registry for the AI assistant.

SECURITY (G1/G2): This module is the data trust boundary. The language model
can ONLY trigger the tools defined here, with strictly validated arguments.

- No tool accepts a user identifier (user_id / email / phone). The model has no
  vocabulary to request another user's data.
- Every user-scoped read is hard-filtered by the authenticated `user` passed in
  from the view — never by anything the model emitted.
- Tools return only public, whitelisted fields (mirroring the public search
  serializers). No cost price, margins, supplier data, staff, or internal flags.
- There are no list/enumerate tools (no list_orders / list_users / search_customers).
"""

import logging
import re
from decimal import Decimal

from django.db.models import F, Q

from products.models import Product, ProductCombo, ProductVariant, Category, default_variant_for
from products.recommendations import build_suggestions

logger = logging.getLogger(__name__)

# Max quantity the assistant will ever propose adding in one go (clamp, G5).
MAX_PROPOSE_QTY = 10

# Login wall message for anonymous users hitting user-scoped tools (G1).
LOGIN_REQUIRED = {
    'error': 'login_required',
    'message': 'Please log in to access your cart and orders.',
}

# ----------------------------------------------------------------------------
# Navigation allowlist (G6) — the assistant can only ever send users to known
# in-app routes. Static routes plus two dynamic patterns whose slug is verified
# to exist before the route is returned. No external URLs, no open redirect.
# ----------------------------------------------------------------------------
NAV_STATIC_ROUTES = {
    '/', '/products', '/combos', '/offer-zone', '/cart', '/billing',
    '/my-orders', '/favorites', '/about', '/contact',
    '/shipping-policy', '/return-policy',
    # NOTE: no /track-order — the storefront has no such route (AP10). Tracking
    # lives on /my-orders via get_tracking.
}
_PRODUCT_ROUTE = re.compile(r'^/products/([\w-]+)$')
_COMBO_ROUTE = re.compile(r'^/combos/([\w-]+)$')


def _safe_route(route):
    """Return the route if it is allowlisted (and any slug exists), else None."""
    if not isinstance(route, str):
        return None
    route = route.strip()
    if route in NAV_STATIC_ROUTES:
        return route
    m = _PRODUCT_ROUTE.match(route)
    if m and Product.objects.filter(slug=m.group(1), is_active=True).exists():
        return route
    m = _COMBO_ROUTE.match(route)
    if m and ProductCombo.objects.filter(slug=m.group(1), is_active=True).exists():
        return route
    return None


# ----------------------------------------------------------------------------
# Serialization helpers — public fields ONLY (G2)
# ----------------------------------------------------------------------------
def _product_public(p, full=False):
    data = {
        'id': p.id,
        'name': p.name,
        'slug': p.slug,
        'type': 'product',
        'price': float(p.final_price),
        'original_price': float(p.price),
        'in_stock': p.stock > 0,
        'route': f'/products/{p.slug}',
    }
    if full:
        data.update({
            'category': getattr(p.category, 'name', '') if p.category_id else '',
            'spice_form': p.spice_form,
            'weight': p.formatted_weight,
            'description': (p.description or '')[:600],
            'ingredients': (p.ingredients or '')[:300],
        })
    return data


def _combo_public(c, full=False):
    data = {
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'type': 'combo',
        'price': float(c.final_price),
        'original_price': float(c.price),
        # Combos carry no stock field in the model (availability is governed only
        # by is_active), so they are always reported in stock — consistent with
        # the rest of the app. Revisit if combos ever track member-product stock.
        'in_stock': True,
        'route': f'/combos/{c.slug}',
    }
    if full:
        data['description'] = (c.description or '')[:600]
    return data


def _order_number(order):
    return f'ORD-{order.id:06d}'


# ----------------------------------------------------------------------------
# READ TOOLS (executed server-side inside the agent loop)
# ----------------------------------------------------------------------------
def tool_search_products(user, args):
    """AP10: size-aware rows. Product hits carry their active pack sizes
    (`variants`: variant_id, weight label, price, in_stock) so "500 g haldi"
    resolves to the right size instead of the default. Combos have no sizes."""
    query = args.get('query')
    if not isinstance(query, str) or not query.strip():
        return {'error': 'bad_args', 'message': 'query is required'}
    payload = build_suggestions(query.strip()[:100], limit=6)
    product_ids = [s['id'] for s in payload['suggestions'] if s['type'] == 'product']
    variants_by_product = {}
    if product_ids:
        for v in ProductVariant.objects.filter(
                product_id__in=product_ids, is_active=True
                ).order_by('display_order', 'weight'):
            variants_by_product.setdefault(v.product_id, []).append({
                'variant_id': v.id,
                'weight': v.formatted_weight,
                'price': float(v.final_price),
                'in_stock': v.stock > 0,
            })
    for s in payload['suggestions']:
        if s['type'] == 'product':
            s['variants'] = variants_by_product.get(s['id'], [])
    return {'query': payload['query'], 'results': payload['suggestions']}


def tool_get_product_details(user, args):
    slug = args.get('slug')
    if not isinstance(slug, str) or not slug.strip():
        return {'error': 'bad_args', 'message': 'slug is required'}
    slug = slug.strip()
    p = Product.objects.filter(slug=slug, is_active=True).select_related('category').first()
    if p:
        return _product_public(p, full=True)
    c = ProductCombo.objects.filter(slug=slug, is_active=True).first()
    if c:
        return _combo_public(c, full=True)
    return {'error': 'not_found', 'message': 'No such product.'}


def tool_list_categories(user, args):
    cats = Category.objects.filter(is_active=True).values_list('name', 'slug')
    return {'categories': [{'name': n, 'slug': s, 'route': '/products'} for n, s in cats]}


def tool_get_policy(user, args):
    """AP10: policy text comes from assistant/policies.py — transcribed from the
    storefront's locale strings (the SAME source the static pages render), NOT
    the retired admin_panel.Policy table (no rows, no routes)."""
    from .policies import POLICIES
    kind = args.get('kind')
    if kind not in POLICIES:
        return {'error': 'bad_args', 'message': "kind must be 'shipping' or 'return'",
                'route': '/shipping-policy'}
    title, content, route = POLICIES[kind]
    return {'kind': kind, 'title': title, 'content': content, 'route': route}


def tool_get_offers(user, args):
    """Currently redeemable coupon offers. Public fields only (AP10): code,
    human-readable offer, minimum order and expiry — never usage counters or
    assignment internals. User-specific coupons appear only for their owner."""
    from django.utils import timezone
    from admin_panel.models import Coupon
    now = timezone.now()
    qs = Coupon.objects.filter(is_active=True)
    qs = qs.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now))
    qs = qs.filter(Q(max_usage__isnull=True) | Q(usage_count__lt=F('max_usage')))
    if user is not None and getattr(user, 'is_authenticated', False):
        qs = qs.filter(Q(assigned_user__isnull=True) | Q(assigned_user=user))
    else:
        qs = qs.filter(assigned_user__isnull=True)
    rows = []
    for c in qs.order_by('valid_until')[:20]:
        if c.discount_type == 'fixed':
            desc = f'Flat Rs.{c.discount_amount} off'
        else:
            desc = f'{c.discount_percent}% off'
        rows.append({
            'code': c.code,
            'offer': desc,
            'minimum_order': float(c.minimum_order_amount or 0),
            'valid_until': c.valid_until.strftime('%Y-%m-%d') if c.valid_until else None,
        })
    return {'offers': rows, 'count': len(rows)}


def tool_get_delivery_info(user, args):
    """Delivery fee facts, read live from limits.py — never hardcoded (AP10)."""
    from spices_backend.limits import (
        SHIPPING_CHARGE_NET, SHIPPING_TAX_RATE, FREE_SHIPPING_THRESHOLD,
    )
    fee = SHIPPING_CHARGE_NET
    rate = SHIPPING_TAX_RATE
    total = (fee * (1 + rate / 100)).quantize(Decimal('0.01'))
    return {
        'fee_net': float(fee),
        'tax_rate': float(rate),
        'fee_total': float(total),
        'free_above': float(FREE_SHIPPING_THRESHOLD),
        'currency': 'INR',
        'note': 'Delivery is taxed on top; product prices already include GST.',
    }


def tool_get_tracking(user, args):
    """Courier + tracking link for ONE of the user's own orders (AP10).
    G1: hard-filtered by `user`, same as get_order_status."""
    if user is None or not user.is_authenticated:
        return LOGIN_REQUIRED
    raw = str(args.get('order_number', ''))
    m = _ORDER_NUM.search(raw)
    if not m:
        return {'error': 'bad_args', 'message': 'Provide an order number like ORD-000123.'}
    from orders.models import Order
    order = Order.objects.filter(id=int(m.group(1)), user=user).first()
    if not order:
        return {'error': 'not_found', 'message': 'No such order on your account.'}
    url = (order.tracking_url or '').strip()
    if url and not (url.startswith('http://') or url.startswith('https://')):
        url = ''
    return {
        'order_number': _order_number(order),
        'status': order.status,
        'courier': (order.courier_name or '').strip(),
        'tracking_id': (order.tracking_number or '').strip(),
        'tracking_url': url,
        'route': '/my-orders',
    }


_ORDER_NUM = re.compile(r'(\d+)')


def tool_get_order_status(user, args):
    # G1: user-scoped. Anonymous users never reach order data.
    if user is None or not user.is_authenticated:
        return LOGIN_REQUIRED
    raw = str(args.get('order_number', ''))
    m = _ORDER_NUM.search(raw)
    if not m:
        return {'error': 'bad_args', 'message': 'Provide an order number like ORD-000123.'}
    order_id = int(m.group(1))
    # Hard filter by the authenticated user — passing someone else's number
    # returns the same "not found" as a non-existent order (no existence oracle).
    from orders.models import Order
    order = Order.objects.filter(id=order_id, user=user).first()
    if not order:
        return {'error': 'not_found', 'message': 'No such order on your account.'}
    return {
        'order_number': f'ORD-{order.id:06d}',
        'status': order.status,
        'payment_status': order.payment_status,
        'total_amount': float(order.total_amount),
        'placed_on': order.created_at.strftime('%Y-%m-%d'),
        'route': '/my-orders',
    }


def tool_get_cart(user, args):
    # G1: user-scoped.
    if user is None or not user.is_authenticated:
        return LOGIN_REQUIRED
    from cart.models import Cart
    cart = Cart.objects.filter(user=user).first()
    if not cart or not cart.items.exists():
        return {'items': [], 'total': 0.0, 'count': 0}
    items = []
    total = Decimal('0')
    for it in cart.items.select_related('product', 'combo').all():
        obj = it.product if it.item_type == 'product' else it.combo
        if obj is None:
            continue
        price = obj.final_price if hasattr(obj, 'final_price') else obj.price
        total += price * it.quantity
        items.append({'name': obj.name, 'quantity': it.quantity, 'price': float(price)})
    return {'items': items, 'total': float(total), 'count': len(items)}


# How many rows the order/browse/review tools will ever return in one call.
MAX_LIST_LIMIT = 20
DEFAULT_LIST_LIMIT = 6
# Cap on the DB candidate set browse_products scans before in-Python filtering.
BROWSE_CANDIDATE_CAP = 200


def _coerce_limit(args, default=DEFAULT_LIST_LIMIT):
    try:
        n = int(args.get('limit', default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, MAX_LIST_LIMIT))


def tool_list_my_orders(user, args):
    """The authenticated user's own recent orders. G1: hard-filtered by `user`;
    there is no argument that could widen the scope to anyone else."""
    if user is None or not user.is_authenticated:
        return LOGIN_REQUIRED
    from orders.models import Order
    limit = _coerce_limit(args)
    orders = (Order.objects.filter(user=user)
              .order_by('-created_at')
              .prefetch_related('items')[:limit])
    results = []
    for o in orders:
        items = list(o.items.all())
        results.append({
            'order_number': _order_number(o),
            'status': o.status,
            'payment_status': o.payment_status,
            'placed_on': o.created_at.strftime('%Y-%m-%d'),
            'total_amount': float(o.total_amount),
            'item_count': len(items),
            'items_preview': [it.product_name for it in items[:3]],
        })
    return {'orders': results, 'count': len(results), 'route': '/my-orders'}


def tool_get_order_details(user, args):
    """Line items of ONE of the authenticated user's orders. G1: filtered by
    `user`; an order number that isn't theirs returns the same 'not_found' as a
    non-existent one (no existence oracle). Includes product ids/types so the
    assistant can offer to reorder via add_to_cart."""
    if user is None or not user.is_authenticated:
        return LOGIN_REQUIRED
    raw = str(args.get('order_number', ''))
    m = _ORDER_NUM.search(raw)
    if not m:
        return {'error': 'bad_args', 'message': 'Provide an order number like ORD-000123.'}
    from orders.models import Order
    order = (Order.objects.filter(id=int(m.group(1)), user=user)
             .prefetch_related('items').first())
    if not order:
        return {'error': 'not_found', 'message': 'No such order on your account.'}
    items = []
    for it in order.items.all():
        items.append({
            'name': it.product_name,
            'item_type': it.item_type,
            'product_id': it.product_id if it.item_type == 'product' else it.combo_id,
            'weight': it.product_weight,
            'quantity': it.quantity,
            'line_total': float(it.final_price),
        })
    return {
        'order_number': _order_number(order),
        'status': order.status,
        'placed_on': order.created_at.strftime('%Y-%m-%d'),
        'total_amount': float(order.total_amount),
        'items': items,
        'route': '/my-orders',
    }


_SPICE_FORMS = {'whole', 'powder', 'crushed', 'mixed'}
_BROWSE_SORTS = {'price_asc', 'price_desc', 'featured', 'newest'}


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except Exception:
        return None


def tool_browse_products(user, args):
    """Structured catalogue browse over products (and optionally combos). Public
    data only (G2). Supports category, price range, spice form, on-offer and
    in-stock filters, plus sorting. Bounded result set — not an enumeration
    oracle for anything private (everything here is already publicly listed)."""
    limit = _coerce_limit(args, default=8)

    category = args.get('category')
    spice_form = args.get('spice_form')
    sort = args.get('sort') if args.get('sort') in _BROWSE_SORTS else None
    min_price = _to_decimal(args.get('min_price')) if args.get('min_price') is not None else None
    max_price = _to_decimal(args.get('max_price')) if args.get('max_price') is not None else None
    on_offer = bool(args.get('on_offer')) if args.get('on_offer') is not None else None
    in_stock = bool(args.get('in_stock')) if args.get('in_stock') is not None else None
    include_combos = args.get('include_combos', True)

    # ---- Products (DB filters first, then price/offer in Python) ----
    pq = Product.objects.filter(is_active=True).select_related('category')
    if isinstance(category, str) and category.strip():
        c = category.strip()
        pq = pq.filter(models_q_category(c))
    if isinstance(spice_form, str) and spice_form.strip().lower() in _SPICE_FORMS:
        pq = pq.filter(spice_form=spice_form.strip().lower())
    if in_stock is True:
        pq = pq.filter(stock__gt=0)

    candidates = list(pq.order_by('-is_featured', '-id')[:BROWSE_CANDIDATE_CAP])

    rows = []
    for p in candidates:
        fp = p.final_price
        if min_price is not None and fp < min_price:
            continue
        if max_price is not None and fp > max_price:
            continue
        if on_offer is True and not (p.discount_price and p.discount_price < p.price):
            continue
        rows.append((p, fp, bool(p.is_featured), p.id))

    # ---- Combos (only when not constrained to a spice/category facet) ----
    if include_combos and not (category or spice_form) and in_stock is not True:
        cq = ProductCombo.objects.filter(is_active=True)
        for c in list(cq.order_by('-is_featured', '-id')[:BROWSE_CANDIDATE_CAP]):
            fp = c.final_price
            if min_price is not None and fp < min_price:
                continue
            if max_price is not None and fp > max_price:
                continue
            if on_offer is True and not (c.discount_price and c.discount_price < c.price):
                continue
            rows.append((c, fp, bool(c.is_featured), c.id))

    # ---- Sort ----
    if sort == 'price_asc':
        rows.sort(key=lambda r: r[1])
    elif sort == 'price_desc':
        rows.sort(key=lambda r: r[1], reverse=True)
    elif sort == 'newest':
        rows.sort(key=lambda r: r[3], reverse=True)
    else:  # featured (default): featured first, then newest
        rows.sort(key=lambda r: (r[2], r[3]), reverse=True)

    results = []
    for obj, _fp, _feat, _id in rows[:limit]:
        results.append(_combo_public(obj) if isinstance(obj, ProductCombo) else _product_public(obj))
    return {'results': results, 'count': len(results)}


def tool_get_product_reviews(user, args):
    """Public review summary for a product or combo by slug. Exposes only public
    review fields (rating, comment, reviewer first name, verified flag) — never
    reviewer email or account details (G2)."""
    slug = args.get('slug')
    if not isinstance(slug, str) or not slug.strip():
        return {'error': 'bad_args', 'message': 'slug is required'}
    slug = slug.strip()
    limit = _coerce_limit(args, default=5)

    item = Product.objects.filter(slug=slug, is_active=True).first()
    if item is None:
        item = ProductCombo.objects.filter(slug=slug, is_active=True).first()
    if item is None:
        return {'error': 'not_found', 'message': 'No such product.'}

    from django.db.models import Avg
    qs = item.reviews.select_related('user').order_by('-created_at')
    agg = qs.aggregate(avg=Avg('rating'))
    count = qs.count()
    if not count:
        return {'name': item.name, 'slug': slug, 'review_count': 0,
                'average_rating': None, 'reviews': []}

    recent = []
    for r in qs[:limit]:
        reviewer = (getattr(r.user, 'first_name', '') or '').strip() or 'A customer'
        recent.append({
            'rating': r.rating,
            'title': (r.title or '')[:120],
            'comment': (r.comment or '')[:300],
            'reviewer': reviewer,
            'verified_purchase': bool(r.is_verified_purchase),
            'date': r.created_at.strftime('%Y-%m-%d'),
        })
    return {
        'name': item.name,
        'slug': slug,
        'review_count': count,
        'average_rating': round(agg['avg'], 1) if agg['avg'] is not None else None,
        'reviews': recent,
    }


def models_q_category(value):
    """Match a category by exact slug or case-insensitive name contains."""
    from django.db.models import Q
    return Q(category__slug=value) | Q(category__name__icontains=value)


# ----------------------------------------------------------------------------
# PROPOSED ACTIONS (returned to the UI, NEVER executed in the loop — G5)
# These build a `proposed_action` dict; the actual mutation happens only when
# the user clicks confirm, through the existing cart/order endpoints.
# ----------------------------------------------------------------------------
def _resolve_proposal_variant(product_id=None, variant_id=None, item_type='product'):
    """Resolve a proposal line to (product_or_combo, variant_or_None, error).

    AP10: sizes are first-class. A variant_id pins the exact pack size; without
    one the product's default size applies (compat fallback — the PROMPT tells
    the model to ask for the size, never guess). Combos have no sizes.
    """
    if item_type not in ('product', 'combo'):
        item_type = 'product'
    if item_type == 'combo':
        if variant_id is not None:
            return None, None, 'Combos have no sizes; omit variant_id.'
        try:
            combo_id = int(product_id)
        except (TypeError, ValueError):
            return None, None, 'I could not identify that combo.'
        obj = ProductCombo.objects.filter(id=combo_id, is_active=True).first()
        if not obj:
            return None, None, 'That combo is not available.'
        return obj, None, None
    variant = None
    if variant_id is not None:
        try:
            vid = int(variant_id)
        except (TypeError, ValueError):
            return None, None, 'I could not identify that size.'
        variant = ProductVariant.objects.filter(
            id=vid, is_active=True).select_related('product').first()
        if variant is None:
            return None, None, 'That size is not available.'
        if product_id is not None:
            try:
                pid = int(product_id)
            except (TypeError, ValueError):
                return None, None, 'I could not identify that product.'
            if pid != variant.product_id:
                return None, None, 'That size does not belong to that product.'
        obj = variant.product
        if not obj.is_active:
            return None, None, 'That product is not available.'
    else:
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            return None, None, 'I could not identify that product.'
        obj = Product.objects.filter(id=pid, is_active=True).first()
        if not obj:
            return None, None, 'That product is not available.'
        variant = default_variant_for(obj)  # None on legacy variant-less rows
    return obj, variant, None


def _proposal_stock_ok(obj, variant):
    """In-stock check against the SIZE when one is pinned (AP10)."""
    if variant is not None:
        return variant.stock > 0, variant
    return obj.stock > 0 if hasattr(obj, 'stock') else True, None


def build_add_to_cart(user, args):
    item_type = args.get('item_type', 'product')
    try:
        qty = int(args.get('quantity', 1))
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, min(qty, MAX_PROPOSE_QTY))  # clamp (G5)

    obj, variant, err = _resolve_proposal_variant(
        args.get('product_id'), args.get('variant_id'), item_type)
    if err:
        return None, err
    ok, _ = _proposal_stock_ok(obj, variant)
    if item_type == 'product' and not ok:
        size = f' ({variant.formatted_weight})' if variant else ''
        return None, f'{obj.name}{size} is out of stock.'

    if variant is not None:
        label = f'Add {qty} × {obj.name} ({variant.formatted_weight}) to cart'
        price = float(variant.final_price)
    else:
        label = f'Add {qty} × {obj.name} to cart'
        price = float(obj.final_price)
    action = {
        'type': 'add_to_cart',
        'product_id': obj.id,
        'variant_id': variant.id if variant else None,
        'item_type': item_type,
        'quantity': qty,
        'price': price,
        'label': label,
    }
    return action, None


# At most this many lines in one cart proposal — one screen, one tap (AP10).
CART_PROPOSAL_MAX_LINES = 5


def build_cart_proposal(user, args):
    """ONE multi-line proposal for the whole shopping list (AP10): several
    sizes/quantities as a single editable card with a single confirm. All lines
    validate or the whole proposal is refused (all-or-nothing)."""
    raw_lines = args.get('lines')
    if not isinstance(raw_lines, list) or not raw_lines:
        return None, 'I could not understand that shopping list.'
    if len(raw_lines) > CART_PROPOSAL_MAX_LINES:
        return None, f'At most {CART_PROPOSAL_MAX_LINES} items per proposal.'
    lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            return None, 'I could not understand that shopping list.'
        try:
            qty = int(entry.get('quantity', entry.get('qty', 1)))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, MAX_PROPOSE_QTY))  # clamp each line (G5)
        obj, variant, err = _resolve_proposal_variant(
            entry.get('product_id'), entry.get('variant_id'),
            entry.get('item_type', 'product'))
        if err:
            return None, err
        ok, _ = _proposal_stock_ok(obj, variant)
        if (entry.get('item_type', 'product') == 'product') and not ok:
            size = f' ({variant.formatted_weight})' if variant else ''
            return None, f'{obj.name}{size} is out of stock.'
        if variant is not None:
            label = f'{qty} × {obj.name} ({variant.formatted_weight})'
            price = float(variant.final_price)
        else:
            label = f'{qty} × {obj.name}'
            price = float(obj.final_price)
        lines.append({
            'product_id': obj.id,
            'variant_id': variant.id if variant else None,
            'item_type': entry.get('item_type', 'product'),
            'quantity': qty,
            'price': price,
            'label': label,
        })
    note = args.get('note') or ''
    if not isinstance(note, str):
        note = ''
    return {
        'type': 'cart_proposal',
        'lines': lines,
        'note': note[:200],
        'label': f'Add {len(lines)} items to cart',
    }, None


def build_edit_cart(user, args):
    """Propose cart edits (set quantity, 0 removes) by size (AP10). The UI
    confirms, then applies the lines through the existing cart endpoints —
    nothing mutates here (G5)."""
    raw_lines = args.get('lines')
    if not isinstance(raw_lines, list) or not raw_lines:
        return None, 'I could not understand that cart change.'
    if len(raw_lines) > CART_PROPOSAL_MAX_LINES:
        return None, f'At most {CART_PROPOSAL_MAX_LINES} changed lines at once.'
    lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            return None, 'I could not understand that cart change.'
        try:
            qty = int(entry.get('quantity', entry.get('qty', 1)))
        except (TypeError, ValueError):
            return None, 'Quantities must be numbers.'
        qty = max(0, min(qty, MAX_PROPOSE_QTY))
        obj, variant, err = _resolve_proposal_variant(
            entry.get('product_id'), entry.get('variant_id'),
            entry.get('item_type', 'product'))
        if err:
            return None, err
        size = f' ({variant.formatted_weight})' if variant else ''
        lines.append({
            'product_id': obj.id,
            'variant_id': variant.id if variant else None,
            'item_type': entry.get('item_type', 'product'),
            'quantity': qty,
            'label': f'Remove {obj.name}{size}' if qty == 0
                     else f'Set {obj.name}{size} to {qty}',
        })
    return {'type': 'edit_cart', 'lines': lines, 'label': 'Update cart'}, None


def build_checkout(user, args):
    if user is None or not user.is_authenticated:
        return {'type': 'navigate', 'route': '/login', 'label': 'Log in to checkout'}, None
    return {'type': 'checkout', 'route': '/billing', 'label': 'Go to checkout'}, None


def build_navigate(user, args):
    route = _safe_route(args.get('route'))
    if not route:
        return None, 'I can only take you to pages on this store.'
    return {'type': 'navigate', 'route': route, 'label': f'Open {route}'}, None


def build_escalate(user, args):
    reason = args.get('reason', '')
    if not isinstance(reason, str):
        reason = ''
    return {'type': 'escalate_to_human', 'reason': reason[:300],
            'label': 'Connect me with a human'}, None


# ----------------------------------------------------------------------------
# Registry & dispatch
# ----------------------------------------------------------------------------
READ_TOOLS = {
    'search_products': tool_search_products,
    'browse_products': tool_browse_products,
    'get_product_details': tool_get_product_details,
    'get_product_reviews': tool_get_product_reviews,
    'list_categories': tool_list_categories,
    'get_policy': tool_get_policy,
    'get_offers': tool_get_offers,
    'get_delivery_info': tool_get_delivery_info,
    'get_tracking': tool_get_tracking,
    'get_order_status': tool_get_order_status,
    'get_order_details': tool_get_order_details,
    'list_my_orders': tool_list_my_orders,
    'get_cart': tool_get_cart,
}

ACTION_BUILDERS = {
    'add_to_cart': build_add_to_cart,
    'cart_proposal': build_cart_proposal,
    'edit_cart': build_edit_cart,
    'checkout': build_checkout,
    'navigate': build_navigate,
    'escalate_to_human': build_escalate,
}

# Names advertised to the model. Anything outside this set is rejected (G3).
ALL_TOOL_NAMES = set(READ_TOOLS) | set(ACTION_BUILDERS)


# ----------------------------------------------------------------------------
# Native function-calling schemas (AP9). The model is bound to these; several
# may be called in ONE round (multi-item lookups). Schemas only GUIDE the
# model — argument validation still happens server-side in each handler (G3).
# ----------------------------------------------------------------------------
def _fn(name, description, properties, required=()):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': properties,
                'required': list(required),
            },
        },
    }


def _str(desc):
    return {'type': 'string', 'description': desc}


def _int(desc):
    return {'type': 'integer', 'description': desc}


def _bool(desc):
    return {'type': 'boolean', 'description': desc}


TOOL_SCHEMAS = [
    _fn('search_products', 'Fuzzy-find products/combos by name or Hinglish term.',
        {'query': _str('What the customer named, e.g. haldi, garam masala.')}, ['query']),
    _fn('browse_products', 'Structured catalogue browse/filter.',
        {'category': _str('Category name or slug.'), 'min_price': {'type': 'number'},
         'max_price': {'type': 'number'},
         'spice_form': _str('whole, powder, crushed or mixed.'),
         'on_offer': _bool('Only discounted items.'), 'in_stock': _bool('Only in-stock items.'),
         'include_combos': _bool('Include combos (default true).'),
         'sort': _str('price_asc, price_desc, featured or newest.'),
         'limit': _int('Max rows (default 8, max 20).')}),
    _fn('get_product_details', 'Price, weight and description for ONE product/combo.',
        {'slug': _str('Product or combo slug.')}, ['slug']),
    _fn('get_product_reviews', 'Rating summary + recent reviews for ONE item.',
        {'slug': _str('Product or combo slug.'), 'limit': _int('Max reviews (default 5).')},
        ['slug']),
    _fn('list_categories', "The store's product categories.", {}),
    _fn('get_policy', 'Shipping or return policy text (from the static pages).',
        {'kind': _str('shipping or return.')}, ['kind']),
    _fn('get_offers', 'Currently redeemable coupon offers.',
        {'limit': _int('Max offers (default 20).')}),
    _fn('get_delivery_info', 'Delivery fee facts: net fee, GST rate, total, free-shipping threshold.', {}),
    _fn('get_tracking', "Courier + tracking link for ONE of the user's orders.",
        {'order_number': _str('e.g. ORD-000123.')}, ['order_number']),
    _fn('get_order_status', "Quick status of ONE of the user's orders.",
        {'order_number': _str('e.g. ORD-000123.')}, ['order_number']),
    _fn('get_order_details', "Line items of ONE of the user's orders.",
        {'order_number': _str('e.g. ORD-000123.')}, ['order_number']),
    _fn('list_my_orders', "The user's recent orders.",
        {'limit': _int('Max orders (default 6).')}),
    _fn('get_cart', "The user's current cart contents.", {}),
]

ACTION_SCHEMAS = [
    _fn('add_to_cart', 'PROPOSE adding one item (customer confirms in the app).',
        {'product_id': _int('Product or combo id.'),
         'variant_id': _int('Exact pack-size id from search variants. Ask the '
                            'customer for the size; never guess the default.'),
         'item_type': _str('product or combo.'),
         'quantity': _int('Units (clamped server-side).')}, ['product_id']),
    _fn('cart_proposal', 'PROPOSE the whole shopping list as ONE editable card '
         '(customer confirms once). Prefer this over several add_to_cart calls.',
        {'lines': {'type': 'array', 'description': 'Up to 5 lines.',
                   'items': {'type': 'object'}},
         'note': _str('One-line note shown on the card.')}, ['lines']),
    _fn('edit_cart', 'PROPOSE cart edits (set quantity, 0 removes a line).',
        {'lines': {'type': 'array', 'description': 'Lines with variant_id/product_id and quantity.',
                   'items': {'type': 'object'}}}, ['lines']),
    _fn('checkout', 'PROPOSE going to checkout.', {}),
    _fn('navigate', 'PROPOSE opening an in-store page.',
        {'route': _str('e.g. /products, /cart, /my-orders.')}, ['route']),
    _fn('escalate_to_human', 'Flag the thread for a human. Call ONLY when the '
         'customer explicitly asks for a human — never for failures you can '
         'describe yourself.',
        {'reason': _str('What the customer asked for, in their words.')}),
]


def run_read_tool(name, user, args):
    """Execute a read tool by name. Returns an observation dict."""
    handler = READ_TOOLS.get(name)
    if handler is None:
        return {'error': 'unknown_tool', 'message': f'No such tool: {name}'}
    if not isinstance(args, dict):
        args = {}
    try:
        return handler(user, args)
    except Exception:
        logger.exception("Assistant read tool %s failed", name)
        return {'error': 'tool_error', 'message': 'That lookup failed, please try again.'}


def build_action(name, user, args):
    """Build a proposed_action dict. Returns (action|None, error_message|None)."""
    builder = ACTION_BUILDERS.get(name)
    if builder is None:
        return None, None
    if not isinstance(args, dict):
        args = {}
    try:
        return builder(user, args)
    except Exception:
        logger.exception("Assistant action builder %s failed", name)
        return None, 'I could not prepare that action.'
