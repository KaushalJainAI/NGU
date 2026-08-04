"""
Order Views - Order Management API

Architecture:
- OrderViewSet: Complete order CRUD serving two surfaces from one route
  - Storefront "My Orders" (default): the caller's own orders, bare array —
    staff get this too when they browse the storefront
  - Admin table (`?scope=all`, staff only): every customer's orders, paginated
  The list scope follows the REQUEST, not the caller's is_staff flag; detail
  actions keep the unconditional staff scope. See `_wants_admin_list`.

Order Creation Flow:
1. Validate cart exists and has items
2. Validate coupon if provided (checks is_active, valid_until)
3. Calculate totals: subtotal, discount, env-configured shipping, and the
   per-line GST contained in the (inclusive) prices — see orders/pricing.py
4. Create Order + OrderItems in atomic transaction
5. Reduce product stock within transaction
6. Clear cart depending on completion (see Key Design Decision 1)

Key Design Decisions:
1. Cart clearing is tied to order COMPLETION, not creation. COD and already-paid
   (zero-total coupon) orders are complete at placement and clear the cart inside
   the transaction. A 'pending' ONLINE order keeps the cart until its payment is
   captured (payments.services.mark_payment_captured clears it) so an abandoned
   payment never strands the customer with an empty cart. A fresh checkout first
   supersedes (cancels + restocks) any earlier pending ONLINE order so reserved
   stock never leaks across retries.
2. Proportional discount - each item gets discount proportional to its share of subtotal
3. Stock validation before order creation - prevents overselling
4. Combos have default stock of 999 (effectively unlimited)
5. Order number format: ORD-XXXXXX (6 digit padded ID)

Status Workflow:
pending → confirmed → processing → shipped → delivered
    └──────────────────────────────────────→ cancelled
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.conf import settings
from django.db import transaction, models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from decimal import Decimal, InvalidOperation
import logging
from .models import Order, OrderItem, OrderItemComponent
from .pricing import (
    allocate_combo_components, blended_rate, combo_line_tax, extract_tax,
    hsn_code_for, shipping_tax_for, tax_rate_for,
)
from .place_of_supply import place_of_supply_for, state_name
from .refunds import record_refund, refundable_balance
from .serializers import OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer
from cart.models import Cart
from admin_panel.models import Coupon
from spices_backend.limits import (
    MAX_ITEM_QUANTITY, MAX_ORDER_TOTAL, MAX_ONLINE_ORDER_TOTAL,
    SHIPPING_CHARGE, FREE_SHIPPING_THRESHOLD,
)
from spices_backend.abuse import flag_suspicious
from spices_backend.timeranges import range_filter
from .emails import (
    send_order_confirmation, send_order_status_email, send_new_order_admin_alert,
    send_low_stock_alert, send_coupon_usage_alert,
)

logger = logging.getLogger(__name__)


def restore_order_stock(order):
    """Give an order's stock back to inventory (products, variants, and combo
    components), mirroring exactly what checkout consumed.

    MUST be called inside a `transaction.atomic()` block with `order` already
    locked (``select_for_update``). This is the single source of truth for
    restocking so every path — the customer `cancel` action, the admin status
    change, L3's stuck-payment auto-cancel and a recorded refund — restores
    inventory identically. The caller is responsible for setting
    ``order.status``/``cancelled_at`` afterwards.

    IDEMPOTENT. More than one of those paths can run against the same order (an
    admin cancels a paid order and then records the refund; L3 auto-cancels and
    an admin refunds afterwards), and crediting the same units twice invents
    stock that never existed. The first call stamps ``stock_restored_at`` and
    every later one is a no-op. Returns True if it actually restocked.
    """
    from products.models import Product, ProductVariant, ProductComboItem

    if order.stock_restored_at is not None:
        logger.info("Stock already restored for order %s at %s — skipping.",
                    order.pk, order.stock_restored_at)
        return False

    variant_updates = {}
    product_updates = {}

    items = (order.items
             .select_related('product', 'combo', 'variant')
             .prefetch_related('components')
             .all())
    for item in items:
        if item.item_type == 'product' and item.variant:
            variant_updates[item.variant.pk] = variant_updates.get(item.variant.pk, 0) + item.quantity
        elif item.product:
            product_updates[item.product.pk] = product_updates.get(item.product.pk, 0) + item.quantity
        elif item.combo:
            # G2 symmetry: a combo consumed its component SIZES at checkout, so
            # cancelling must give that same inventory back. It MUST be the
            # variant, not the product: checkout debits `variant.stock`, and
            # crediting Product.stock here instead would destroy the sellable
            # stock while inflating the legacy display mirror nothing sells from.
            #
            # Restore from the ORDER'S SNAPSHOT, never the live recipe. An admin
            # who swaps a component size, changes a per-combo quantity, or adds a
            # component between placement and cancellation would otherwise make us
            # credit variants the order never consumed — phantom stock on one SKU
            # and permanently lost stock on another, silently. `components` is
            # written at checkout from exactly what was drawn from stock.
            components = list(item.components.all())
            if components:
                for comp in components:
                    # `comp.quantity` is ALREADY per-combo x line quantity (see the
                    # model docstring) — multiplying by item.quantity again would
                    # over-credit every combo line ordered in quantity > 1.
                    variant_updates[comp.variant_id] = (
                        variant_updates.get(comp.variant_id, 0) + comp.quantity)
            else:
                # Historical lines placed before the snapshot shipped. The live
                # recipe is the only record of what they consumed — wrong if the
                # combo has since been edited, but it is all there is.
                for ci in ProductComboItem.objects.filter(combo=item.combo).select_related('variant'):
                    variant_updates[ci.variant_id] = (
                        variant_updates.get(ci.variant_id, 0) + ci.quantity * item.quantity)

    # Batch restore stock for variants (+ mirror default to product)
    if variant_updates:
        variants = list(ProductVariant.objects.select_for_update().filter(pk__in=variant_updates.keys()))
        for variant in variants:
            restore_by = variant_updates[variant.pk]
            variant.stock += restore_by
            if variant.is_default:
                product_updates[variant.product_id] = product_updates.get(variant.product_id, 0) + restore_by
        ProductVariant.objects.bulk_update(variants, ['stock'])

    # Batch restore stock for products (variant-less legacy lines + default mirror)
    if product_updates:
        products = list(Product.objects.select_for_update().filter(pk__in=product_updates.keys()))
        for product in products:
            product.stock += product_updates[product.pk]
        Product.objects.bulk_update(products, ['stock'])

    # Close the door behind us. Written with .update() AND onto the in-memory
    # instance: callers that never save the order still get the flag persisted,
    # and callers that do a full `order.save()` afterwards don't write a stale
    # None back over it.
    order.stock_restored_at = timezone.now()
    Order.objects.filter(pk=order.pk).update(stock_restored_at=order.stock_restored_at)
    return True


class OrderViewSet(viewsets.ModelViewSet):
    # Fields an admin may edit via PATCH/PUT. Everything else on an order
    # (money, items, user…) is immutable through the API.
    # `shipping_cost` is the courier's charge to US — internal cost data, not part
    # of what the customer was billed, so editing it never alters `total_amount`.
    # `place_of_supply_state_code` is editable so a misdetected destination can be
    # corrected BEFORE the return is filed — the resolver falls back to the
    # seller's state on an address it can't place, and that guess has to be
    # fixable. It is deliberately NOT recomputed when an admin edits
    # `shipping_address`: silently re-heading an already-issued invoice off a
    # courier-detail correction is precisely the failure this guards against.
    ADMIN_EDITABLE_FIELDS = {'status', 'tracking_number', 'shipping_address',
                             'phone_number', 'payment_status', 'shipping_cost',
                             'cod_paid', 'place_of_supply_state_code'}
    # Statuses from which an order can no longer be cancelled. 'refunded' is
    # terminal — the money is already back with the customer.
    UNCANCELLABLE_STATUSES = {'delivered', 'delivering', 'cancelled', 'refunded'}
    # Payment methods whose money moved through the gateway.
    ONLINE_PAYMENT_METHODS = {'ONLINE', 'razorpay'}
    permission_classes = [IsAuthenticated]

    @classmethod
    def _is_refundable_payment(cls, order):
        """True when this order took money we could actually give back.

        Two ways that happens:

        * **Online**, captured through Razorpay.
        * **COD**, once an admin has ticked "Paid in cash" — `cod_paid_at` is the
          proof the money was received. Before that tick a COD order has taken
          nothing, and recording a refund against it would write a ledger row and
          reverse GST on cash that never arrived.

        Until COD collection was tracked this method demanded an ONLINE method
        outright, which meant a genuine COD return could not be recorded AT ALL —
        the cash went back and its GST stayed on the books forever. The tick is
        what closes that hole.

        `payment_status == 'refunded'` counts as well as 'paid': an order being
        settled in instalments has already flipped to 'refunded' but may still
        have a balance outstanding, and blocking it would strand the remainder.
        """
        paid_flag = order.payment_status in ('paid', 'refunded')
        if order.payment_method in cls.ONLINE_PAYMENT_METHODS:
            return paid_flag
        if order.payment_method == 'COD':
            return order.cod_paid_at is not None and paid_flag
        return False

    def get_throttles(self):
        # Rate-limit order placement (per-minute + daily); other actions are
        # governed by the default user throttle.
        if getattr(self, 'action', None) == 'create':
            from spices_backend.throttles import OrderRateThrottle, OrderDailyThrottle
            return [OrderRateThrottle(), OrderDailyThrottle()]
        return super().get_throttles()

    # Admin list sort keys → real ORM ordering. Kept small and explicit so the
    # admin can only sort by columns that actually exist (no arbitrary orderby).
    _ADMIN_ORDERING = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'highestTotal': '-total_amount',
        'lowestTotal': 'total_amount',
    }

    # Query params that only the admin order table ever sends. Their presence is
    # treated as a request for the admin view (see `_wants_admin_list`) so the
    # currently-deployed admin panel keeps working before it is rebuilt to send
    # `?scope=all`. Storefront "My Orders" sends none of these.
    _ADMIN_LIST_PARAMS = frozenset({
        'page', 'deleted', 'export', 'status', 'payment_method',
        'date_from', 'date_to', 'min_amount', 'max_amount', 'ordering', 'search',
    })

    def _wants_admin_list(self):
        """True when this `list` call is the ADMIN order table rather than the
        storefront's "My Orders".

        The two surfaces have genuinely different powers — every order vs. only
        the caller's — so the scope must follow the request's INTENT, not merely
        the caller's `is_staff` flag. A shop owner browsing their own storefront
        is a customer there and must see only their own orders; the same person
        in /panel/orders is an administrator and sees everyone's.

        Deciding on identity alone (the pre-2026-07-25 behaviour) meant a staff
        user's /my-orders page was served the paginated all-customers admin table,
        which the storefront could not render — and would have leaked every
        customer's PII if it had.

        Admin intent is `?scope=all`. Non-staff asking for it EXPLICITLY are
        refused in `list()` rather than silently downgraded, so a permission
        problem is never mistaken for an empty order history.
        """
        params = self.request.query_params
        if params.get('scope') == 'all':
            return True
        # Compat: pre-`scope` admin builds are recognised by their filter params.
        # Staff-only, so a customer who happens to send `?page=1` (or a stray
        # `?search=`) still gets their own orders instead of a 403 — the shim
        # must never change what a non-admin request means.
        user = self.request.user
        if not (user.is_staff or user.is_superuser):
            return False
        return any(key in params for key in self._ADMIN_LIST_PARAMS)

    def get_queryset(self):
        user = self.request.user
        is_admin = user.is_staff or user.is_superuser
        # The admin's all-orders scope applies to `list` only when the admin view
        # was actually requested. Detail actions (retrieve/update/restore/…) keep
        # the unconditional staff scope — they address one known order and are
        # what the admin panel's row actions rely on.
        if is_admin and (self.action != 'list' or self._wants_admin_list()):
            # `items__components` and `refunds` are NOT optional here: both order
            # serializers render `tax_breakdown` (which walks each line's combo
            # components) and the nested `refunds` list, so without them every
            # row on a paginated list costs three extra round-trips. `invoice` is
            # select_related for the same reason — the serializer reads it on
            # every row to decide whether a "Download invoice" button applies.
            qs = Order.objects.all().prefetch_related(
                'items__product', 'items__combo', 'items__variant',
                'items__components', 'refunds',
            ).select_related('user', 'payment', 'invoice')
            # Recycle Bin: only the `list` action honours the ?deleted flag, so
            # detail actions (restore/retrieve/update) can still reach a
            # soft-deleted order. Default list hides deleted orders; ?deleted=true
            # shows ONLY the recycle bin.
            if self.action == 'list':
                only_deleted = self.request.query_params.get('deleted') in ('1', 'true', 'True')
                qs = qs.filter(is_deleted=only_deleted)
                # Server-side filter/sort for the admin list. This MUST run in the
                # DB, not the browser: the admin list is paginated (PAGE_SIZE=12),
                # so a client-side filter would only ever see the first page and
                # could report e.g. "no cancelled orders" while later pages hold
                # plenty.
                qs = self._apply_admin_filters(qs)
            return qs
        # Customer scope — only their own, non-deleted orders. Staff land here too
        # when they browse the storefront.
        # Same prefetches as the admin scope — "My Orders" renders the very same
        # GST breakup and refund list, so it needs them just as much. `user` is
        # select_related for `customer_name`/`customer_email`, which the list
        # serializer renders on every row.
        return (Order.objects.filter(user=user, is_deleted=False)
                .select_related('user', 'payment', 'invoice')
                .prefetch_related('items__product', 'items__combo', 'items__variant',
                                  'items__components', 'refunds'))

    def _apply_admin_filters(self, qs):
        """Apply status / payment-method / amount / search / sort query params to
        the admin order list, entirely in the database."""
        params = self.request.query_params

        status_val = (params.get('status') or '').strip()
        if status_val:
            qs = qs.filter(status=status_val)

        payment_method = (params.get('payment_method') or '').strip()
        if payment_method:
            qs = qs.filter(payment_method=payment_method)

        for key, lookup in (('min_amount', 'total_amount__gte'), ('max_amount', 'total_amount__lte')):
            raw = (params.get(key) or '').strip()
            if raw:
                try:
                    qs = qs.filter(**{lookup: Decimal(raw)})
                except (InvalidOperation, ValueError):
                    pass  # ignore an unparseable amount rather than 500

        # Date range on the order's creation date (inclusive). Dates arrive as
        # ISO YYYY-MM-DD from the admin panel's date inputs. Translated to a
        # half-open datetime range so the filter stays on the bare column and
        # can use the created_at indexes — see spices_backend/timeranges.py.
        bounds = {}
        for key in ('date_from', 'date_to'):
            raw = (params.get(key) or '').strip()
            if raw:
                bounds[key] = parse_date(raw)  # None if unparseable → ignored
        qs = qs.filter(**range_filter('created_at', bounds.get('date_from'),
                                      bounds.get('date_to')))

        search = (params.get('search') or '').strip()
        if search:
            cond = Q(user__email__icontains=search) | \
                Q(user__first_name__icontains=search) | \
                Q(user__last_name__icontains=search) | \
                Q(shipping_address__icontains=search)
            # Order numbers are ORD-000123 → let a numeric search hit the id too.
            # Cap at 9 digits: anything longer can't be a real order id and
            # would overflow Postgres's integer type (DataError → 500).
            digits = ''.join(ch for ch in search if ch.isdigit())
            if digits and len(digits) <= 9:
                cond |= Q(id=int(digits))
            qs = qs.filter(cond)

        ordering = self._ADMIN_ORDERING.get((params.get('ordering') or '').strip())
        return qs.order_by(ordering) if ordering else qs

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        elif self.action == 'list':
            return OrderListSerializer
        return OrderDetailSerializer

    def _validate_coupon(self, coupon_code, user, order_amount=None):
        """
        Validates coupon code and returns the coupon object or error response.
        Checks is_active, expiration, max_usage, and minimum_order_amount.
        """
        try:
            coupon = Coupon.objects.get(code__iexact=coupon_code)
        except Coupon.DoesNotExist:
            return None, {'error': f'"{coupon_code}" is not a valid coupon code.'}

        # Pass the user so single-user (assigned) coupons are enforced.
        reason = coupon.get_invalid_reason(order_amount=order_amount, user=user)
        if reason:
            return None, {'error': reason}

        return coupon, None

    def _cart_line_tax_rate(self, cart_item):
        """GST rate (%) for a PRODUCT cart line.

        Combo lines have no single rate — each component is taxed at its own
        product's rate — so they go through `_cart_line_tax` instead.
        """
        return tax_rate_for(cart_item.product)

    def _cart_line_tax(self, cart_item, discounted_total):
        """GST contained in a cart line's discounted total.

        Routes combo lines through the same component allocator the order write
        path uses. Both surfaces MUST agree to the paisa: the cart quotes this
        figure before payment and the placed order recomputes it, and the two
        drifting apart is exactly the class of bug `orders.pricing` exists to
        prevent.
        """
        if cart_item.item_type == 'combo' and cart_item.combo:
            return combo_line_tax(cart_item.combo, discounted_total)
        return extract_tax(discounted_total, self._cart_line_tax_rate(cart_item))

    def _cart_line_price(self, cart_item):
        """Unit final price for a cart line (variant-aware)."""
        if cart_item.item_type == 'product' and cart_item.variant:
            return Decimal(str(cart_item.variant.final_price))
        item = cart_item.combo if cart_item.item_type == 'combo' else cart_item.product
        if item is None:
            return Decimal('0')
        price = getattr(item, 'final_price', None)
        return Decimal(str(price if price is not None else getattr(item, 'price', 0)))

    def _compute_cart_tax(self, cart, subtotal, total_discount):
        """Sum of per-line GST CONTAINED IN the discounted line totals.

        Prices are GST-inclusive, so this is a disclosure figure carved out of
        the amount payable, not a charge added to it. Mirrors the per-line math
        used when an order is actually created, so the coupon preview and the
        placed order show the same tax figure.
        """
        tax = Decimal('0')
        for cart_item in cart.items.select_related('product', 'combo', 'variant').all():
            unit_price = self._cart_line_price(cart_item)
            quantity = cart_item.quantity
            line_total = unit_price * quantity
            if total_discount > 0 and subtotal > 0:
                line_discount = ((line_total / subtotal) * total_discount).quantize(Decimal('0.01'))
            else:
                line_discount = Decimal('0')
            discounted_total = (line_total - line_discount).quantize(Decimal('0.01'))
            tax += self._cart_line_tax(cart_item, discounted_total)
        return tax

    def _calculate_discount(self, price, coupon):
        """Absolute ₹ discount for `price` under `coupon`. Delegates to
        Coupon.discount_for(), which handles both percent and fixed coupons and
        clamps the discount to the subtotal (total floors at ₹0)."""
        if not coupon:
            return Decimal('0.00')
        return coupon.discount_for(price)

    @action(detail=False, methods=['post'])
    def validate_coupon(self, request):
        """
        Endpoint to validate coupon before placing order
        """
        coupon_code = request.data.get('coupon_code', '').strip()
        
        if not coupon_code:
            return Response({'error': 'Coupon code is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cart = Cart.objects.get(user=request.user)
        except Cart.DoesNotExist:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        if not cart.items.exists():
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate subtotal from cart to validate coupon against minimum
        subtotal = cart.total_price

        # Validate coupon
        coupon, error = self._validate_coupon(coupon_code, request.user, order_amount=subtotal)
        if error:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        # Absolute ₹ discount (percent or fixed, clamped to subtotal).
        total_discount = self._calculate_discount(subtotal, coupon)

        # Calculate order breakdown (per-product GST contained in each line).
        discounted_subtotal = subtotal - total_discount
        if discounted_subtotal <= 0:
            # Full-value coupon → zero-total order: shipping is waived and there
            # is no price left to carve tax out of, so the total is genuinely ₹0
            # (mirrors the placed-order path, §14.3).
            discounted_subtotal = Decimal('0')
            shipping_charge = Decimal('0')
            shipping_tax = Decimal('0')
            tax = Decimal('0')
            total_amount = Decimal('0')
        else:
            shipping_charge = Decimal('0') if discounted_subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_CHARGE
            # GST-inclusive pricing: `tax` is already part of discounted_subtotal
            # and must NOT be added again.
            tax = self._compute_cart_tax(cart, subtotal, total_discount)
            # Delivery is the one EXCLUSIVE-priced component: its GST is added on
            # top of the net fee, so unlike `tax` it IS an addend of the total.
            shipping_tax = shipping_tax_for(shipping_charge)
            total_amount = discounted_subtotal + shipping_charge + shipping_tax

        return Response({
            'valid': True,
            'coupon_code': coupon.code,
            'discount_type': coupon.discount_type,
            'discount_percent': coupon.discount_percent,
            'subtotal': float(subtotal),
            'discount_amount': float(total_discount),
            'discounted_subtotal': float(discounted_subtotal),
            'shipping_charge': float(shipping_charge),
            'shipping_tax': float(shipping_tax),
            'tax': float(tax),
            # All output GST on the order — goods + delivery. The cart summary
            # must quote this, or it shows a smaller GST than the invoice.
            'total_tax': float(tax + shipping_tax),
            'total_amount': float(total_amount),
            'savings': float(total_discount),
            'is_zero_total': total_amount == 0,
        })

    def create(self, request):
        """
        Create order with optional coupon validation and clear cart
        CART DELETION IS DONE AFTER TRANSACTION TO PREVENT ROLLBACK
        """
        from products.models import ProductComboItem

        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon_code = request.data.get('coupon_code', '').strip()
        coupon = None
        
        # Validate cart
        try:
            cart = Cart.objects.get(user=request.user)
        except Cart.DoesNotExist:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        if not cart.items.exists():
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        subtotal_for_validation = cart.total_price

        # Validate coupon if provided
        if coupon_code:
            coupon, error = self._validate_coupon(coupon_code, request.user, order_amount=subtotal_for_validation)
            if error:
                return Response(error, status=status.HTTP_400_BAD_REQUEST)

        # Store cart items data before transaction
        cart_items_data = []
        subtotal = Decimal('0')
        
        for cart_item in cart.items.select_related('product', 'combo', 'variant').all():
            # Handle both products and combos
            components = []  # (product_id, total_units) the line consumes from inventory
            if cart_item.item_type == 'product' and cart_item.product:
                item = cart_item.product
                item_name = cart_item.product.name
                variant = cart_item.variant

                # G1: never sell a delisted/inactive product, even if it is still
                # sitting in a cart from before it was hidden.
                if not item.is_active:
                    return Response({'error': f'{item_name} is no longer available'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if variant:
                    item_weight = variant.formatted_weight
                    item_stock = variant.stock
                    item_price = variant.final_price
                else:
                    item_weight = cart_item.product.formatted_weight
                    item_stock = cart_item.product.stock
                    item_price = cart_item.product.final_price if hasattr(cart_item.product, 'final_price') else cart_item.product.price
                product_ref = cart_item.product
            elif cart_item.item_type == 'combo' and cart_item.combo:
                item = cart_item.combo
                item_name = cart_item.combo.name

                # G1: a delisted combo cannot be ordered either.
                if not item.is_active:
                    return Response({'error': f'{item_name} is no longer available'},
                                    status=status.HTTP_400_BAD_REQUEST)

                # Use combo's own weight if available
                if cart_item.combo.weight and cart_item.combo.unit:
                    w = float(cart_item.combo.weight)
                    if w.is_integer():
                        w = int(w)
                    item_weight = f"{w}{cart_item.combo.unit}"
                else:
                    item_weight = "Combo"

                # G2: a combo's availability is governed by its COMPONENT stock,
                # and ordering it must consume that component inventory. The
                # component is a specific SIZE, so both the check and the draw
                # are against the variant — the legacy Product.stock mirror is
                # not what any sale reads.
                for ci in ProductComboItem.objects.filter(combo=item).select_related(
                        'variant', 'variant__product'):
                    required = ci.quantity * cart_item.quantity
                    label = f'{ci.variant.product.name} ({ci.variant.formatted_weight})'
                    if not ci.variant.is_active:
                        return Response({
                            'error': f'{label} (in {item_name}) is no longer available'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    if ci.variant.stock < required:
                        return Response({
                            'error': f'Insufficient stock for {label} (in {item_name}). '
                                     f'Available: {ci.variant.stock}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    components.append((ci.variant_id, required))

                item_stock = cart_item.quantity  # component checks above are authoritative
                item_price = cart_item.combo.final_price if hasattr(cart_item.combo, 'final_price') else cart_item.combo.price
                product_ref = None  # Combos don't have a product reference
                variant = None
            else:
                # Skip invalid items
                logger.warning(f"Skipping invalid cart item: {cart_item.id}")
                continue

            # Upper-bound the per-line quantity (defence in depth behind the cart
            # caps): an extreme value would overflow the money columns below.
            if cart_item.quantity > MAX_ITEM_QUANTITY:
                flag_suspicious(request, reason='order.line_quantity', value=cart_item.quantity)
                return Response({
                    'error': f'Quantity for {item_name} exceeds the maximum of {MAX_ITEM_QUANTITY}.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check stock availability
            if item_stock < cart_item.quantity:
                return Response({
                    'error': f'Insufficient stock for {item_name}. Available: {item_stock}'
                }, status=status.HTTP_400_BAD_REQUEST)

            cart_items_data.append({
                'item': item,
                'product': product_ref,  # Will be None for combos
                'variant': variant,  # Will be None for combos / legacy lines
                'item_type': cart_item.item_type,
                'product_name': item_name,
                'product_weight': item_weight,
                'quantity': cart_item.quantity,
                'item_price': item_price,
                # Per-product GST rate (%). Papad/papad katran are 0; default 5.
                'tax_rate': tax_rate_for(item),
                # Snapshotted for the same reason as the rate: the HSN summary on
                # a GST return is built from the lines BILLED in that period, so
                # re-classifying a product later must not rewrite past invoices.
                # '' for combos — a bundle has no single code; its components
                # carry theirs on the OrderItemComponent rows.
                'hsn_code': hsn_code_for(item),
                'components': components,  # combo component draws (empty for products)
            })
            subtotal += item_price * cart_item.quantity

        # Calculate discount (percent or fixed, clamped to subtotal).
        total_discount = self._calculate_discount(subtotal, coupon) if coupon else Decimal('0')
        discounted_subtotal = subtotal - total_discount

        # A full-value coupon that covers the whole subtotal produces a ZERO-TOTAL
        # order: shipping is waived, there is no price left to carve tax out of,
        # and it is placed straight as paid with no gateway call
        # (PAYMENT_INTEGRATION_PLAN.md §4.4/§14.3).
        is_zero_total = bool(coupon) and discounted_subtotal <= 0

        # Per-line money (proportional discount + the per-product GST CONTAINED
        # IN each discounted line total — prices are GST-inclusive). Computed
        # once here so the OrderItem rows and the order header tax agree exactly.
        tax = Decimal('0')
        for item_data in cart_items_data:
            item_price = item_data['item_price']
            quantity = item_data['quantity']
            item_total = item_price * quantity
            components = []

            if is_zero_total:
                # The whole line is discounted away — no tax, nothing to pay.
                item_discount = item_total.quantize(Decimal('0.01'))
                discounted_item_price = Decimal('0.00')
                discounted_item_total = Decimal('0.00')
                item_tax = Decimal('0.00')
            else:
                if total_discount > 0 and subtotal > 0:
                    item_discount = ((item_total / subtotal) * total_discount).quantize(Decimal('0.01'))
                else:
                    item_discount = Decimal('0')

                discounted_item_price = (item_price - (item_discount / quantity)).quantize(Decimal('0.01'))
                discounted_item_total = (discounted_item_price * quantity).quantize(Decimal('0.01'))

                if item_data['item_type'] == 'combo':
                    # A combo is a mixed supply: split the FINAL line amount back
                    # across its components and tax each at its own product's
                    # rate. Done after both discounts precisely because the split
                    # is linear in the same weights, so one pass on the final
                    # figure is exact and its parts sum to what was charged.
                    components = allocate_combo_components(
                        item_data['item'], discounted_item_total, quantity)
                    item_tax = sum((c['tax'] for c in components), Decimal('0.00'))
                    # The line's stored rate becomes the BLENDED effective rate —
                    # display only. The per-slab breakup reads the component rows,
                    # never this.
                    item_data['tax_rate'] = blended_rate(discounted_item_total, item_tax)
                else:
                    item_tax = extract_tax(discounted_item_total, item_data['tax_rate'])

            item_data['item_discount'] = item_discount
            item_data['discounted_item_price'] = discounted_item_price
            item_data['discounted_item_total'] = discounted_item_total
            item_data['item_tax'] = item_tax
            item_data['tax_components'] = components
            tax += item_tax

        # Calculate shipping and total
        if is_zero_total:
            total_discount = subtotal            # record the full waiver
            discounted_subtotal = Decimal('0')
            shipping_charge = Decimal('0')
            shipping_tax = Decimal('0')
            tax = Decimal('0')
            total_amount = Decimal('0.00')
        else:
            shipping_charge = Decimal('0') if discounted_subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_CHARGE
            # Two OPPOSITE tax conventions meet here, so read carefully:
            #   * goods `tax` is already INSIDE discounted_subtotal (MRP is
            #     GST-inclusive) — adding it would double-charge.
            #   * delivery is quoted NET, so its GST is a genuine addend.
            shipping_tax = shipping_tax_for(shipping_charge)
            total_amount = (discounted_subtotal + shipping_charge
                            + shipping_tax).quantize(Decimal('0.01'))

        # Belt-and-suspenders: refuse an order whose computed money values would
        # overflow the numeric(10,2) columns, returning a clean 400 instead of a
        # 500 DB error. (Should be unreachable given the per-line quantity cap.)
        if subtotal > MAX_ORDER_TOTAL or total_amount > MAX_ORDER_TOTAL:
            flag_suspicious(request, reason='order.total_overflow', value=str(total_amount))
            return Response({'error': 'Order total is too large. Please reduce quantities.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # UPI / online payments are capped at ₹1,00,000 per transaction by the
        # gateway, so refuse an ONLINE order above that with a clear message
        # (the customer can still place it as COD).
        if (serializer.validated_data.get('payment_method') == 'ONLINE'
                and total_amount > MAX_ONLINE_ORDER_TOTAL):
            return Response(
                {'error': f'Online payment is limited to ₹{MAX_ONLINE_ORDER_TOTAL:,} per order. '
                          f'Please choose Cash on Delivery or reduce your order.'},
                status=status.HTTP_400_BAD_REQUEST)

        # Create order in transaction
        try:
            with transaction.atomic():
                # Concurrency gate (§7.7): lock the Cart row FIRST and re-check
                # items under the lock so two concurrent creates from the same
                # user serialise here rather than both minting an order.
                #   • COD / zero-total orders are complete at placement and still
                #     empty the cart inside this txn (below), so the loser of a
                #     double-submit finds an empty cart and gets a clean 400.
                #   • ONLINE orders are only 'pending' here and DELIBERATELY keep
                #     the cart until payment is captured, so an abandoned payment
                #     doesn't strand the customer with an empty cart. The
                #     supersede step below is what makes that safe: it guarantees
                #     one open ONLINE order per user, so the double-submit loser
                #     cancels the winner's fresh order and replaces it — no
                #     duplicate order, no double stock reservation.
                locked_cart = Cart.objects.select_for_update().get(pk=cart.pk)
                if not locked_cart.items.exists():
                    raise ValueError('Cart is empty')

                # Supersede any earlier unpaid ONLINE order from this user. Because
                # ONLINE checkout no longer empties the cart, a customer who
                # abandoned a payment keeps their items and can check out again —
                # but their previous pending order is still holding reserved stock.
                # Cancel + restock it here (mirrors reconcile._cancel_abandoned and
                # the user/admin cancel paths via restore_order_stock), under the
                # canonical Order→Payment lock, before we reserve stock for the new
                # order. Runs regardless of the new order's method so a stale ONLINE
                # reservation is released even when the customer switches to COD.
                from payments.models import Payment
                stale_orders = (Order.objects
                                .select_for_update()
                                .filter(user=request.user, payment_method='ONLINE',
                                        payment_status='pending', status='pending',
                                        is_deleted=False))
                for stale in stale_orders:
                    Payment.objects.select_for_update().filter(order=stale).first()
                    restore_order_stock(stale)
                    stale.status = 'cancelled'
                    stale.payment_status = 'rejected'
                    stale.cancelled_at = timezone.now()
                    stale.save(update_fields=['status', 'payment_status',
                                              'cancelled_at', 'updated_at'])

                # A zero-total (full-coupon) order needs no gateway — place it
                # straight as confirmed + paid. Everything else starts pending.
                order_status = 'confirmed' if is_zero_total else 'pending'
                order_payment_status = 'paid' if is_zero_total else 'pending'

                # GST place of supply, resolved from the destination and frozen
                # onto the order. It decides the tax HEADS (CGST+SGST vs IGST)
                # for the identical amount, so it must be settled at placement
                # and never re-derived: an admin correcting the address later
                # would otherwise silently re-head an invoice already filed.
                # Unresolvable addresses fall back to the seller's own state.
                place_of_supply = place_of_supply_for(
                    state=serializer.validated_data.get('shipping_state'),
                    address=serializer.validated_data.get('shipping_address'),
                )

                # Create order
                order = Order.objects.create(
                    user=request.user,
                    subtotal=subtotal,
                    discount_amount=total_discount,
                    shipping_charge=shipping_charge,
                    shipping_tax=shipping_tax,
                    tax=tax,
                    total_amount=total_amount,
                    coupon=coupon,
                    status=order_status,
                    payment_status=order_payment_status,
                    place_of_supply_state_code=place_of_supply,
                    **serializer.validated_data
                )

                # Create order items, reusing the per-line money computed above
                # (proportional discount + per-product tax) so the rows match the
                # order header exactly.
                for item_data in cart_items_data:
                    item_price = item_data['item_price']
                    quantity = item_data['quantity']
                    item_discount = item_data['item_discount']
                    discounted_item_price = item_data['discounted_item_price']
                    discounted_item_total = item_data['discounted_item_total']
                    item_tax = item_data['item_tax']

                    # Create OrderItem with proper product/combo reference
                    order_item_data = {
                        'order': order,
                        'item_type': item_data['item_type'],
                        'product_name': item_data['product_name'],
                        'product_weight': item_data['product_weight'],
                        'quantity': quantity,
                        'price': item_price,
                        'discount_amount': item_discount,
                        'discounted_price': discounted_item_price,
                        'tax_amount': item_tax,
                        # Snapshot the rate too, so the bill can always reproduce
                        # the per-slab breakup even if the product is re-rated later.
                        'tax_rate': item_data['tax_rate'],
                        'hsn_code': item_data['hsn_code'],
                        'final_price': discounted_item_total,
                    }
                    
                    # Set product or combo reference based on item type
                    if item_data['item_type'] == 'product':
                        order_item_data['product'] = item_data['product']
                        order_item_data['variant'] = item_data['variant']
                    elif item_data['item_type'] == 'combo':
                        order_item_data['combo'] = item_data['item']

                    order_item = OrderItem.objects.create(**order_item_data)

                    # Persist a combo line's per-component GST split. This is what
                    # makes the tax invoice's per-slab summary reproducible: the
                    # combo's composition and its components' rates can both
                    # change later, so the bill cannot be rebuilt from the
                    # catalogue. Products need no such rows — their single line
                    # already carries its own rate.
                    if item_data.get('tax_components'):
                        OrderItemComponent.objects.bulk_create([
                            OrderItemComponent(
                                order_item=order_item,
                                variant=c['variant'],
                                product_name=c['variant'].product.name,
                                variant_label=c['variant'].formatted_weight or '',
                                quantity=c['quantity'],
                                tax_rate=c['tax_rate'],
                                hsn_code=c['hsn_code'],
                                allocated_amount=c['allocated'],
                                tax_amount=c['tax'],
                            )
                            for c in item_data['tax_components']
                        ])


                # Gather quantities for batch stock update. Stock lives on the
                # VARIANT — for plain product lines and for combo components
                # alike — and both are decremented under a row lock that
                # re-checks availability, so neither can oversell (G4).
                # The legacy Product.stock is only a mirror of the default
                # variant, tracked separately:
                #   hard_updates   — must NOT oversell (variant-less legacy
                #                    lines only); raise if stock is insufficient.
                #   mirror_updates — default-variant mirror; clamp at 0 because a
                #                    drifted legacy mirror should not fail an order.
                variant_updates = {}
                hard_updates = {}
                mirror_updates = {}

                for item_data in cart_items_data:
                    quantity = item_data['quantity']
                    if item_data['item_type'] == 'product':
                        variant = item_data.get('variant')
                        if variant:
                            variant_updates[variant.pk] = variant_updates.get(variant.pk, 0) + quantity
                        elif item_data.get('product'):
                            pk = item_data['product'].pk
                            hard_updates[pk] = hard_updates.get(pk, 0) + quantity
                    elif item_data['item_type'] == 'combo':
                        # G2: draw down each component SIZE's real inventory.
                        for variant_id, units in item_data.get('components', []):
                            variant_updates[variant_id] = variant_updates.get(variant_id, 0) + units

                from products.models import Product, ProductVariant

                # Batch reduce stock for variants (+ mirror default to product)
                low_stock_alerts = []
                # Per-variant stock before/after this order — used to detect
                # threshold crossings and, below, combo buildable counts.
                variant_before = {}
                variant_after = {}
                if variant_updates:
                    variants = list(ProductVariant.objects.select_for_update().filter(pk__in=variant_updates.keys()))
                    for variant in variants:
                        reduce_by = variant_updates[variant.pk]
                        if variant.stock < reduce_by:
                            raise ValueError(f'Insufficient stock for {variant.product.name}. Available: {variant.stock}')
                        before = variant.stock
                        variant.stock -= reduce_by
                        variant_before[variant.pk] = before
                        variant_after[variant.pk] = variant.stock
                        if variant.is_default:
                            mirror_updates[variant.product_id] = mirror_updates.get(variant.product_id, 0) + reduce_by
                        # Alert on a per-size threshold crossing. For a default
                        # variant the Product mirror below carries the same signal,
                        # so only alert here for NON-default sizes to avoid a
                        # duplicate email for the same physical stock.
                        threshold = variant.low_stock_threshold
                        if (not variant.is_default and before > threshold
                                and variant.stock <= threshold):
                            low_stock_alerts.append({
                                'name': f"{variant.product.name} ({variant.formatted_weight})",
                                'stock': variant.stock,
                                'threshold': threshold,
                            })
                    ProductVariant.objects.bulk_update(variants, ['stock'])

                # Batch reduce Product.stock under a row lock. Hard decrements
                # (legacy lines + combo components) are re-checked against the
                # LOCKED row, so two concurrent checkouts for the last unit can
                # never both succeed (G4). Mirror decrements clamp at 0.
                affected = set(hard_updates) | set(mirror_updates)
                # Per-product stock before/after this order — used to detect
                # threshold crossings for both products and (below) combos.
                stock_before = {}
                stock_after = {}
                if affected:
                    products = list(Product.objects.select_for_update().filter(pk__in=affected))
                    for product in products:
                        before = product.stock
                        hard = hard_updates.get(product.pk, 0)
                        if hard and product.stock < hard:
                            raise ValueError(
                                f'Insufficient stock for {product.name}. Available: {product.stock}'
                            )
                        product.stock -= hard
                        mirror = mirror_updates.get(product.pk, 0)
                        if mirror:
                            product.stock = max(0, product.stock - mirror)
                        stock_before[product.pk] = before
                        stock_after[product.pk] = product.stock
                        # Alert the owner only when THIS order crossed the
                        # threshold (was above it before, at/below it now) — so an
                        # already-low product doesn't re-email on every order.
                        threshold = product.low_stock_threshold
                        if before > threshold and product.stock <= threshold:
                            low_stock_alerts.append({
                                'name': product.name,
                                'stock': product.stock,
                                'threshold': threshold,
                            })
                    Product.objects.bulk_update(products, ['stock'])

                # Combo low-stock: a combo has no stock of its own, so we alert on
                # its *buildable count* (min over components of stock // per-combo
                # qty) crossing the combo's threshold. Only combos in THIS order can
                # have moved, and their components were all just locked above.
                #
                # The maps consulted MUST be the per-VARIANT ones: `components`
                # holds variant ids (checkout draws component stock from the
                # variant, not the legacy Product mirror). Reading the
                # product-keyed maps here made every lookup miss, so `before` was
                # always 0, the `before > threshold` guard was never true, and no
                # combo alert could ever fire.
                for item_data in cart_items_data:
                    if item_data['item_type'] != 'combo':
                        continue
                    combo = item_data['item']
                    line_qty = item_data['quantity'] or 1
                    components = item_data.get('components', [])
                    if not components:
                        continue

                    def _buildable(stock_map, components=components, line_qty=line_qty):
                        counts = []
                        for variant_id, units in components:
                            per_combo = (units // line_qty) or 1  # units is line total
                            counts.append(stock_map.get(variant_id, 0) // per_combo)
                        return min(counts) if counts else 0

                    threshold = combo.low_stock_threshold
                    avail_before = _buildable(variant_before)
                    avail_after = _buildable(variant_after)
                    if avail_before > threshold and avail_after <= threshold:
                        low_stock_alerts.append({
                            'name': f"{combo.name} (combo)",
                            'stock': avail_after,
                            'threshold': threshold,
                        })

                # Fire the low-stock alert only after the order transaction
                # actually commits, so a rolled-back order never emails.
                if low_stock_alerts:
                    transaction.on_commit(
                        lambda items=low_stock_alerts: send_low_stock_alert(items)
                    )

                # G5: increment coupon usage under a row lock and re-validate
                # against the LOCKED row, so a max_usage / single-use coupon can
                # never be over-redeemed by concurrent checkouts.
                if coupon:
                    locked_coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
                    reason = locked_coupon.get_invalid_reason(order_amount=subtotal, user=request.user)
                    if reason:
                        raise ValueError(reason)
                    prev_usage = locked_coupon.usage_count
                    locked_coupon.usage_count = models.F('usage_count') + 1
                    locked_coupon.save(update_fields=['usage_count'])

                    # Warn the owner as a capped coupon nears/hits its usage limit.
                    # This redemption raised the count by exactly 1, so comparing
                    # prev vs new against each boundary fires the email once, on the
                    # crossing — never on every remaining redemption.
                    if locked_coupon.max_usage:
                        import math
                        new_usage = prev_usage + 1
                        pct = getattr(settings, 'COUPON_USAGE_ALERT_PERCENT', 90)
                        alert_level = math.ceil(locked_coupon.max_usage * pct / 100)
                        crossed_warn = prev_usage < alert_level <= new_usage
                        crossed_full = prev_usage < locked_coupon.max_usage <= new_usage
                        if crossed_warn or crossed_full:
                            locked_coupon.usage_count = new_usage  # concrete value for the email
                            transaction.on_commit(
                                lambda c=locked_coupon: send_coupon_usage_alert(c))

                # Empty the cart ONLY for orders that are complete at placement:
                # COD (no gateway) and already-paid zero-total coupon orders. A
                # 'pending' ONLINE order intentionally KEEPS the cart until its
                # payment is captured (payments.services.mark_payment_captured
                # clears it then), so an abandoned/failed payment leaves the
                # customer's cart intact to retry — the supersede step above stops
                # the reserved stock from leaking across retries.
                if order.payment_method == 'COD' or order.payment_status == 'paid':
                    locked_cart.items.all().delete()

                # A zero-total (fully coupon-waived) order is placed already
                # 'paid', so its supply is committed here and its invoice is due
                # now — there is no capture event coming to raise one later. A COD
                # order is NOT invoiced here: it is invoiced at dispatch.
                from .invoicing import maybe_issue_invoice
                maybe_issue_invoice(order)

                # Transaction complete - prepare response data
                order_data = OrderDetailSerializer(order).data

        except ValueError as e:
            logger.warning(f"Order creation validation failed: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # Log the detail server-side; never echo the raw DB/internal error to
            # the client (it leaks schema details).
            logger.exception("Order creation failed")
            return Response(
                {'error': 'Could not place the order. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Generate order number
        order_number = f"ORD-{order.id:06d}"

        # Purchase analytics are captured by the analytics app via a post_save
        # signal on Order (see analytics/signals.py) — no inline call needed.

        # Order-placed confirmation email (best-effort, background thread).
        # Only send now for orders that are actually complete at placement: COD
        # (no gateway) or already-paid (e.g. zero-total coupon orders). ONLINE
        # orders are still 'pending' payment here — their confirmation is sent
        # once the payment is captured (payments.services.mark_payment_captured
        # → _on_commit_order_confirmation), so we must NOT send it before the
        # order/payment is verified.
        if order.payment_method == 'COD' or order.payment_status == 'paid':
            send_order_confirmation(order)
            send_new_order_admin_alert(order)

        return Response({
            'message': 'Order created successfully',
            'order_id': order.id,
            'order_number': order_number,
            'total_amount': float(total_amount),
            'order': order_data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Admin-only order edit (status, tracking number, shipping details).

        Two things make this override necessary instead of DRF's default save:

        1. **Restock parity.** Setting ``status='cancelled'`` here must return
           stock to inventory exactly like the `cancel` action does — otherwise
           the admin status dropdown silently drifts inventory. Both paths now
           funnel through ``restore_order_stock``.
        2. **Customer notifications.** A status change or a newly-entered
           tracking number emails the customer ("processing" / "on its way" /
           "delivered").

        Regular users may never edit an order directly — they can only cancel
        their own order via the `cancel` action. Editing (advancing status,
        adding tracking) is an admin power.
        """
        from rest_framework.exceptions import PermissionDenied
        from rest_framework.exceptions import ValidationError as DRFValidationError
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("You do not have permission to modify this order.")

        # Parse `refund_amount` BEFORE the transaction: a malformed number must
        # 400 without having written anything, and the format check needs no lock.
        # Absent/blank means "refund everything outstanding" — the old behaviour,
        # so a client that never sends the field keeps working unchanged.
        raw_refund = request.data.get('refund_amount', None)
        refund_amount_given = raw_refund is not None and str(raw_refund).strip() != ''
        refund_amount = None
        if refund_amount_given:
            try:
                refund_amount = Decimal(str(raw_refund).strip()).quantize(Decimal('0.01'))
            except (InvalidOperation, ValueError):
                return Response({'error': 'refund_amount must be a number.'},
                                status=status.HTTP_400_BAD_REQUEST)
            if refund_amount <= 0:
                return Response({'error': 'refund_amount must be greater than zero.'},
                                status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            obj = self.get_object()  # 404s if outside the caller's queryset
            # Canonical lock order (§7.2): Order first, then Payment — so an admin
            # status change can't interleave with an in-flight capture.
            order = Order.objects.select_for_update().get(pk=obj.pk)
            from payments.models import Payment
            Payment.objects.select_for_update().filter(order=order).first()

            old_status = order.status
            old_tracking = (order.tracking_number or '').strip()

            data = {k: v for k, v in request.data.items() if k in self.ADMIN_EDITABLE_FIELDS}
            new_status = data.get('status', old_status)

            valid_statuses = {c[0] for c in Order.STATUS_CHOICES}
            if new_status not in valid_statuses:
                return Response({'error': f'Invalid status: {new_status}'},
                                status=status.HTTP_400_BAD_REQUEST)

            cancelling = new_status == 'cancelled' and old_status != 'cancelled'
            if cancelling and old_status in ('delivered', 'delivering'):
                return Response(
                    {'error': f'Cannot cancel order with status: {old_status}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # A refund is only ever recorded against money we actually took —
            # captured online, or COD cash confirmed with the "Paid in cash"
            # tick. An unpaid, failed or rejected order has nothing to give back,
            # and recording one would write a ledger row and reverse GST that was
            # never collected, understating what is owed to the government.
            # Re-sending an amount on an already-'refunded' order is an
            # instalment, so that case is included. Checked BEFORE anything is
            # written, so it is a clean 400 with no rollback.
            recording_refund = new_status == 'refunded' and (
                old_status != 'refunded' or refund_amount_given)
            if recording_refund and not self._is_refundable_payment(order):
                hint = (' Tick "Paid in cash" first to record a COD return.'
                        if order.payment_method == 'COD' else '')
                return Response(
                    {'error': 'Only orders whose payment was received can be '
                              f'refunded (this one is {order.payment_method or "unknown"} / '
                              f'{order.payment_status or "unknown"}).{hint}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Apply the editable fields.
            if 'shipping_address' in data:
                order.shipping_address = data['shipping_address']
            if 'phone_number' in data:
                order.phone_number = data['phone_number']
            if 'payment_status' in data:
                order.payment_status = data['payment_status']
            if 'place_of_supply_state_code' in data:
                # Correcting where the supply was made. Validated against the
                # published GST state-code list rather than trusted: a code that
                # isn't a real state would put the order in a GSTR-1 bucket that
                # doesn't exist, and blanking it would silently reclassify the
                # order as historical/intra-state.
                code = str(data['place_of_supply_state_code'] or '').strip().zfill(2)
                if not state_name(code):
                    return Response(
                        {'error': 'place_of_supply_state_code must be a valid '
                                  'two-digit GST state code.'},
                        status=status.HTTP_400_BAD_REQUEST)
                if code != (order.place_of_supply_state_code or ''):
                    logger.info(
                        "Place of supply on order %s corrected %s -> %s by %s.",
                        order.pk, order.place_of_supply_state_code or '(unset)',
                        code, getattr(request.user, 'email', request.user.pk))
                order.place_of_supply_state_code = code
            if 'shipping_cost' in data:
                # Admin-entered courier cost. Validated here rather than trusted:
                # a blank field means "not recorded" (0), and a garbage value must
                # 400 instead of raising deep inside the ORM.
                raw = data['shipping_cost']
                try:
                    cost = Decimal(str(raw).strip() or '0')
                except (InvalidOperation, ValueError):
                    return Response({'error': 'shipping_cost must be a number.'},
                                    status=status.HTTP_400_BAD_REQUEST)
                if cost < 0 or cost > MAX_ORDER_TOTAL:
                    return Response({'error': 'shipping_cost is out of range.'},
                                    status=status.HTTP_400_BAD_REQUEST)
                order.shipping_cost = cost.quantize(Decimal('0.01'))
            if 'cod_paid' in data:
                # The "Paid in cash" tick. Only meaningful on a COD order — an
                # ONLINE order's money came through the gateway and its
                # payment_status is owned by the payments app, so accepting the
                # tick there would let an admin hand-mark an unpaid online order
                # as settled and bypass verification entirely.
                if order.payment_method != 'COD':
                    return Response(
                        {'error': 'cod_paid applies only to COD orders.'},
                        status=status.HTTP_400_BAD_REQUEST)
                want_paid = str(data['cod_paid']).lower() not in ('false', '0', 'none', '')
                if want_paid and order.cod_paid_at is None:
                    order.cod_paid_at = timezone.now()
                    order.cod_confirmed_by = request.user
                    order.payment_status = 'paid'
                    logger.info(
                        "COD cash confirmed on order %s by %s (%s).",
                        order.pk, getattr(request.user, 'email', request.user.pk),
                        order.total_amount)
                elif not want_paid and order.cod_paid_at is not None:
                    # Un-tick, for the misclick. Refusing to reverse would leave
                    # a permanent false record of cash received, which is worse
                    # than allowing the correction — but it is logged loudly,
                    # because un-ticking is how a genuine receipt would be hidden.
                    if order.refunded_amount and order.refunded_amount > 0:
                        return Response(
                            {'error': 'Cannot un-tick: a refund has already been '
                                      'recorded against this payment.'},
                            status=status.HTTP_400_BAD_REQUEST)
                    logger.warning(
                        "COD cash confirmation REVERSED on order %s by %s (was "
                        "confirmed by %s at %s).",
                        order.pk, getattr(request.user, 'email', request.user.pk),
                        getattr(order.cod_confirmed_by, 'email', None), order.cod_paid_at)
                    order.cod_paid_at = None
                    order.cod_confirmed_by = None
                    order.payment_status = 'pending'
            if 'tracking_number' in data:
                order.tracking_number = (data['tracking_number'] or '').strip()

            # Restock on the transition into 'cancelled', once (never on a no-op
            # re-cancel).
            #
            # ⚠ THIS MUST STAY BELOW EVERY `return Response(400)` ABOVE. Returning
            # from inside `transaction.atomic()` exits the context manager without
            # an exception, so the transaction COMMITS — a validation failure that
            # returns after this point would credit the stock back and then leave
            # the order live and unsaved (`order.save()` is never reached), so the
            # parcel still ships and `stock_restored_at` makes the eventual real
            # cancel a no-op. Inventory ends up permanently inflated. The refund
            # branch below raises instead of returning for the same reason.
            if cancelling:
                restore_order_stock(order)
                order.cancelled_at = timezone.now()

            order.status = new_status
            if new_status == 'delivered' and order.delivered_at is None:
                order.delivered_at = timezone.now()

            order.save()

            # Raise the tax invoice if this edit is the event that makes one due.
            # In practice that means a COD order reaching DISPATCH — the bill has
            # to travel with the goods, and COD cash is remitted by the courier
            # days later, so waiting for the "Paid in cash" tick would leave
            # delivered goods uninvoiced. (An online order is normally invoiced at
            # capture; this also covers an admin hand-setting payment_status.)
            # No-op when one already exists — an invoice is issued once, and
            # advancing shipped → delivered must not raise a second.
            from .invoicing import maybe_issue_invoice
            maybe_issue_invoice(order)

            # Flipping an order to 'refunded' by hand must reverse its GST and
            # give the goods back to stock, or the tax owed stays overstated and
            # inventory silently drains. Since refunds are manual-only (the
            # gateway webhook branch is disabled), this is the ONLY path that
            # records one. Eligibility was checked above.
            #
            # `refund_amount` is optional and defaults to the whole outstanding
            # balance. A partial IS allowed and still marks the order 'refunded'
            # (mark_refunded=True) — an amount a human deliberately typed is a
            # settled outcome. `refunded_amount` on the response is what says how
            # much; the flag alone no longer means "all of it".
            #
            # Re-sending an explicit amount on an already-'refunded' order records
            # a FURTHER partial, so a refund can be settled in instalments.
            if recording_refund:
                outstanding = refundable_balance(order)
                amount = refund_amount if refund_amount_given else outstanding
                # RAISE, don't return: `order.save()` above has already written
                # status='refunded' inside this transaction. A plain 400 response
                # would commit that write and leave the order marked refunded with
                # no ledger row behind it. The exception rolls the whole thing back
                # and DRF still renders it as a 400.
                if outstanding <= 0:
                    # Nothing left to give back. Silently accepting this used to
                    # leave the order reading 'refunded' with an empty ledger —
                    # a refund that shows on every screen but never happened.
                    raise DRFValidationError(
                        {'error': 'This order has nothing left to refund '
                                  f'(already refunded {order.refunded_amount} '
                                  f'of {order.total_amount}).'})
                if refund_amount_given and amount > outstanding:
                    raise DRFValidationError(
                        {'error': f'refund_amount exceeds the refundable balance '
                                  f'({outstanding}).'})
                record_refund(
                    order, amount, source='admin', mark_refunded=True,
                    note=(request.data.get('refund_note') or '')[:255])
                order.refresh_from_db()

        # Side-effect notifications, outside the transaction.
        # Product decision: routine status changes (confirmed → processing →
        # delivered …) must NOT email the customer. The ONLY status update that
        # notifies them is a newly-added tracking number (their parcel shipped).
        # Cancellation is handled separately by the `cancel` action below.
        new_tracking = (order.tracking_number or '').strip()
        tracking_added = bool(new_tracking) and new_tracking != old_tracking
        if tracking_added:
            send_order_status_email(order, status_changed=False, tracking_added=True)

        return Response(OrderDetailSerializer(order, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancel order and restore stock (both products AND combos).

        Customer-facing cancel path: a user may cancel their own order (admins
        may cancel any). Restock is delegated to the shared
        ``restore_order_stock`` helper so this behaves identically to an admin
        cancelling via the status dropdown.
        """
        with transaction.atomic():
            # Lock the order to prevent concurrent cancellations
            obj = self.get_object()
            if obj.user != request.user and not request.user.is_staff:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You do not have permission to cancel this order.")

            # Canonical lock order (§7.2): Order FIRST, then Payment. Locking the
            # Payment here serialises against an in-flight capture so a cancel and
            # a payment can't interleave into a "cancelled but paid" state.
            order = Order.objects.select_for_update().get(pk=obj.pk)
            from payments.models import Payment
            payment = Payment.objects.select_for_update().filter(order=order).first()

            if order.status in self.UNCANCELLABLE_STATUSES:
                return Response(
                    {'success': False, 'error': f'Cannot cancel order with status: {order.status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Never let a customer self-cancel an order whose money is actually
            # captured — that would restore stock and keep the payment with no
            # refund record (§7.8). Route them to support (refunds are phase 2).
            # A zero-total coupon order is 'paid' with NO Payment row → still
            # cancellable (nothing to refund). Staff may cancel + refund manually.
            if (payment and payment.status == 'completed'
                    and not (request.user.is_staff or request.user.is_superuser)):
                return Response(
                    {'success': False,
                     'error': 'This order is already paid. Please contact support to '
                              'cancel and arrange a refund.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            restore_order_stock(order)

            order.status = 'cancelled'
            order.cancelled_at = timezone.now()
            order.save(update_fields=['status', 'cancelled_at'])

        # Tell the customer their order was cancelled (best-effort).
        send_order_status_email(order, status_changed=True, tracking_added=False)

        return Response({
            'success': True,
            'message': 'Order cancelled successfully',
            'order': OrderDetailSerializer(order).data
        })

    def destroy(self, request, *args, **kwargs):
        """Soft-delete (move to Recycle Bin) — admin only.

        We deliberately do NOT hard-delete: an order is a financial record, and
        soft-deletion lets an admin recover it via ``restore``. Stock and payment
        state are left untouched (deletion is housekeeping, not cancellation), so
        an admin who wants to release stock should cancel the order first.
        """
        from rest_framework.exceptions import PermissionDenied
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("You do not have permission to delete this order.")

        order = self.get_object()
        if not order.is_deleted:
            order.is_deleted = True
            order.deleted_at = timezone.now()
            order.save(update_fields=['is_deleted', 'deleted_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """Restore a soft-deleted order out of the Recycle Bin — admin only."""
        from rest_framework.exceptions import PermissionDenied
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("You do not have permission to restore this order.")

        order = self.get_object()
        if not order.is_deleted:
            return Response(
                {'success': False, 'error': 'Order is not in the recycle bin.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.is_deleted = False
        order.deleted_at = None
        order.save(update_fields=['is_deleted', 'deleted_at'])
        return Response({
            'success': True,
            'message': 'Order restored successfully',
            'order': OrderDetailSerializer(order, context={'request': request}).data,
        })

    @action(detail=True, methods=['get'])
    def invoice(self, request, pk=None):
        """Return the PDF tax invoice for this order, if one has been ISSUED.

        Downloading is a reprint, never an issue event: the document is rendered
        from `Invoice.snapshot`, frozen when it was raised (see
        orders/invoicing.py). An order with no invoice therefore has nothing to
        serve and gets a 409 — which is the point. Previously this endpoint
        rendered a page headed TAX INVOICE for ANY order, including a pending
        unpaid one that L3 would auto-cancel fifteen minutes later.

        get_object() enforces ownership (or staff access) via get_queryset().
        """
        from django.http import HttpResponse
        from .models import Invoice

        order = self.get_object()
        invoice = Invoice.objects.filter(order_id=order.pk).first()
        if invoice is None:
            return Response(
                {'error': 'No tax invoice has been issued for this order yet.',
                 'code': 'invoice_not_issued',
                 # Say WHICH event is awaited — "not yet" alone sends an admin
                 # hunting for a broken download.
                 'detail': ('An invoice is issued once payment is confirmed '
                            '(online) or the order is dispatched (COD).')},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            from .invoice import generate_invoice_pdf
            pdf_bytes = generate_invoice_pdf(invoice)
        except ImportError:
            logger.error("reportlab is not installed; cannot generate invoice PDF")
            return Response(
                {'error': 'Invoice generation is not available on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Invoice rendering failed for invoice {invoice.number}: {e}")
            return Response(
                {'error': 'Failed to generate invoice'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Named by the INVOICE number, not the order id — that is the serial the
        # customer and their accountant will look for. '/' is not filename-safe.
        filename = f"invoice-{invoice.number.replace('/', '-')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['get'], url_path='credit-note')
    def credit_note(self, request, pk=None):
        """PDF credit note for one refund on this order — `?refund=<id>`.

        Defaults to the most recent refund, which is what a "download the credit
        note" button on a just-refunded order wants. Each instalment has its own
        document, so the id is how you reach the earlier ones; the number to ask
        for is on every refund in the order response (`credit_note_number`).

        get_object() enforces ownership (or staff access) via get_queryset(), and
        the refund is looked up WITHIN that order, so an id belonging to someone
        else's order 404s rather than rendering their money back to a stranger.
        """
        from django.http import HttpResponse

        order = self.get_object()
        refund_id = request.query_params.get('refund')
        refunds = order.refunds.all()
        refund = refunds.filter(pk=refund_id).first() if refund_id else refunds.first()
        if refund is None:
            return Response(
                {'error': 'No refund has been recorded on this order.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            from .invoice import credit_note_number, generate_credit_note_pdf
            pdf_bytes = generate_credit_note_pdf(refund)
        except ImportError:
            logger.error("reportlab is not installed; cannot generate credit note PDF")
            return Response(
                {'error': 'Credit note generation is not available on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Credit note generation failed for refund {refund.id}: {e}")
            return Response(
                {'error': 'Failed to generate credit note'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        filename = f"credit-note-{credit_note_number(refund)}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['get'], url_path='packing-slip')
    def packing_slip(self, request, pk=None):
        """Staff-only printable packing slip (address + items + COD amount —
        no prices). Used when packing parcels; distinct from the tax invoice."""
        from django.http import HttpResponse
        from rest_framework.exceptions import PermissionDenied

        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can download packing slips.")

        order = self.get_object()
        try:
            from .invoice import generate_packing_slip_pdf
            pdf_bytes = generate_packing_slip_pdf(order)
        except ImportError:
            logger.error("reportlab is not installed; cannot generate packing slip PDF")
            return Response(
                {'error': 'Packing slip generation is not available on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Packing slip generation failed for order {order.id}: {e}")
            return Response(
                {'error': 'Failed to generate packing slip'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        filename = f"packing-slip-ORD-{order.id:06d}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # Delivery bill: types the admin is allowed to upload, mapped to the
    # extension used when streaming it back. Images (a photo of the courier
    # receipt) and PDFs cover every real case.
    DELIVERY_BILL_TYPES = {
        'application/pdf': 'pdf',
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
    }
    MAX_DELIVERY_BILL_BYTES = 10 * 1024 * 1024  # 10 MB

    @staticmethod
    def _delivery_bill_bytes_match(content_type, head):
        """True if the file's leading bytes match the declared content-type.
        The declared type picks the extension AND the type we serve the file
        back with, so don't trust the client's header alone — a payload lying
        about its type (e.g. HTML labelled image/png) must be rejected."""
        if content_type == 'application/pdf':
            return head.startswith(b'%PDF')
        if content_type == 'image/jpeg':
            return head.startswith(b'\xff\xd8\xff')
        if content_type == 'image/png':
            return head.startswith(b'\x89PNG\r\n\x1a\n')
        if content_type == 'image/webp':
            return head[:4] == b'RIFF' and head[8:12] == b'WEBP'
        return False

    @action(detail=True, methods=['get', 'post', 'delete'],
            parser_classes=[MultiPartParser, FormParser])
    def delivery_bill(self, request, pk=None):
        """Admin-only delivery-bill store for an order.

        GET    — stream the uploaded bill inline (never a public storage URL).
        POST   — upload/replace the bill (multipart field ``file``).
        DELETE — remove the stored bill.

        Strictly staff/superuser only: the delivery bill is the admin's private
        record and must never be reachable by the order's customer.
        """
        from rest_framework.exceptions import PermissionDenied
        from django.http import FileResponse

        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can access delivery bills.")

        order = self.get_object()

        if request.method == 'GET':
            if not order.delivery_bill:
                return Response({'error': 'No delivery bill uploaded for this order.'},
                                status=status.HTTP_404_NOT_FOUND)
            try:
                fh = order.delivery_bill.open('rb')
            except Exception as e:
                logger.error(f"Failed to open delivery bill for order {order.id}: {e}")
                return Response({'error': 'Could not read the stored delivery bill.'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            ext = order.delivery_bill.name.rsplit('.', 1)[-1].lower()
            content_type = next(
                (ct for ct, e in self.DELIVERY_BILL_TYPES.items() if e == ext),
                'application/octet-stream',
            )
            resp = FileResponse(fh, content_type=content_type)
            resp['Content-Disposition'] = (
                f'inline; filename="delivery-bill-ORD-{order.id:06d}.{ext}"'
            )
            return resp

        if request.method == 'DELETE':
            if order.delivery_bill:
                order.delivery_bill.delete(save=False)
            order.delivery_bill = None
            order.delivery_bill_uploaded_at = None
            order.save(update_fields=['delivery_bill', 'delivery_bill_uploaded_at'])
            return Response({'success': True, 'message': 'Delivery bill removed.'})

        # POST — upload / replace
        upload = request.FILES.get('file')
        if not upload:
            return Response({'error': 'No file provided (expected multipart field "file").'},
                            status=status.HTTP_400_BAD_REQUEST)
        if upload.content_type not in self.DELIVERY_BILL_TYPES:
            return Response(
                {'error': 'Unsupported file type. Upload a PDF, JPG, PNG or WebP.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > self.MAX_DELIVERY_BILL_BYTES:
            return Response({'error': 'File too large (max 10 MB).'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Verify the magic bytes actually match the declared type.
        head = upload.read(12)
        upload.seek(0)
        if not self._delivery_bill_bytes_match(upload.content_type, head):
            return Response(
                {'error': 'The file does not look like a valid PDF, JPG, PNG or WebP.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Replace any existing bill so we don't orphan the old object.
        if order.delivery_bill:
            order.delivery_bill.delete(save=False)
        # Normalise the extension from the trusted content-type, not the filename.
        ext = self.DELIVERY_BILL_TYPES[upload.content_type]
        upload.name = f"bill.{ext}"
        order.delivery_bill = upload
        order.delivery_bill_uploaded_at = timezone.now()
        order.save(update_fields=['delivery_bill', 'delivery_bill_uploaded_at'])
        return Response({
            'success': True,
            'message': 'Delivery bill uploaded.',
            'has_delivery_bill': True,
            'delivery_bill_uploaded_at': order.delivery_bill_uploaded_at,
        }, status=status.HTTP_201_CREATED)

    def _export_orders_csv(self, queryset):
        """Render the given order queryset as a downloadable CSV.

        Accountant-friendly columns including the GST/tax split. One row per
        order (line-item detail lives on the invoice PDF)."""
        from admin_panel.utils import csv_response

        header = [
            'Order Number', 'Date', 'Customer Name', 'Customer Email', 'Phone',
            'Status', 'Payment Method', 'Payment Status',
            'Subtotal', 'Discount', 'Coupon', 'Taxable Amount', 'GST (Goods)', 'GST Rates',
            'Shipping Charged (Net)', 'GST on Shipping', 'Total GST',
            # Place of supply and the heads that follow from it. GSTR-1 Table 7
            # (B2C others) is bucketed BY place of supply, so without these
            # columns the return can't be built from this export at all. CGST +
            # SGST + IGST always sum back to Total GST — this is the same money
            # re-headed, never extra tax.
            'Place of Supply', 'POS Code', 'CGST', 'SGST', 'IGST',
            'Courier Cost', 'Delivery Margin',
            'Total', 'Refunded', 'GST Reversed', 'Net GST',
            'COD Paid At', 'COD Confirmed By',
            'Gateway Fee', 'Gateway GST (ITC)', 'Net Settlement',
            'Items', 'Shipping Address',
        ]

        def rows():
            # Plain iteration (not .iterator()) so get_queryset's
            # prefetch_related('items…') is honoured — .iterator() would drop it.
            for o in queryset:
                user = o.user
                name = (getattr(user, 'name', '') or
                        f"{user.first_name} {user.last_name}".strip() or
                        getattr(user, 'email', '')) if user else 'Guest'
                # Taxable value = the NET (pre-GST) amount, which is what a GST
                # return wants. Prices are GST-inclusive, so the discounted
                # subtotal still CONTAINS the tax and must have it removed.
                # Legacy (tax_inclusive=False) orders had GST added on top, so
                # their discounted subtotal is already net — don't subtract twice.
                taxable = (o.subtotal or 0) - (o.discount_amount or 0)
                if getattr(o, 'tax_inclusive', True):
                    taxable -= (o.tax or 0)
                # Which slabs made up the GST, e.g. "0%, 5%" — lets the accountant
                # spot mixed-rate orders without opening each invoice.
                rates = sorted({
                    Decimal(str(i.tax_rate or 0)) for i in o.items.all()
                    if (i.tax_amount or 0) > 0 or (i.tax_rate or 0) > 0
                })
                rate_label = ', '.join(f"{r:g}%" for r in rates)
                margin = (o.shipping_charge or 0) - (o.shipping_cost or 0)
                pay = getattr(o, 'payment', None)
                gw_fee = pay.gateway_fee if pay else ''
                gw_tax = pay.gateway_tax if pay else ''
                gw_net = pay.net_settlement if pay else ''
                items = '; '.join(
                    f"{i.product_name} x{i.quantity}" for i in o.items.all()
                )
                # Heads for the WHOLE order's output tax (goods + delivery),
                # which is what `Total GST` two columns to the left reports.
                heads = o.gst_heads
                yield [
                    f"ORD-{o.id:06d}",
                    o.created_at.strftime('%Y-%m-%d %H:%M'),
                    name,
                    getattr(user, 'email', '') if user else '',
                    o.phone_number or '',
                    o.status,
                    o.payment_method or '',
                    o.payment_status or '',
                    o.subtotal, o.discount_amount, (o.coupon_code or ''),
                    taxable, o.tax, rate_label,
                    # Shipping is billed NET + its own 18% GST, so the fee and
                    # its tax are separate columns. "Total GST" is the figure
                    # that belongs on the return — goods plus delivery.
                    o.shipping_charge, o.shipping_tax, o.total_tax,
                    o.place_of_supply_name,
                    o.place_of_supply_state_code or '',
                    heads['cgst'], heads['sgst'], heads['igst'],
                    o.shipping_cost, margin,
                    o.total_amount,
                    o.refunded_amount, o.refunded_tax,
                    o.total_tax - (o.refunded_tax or 0),
                    (o.cod_paid_at.strftime('%Y-%m-%d %H:%M') if o.cod_paid_at else ''),
                    (getattr(o.cod_confirmed_by, 'email', '') or '') if o.cod_confirmed_by else '',
                    # Razorpay's cut. `Gateway GST` is input tax credit — GST we
                    # PAID on a service, deductible from the output tax above.
                    # Blank for COD (no Payment row) rather than a misleading 0.
                    gw_fee, gw_tax, gw_net,
                    items,
                    (o.shipping_address or '').replace('\n', ', '),
                ]

        from django.utils import timezone
        filename = f"orders-{timezone.now().strftime('%Y%m%d')}.csv"
        # get_queryset already prefetches items/product, so the per-row items
        # join doesn't N+1.
        return csv_response(filename, header, rows())

    def list(self, request):
        """
        List orders.

        Admin view (`?scope=all`, staff only): the full order table, so the
        response is PAGINATED (PAGE_SIZE=12) — bounded work per request and it
        powers the admin's server-side Prev/Next. The admin sort param (applied
        in get_queryset) overrides the default order.

        Customer view (no admin params — the storefront's "My Orders"): only the
        caller's own orders, a naturally small set the storefront expects as a
        bare array, so it stays unpaginated.

        Which one you get follows the REQUEST, not the caller's role: staff
        browsing the storefront are customers there and get the customer view.
        Scope and shape are decided by the single `_wants_admin_list()` predicate
        so they can never disagree — a paginated envelope always means the
        all-orders scope, and a bare array always means own-orders-only.
        """
        is_admin = request.user.is_staff or request.user.is_superuser
        admin_view = self._wants_admin_list()
        if admin_view and not is_admin:
            # Explicit refusal beats silently serving the customer view: a
            # non-staff caller asking for the admin table has a permission
            # problem, and an empty-looking list would hide it.
            return Response({'error': 'Admin access required.'},
                            status=status.HTTP_403_FORBIDDEN)

        queryset = self.get_queryset()
        if not queryset.query.order_by:
            queryset = queryset.order_by('-created_at')

        # CSV export (admin view only): stream EVERY filtered row, ignoring
        # pagination, so the admin's accountant gets the whole selection in one
        # file. The active filters (status/date/search/…) already applied in
        # get_queryset.
        if admin_view and request.query_params.get('export') == 'csv':
            return self._export_orders_csv(queryset)

        if admin_view:
            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """
        Get detailed information about a specific order
        """
        order = self.get_object()
        serializer = self.get_serializer(order)
        return Response(serializer.data)
