"""
Order Views - Order Management API

Architecture:
- OrderViewSet: Complete order CRUD with role-based filtering
  - Regular users: see only their orders
  - Admins (is_staff): see all orders

Order Creation Flow:
1. Validate cart exists and has items
2. Validate coupon if provided (checks is_active, valid_until)
3. Calculate totals: subtotal, discount, env-configured shipping, per-line tax
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
from django.db import transaction, models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from decimal import Decimal, InvalidOperation
import logging
from .models import Order, OrderItem
from .serializers import OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer
from cart.models import Cart
from admin_panel.models import Coupon
from spices_backend.limits import (
    MAX_ITEM_QUANTITY, MAX_ORDER_TOTAL, MAX_ONLINE_ORDER_TOTAL,
    SHIPPING_CHARGE, FREE_SHIPPING_THRESHOLD, DEFAULT_TAX_RATE,
)
from spices_backend.abuse import flag_suspicious
from .emails import send_order_confirmation, send_order_status_email, send_new_order_admin_alert

logger = logging.getLogger(__name__)


def restore_order_stock(order):
    """Give an order's stock back to inventory (products, variants, and combo
    components), mirroring exactly what checkout consumed.

    MUST be called inside a `transaction.atomic()` block with `order` already
    locked (``select_for_update``). This is the single source of truth for
    restocking so every cancel path — the customer `cancel` action and the admin
    status change — restores inventory identically. The caller is responsible for
    setting ``order.status``/``cancelled_at`` afterwards.
    """
    from products.models import Product, ProductVariant, ProductComboItem

    variant_updates = {}
    product_updates = {}

    for item in order.items.select_related('product', 'combo', 'variant').all():
        if item.item_type == 'product' and item.variant:
            variant_updates[item.variant.pk] = variant_updates.get(item.variant.pk, 0) + item.quantity
        elif item.product:
            product_updates[item.product.pk] = product_updates.get(item.product.pk, 0) + item.quantity
        elif item.combo:
            # G2 symmetry: a combo consumed its component products at checkout,
            # so cancelling must give that inventory back.
            for ci in ProductComboItem.objects.filter(combo=item.combo).select_related('product'):
                product_updates[ci.product_id] = product_updates.get(ci.product_id, 0) + ci.quantity * item.quantity

    # Batch restore stock for variants (+ mirror default to product)
    if variant_updates:
        variants = list(ProductVariant.objects.select_for_update().filter(pk__in=variant_updates.keys()))
        for variant in variants:
            restore_by = variant_updates[variant.pk]
            variant.stock += restore_by
            if variant.is_default:
                product_updates[variant.product_id] = product_updates.get(variant.product_id, 0) + restore_by
        ProductVariant.objects.bulk_update(variants, ['stock'])

    # Batch restore stock for products (legacy lines + default mirror + combo components)
    if product_updates:
        products = list(Product.objects.select_for_update().filter(pk__in=product_updates.keys()))
        for product in products:
            product.stock += product_updates[product.pk]
        Product.objects.bulk_update(products, ['stock'])


class OrderViewSet(viewsets.ModelViewSet):
    # Fields an admin may edit via PATCH/PUT. Everything else on an order
    # (money, items, user…) is immutable through the API.
    ADMIN_EDITABLE_FIELDS = {'status', 'tracking_number', 'shipping_address',
                             'phone_number', 'payment_status'}
    # Statuses from which an order can no longer be cancelled.
    UNCANCELLABLE_STATUSES = {'delivered', 'delivering', 'cancelled'}
    permission_classes = [IsAuthenticated]

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

    def get_queryset(self):
        user = self.request.user
        # Admin/superusers can see all orders
        if user.is_staff or user.is_superuser:
            qs = Order.objects.all().prefetch_related(
                'items__product', 'items__combo', 'items__variant').select_related('user')
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
        # Regular users only see their own, non-deleted orders
        return Order.objects.filter(user=user, is_deleted=False).prefetch_related(
            'items__product', 'items__combo', 'items__variant')

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
        # ISO YYYY-MM-DD from the admin panel's date inputs.
        for key, lookup in (('date_from', 'created_at__date__gte'), ('date_to', 'created_at__date__lte')):
            raw = (params.get(key) or '').strip()
            if raw:
                parsed = parse_date(raw)
                if parsed:
                    qs = qs.filter(**{lookup: parsed})

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
        """GST rate (%) for a cart line, taken from its product or combo."""
        if cart_item.item_type == 'combo' and cart_item.combo:
            source = cart_item.combo
        else:
            source = cart_item.product
        return Decimal(str(getattr(source, 'tax_rate', DEFAULT_TAX_RATE) or 0))

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
        """Sum of per-line GST after distributing the order discount proportionally.

        Mirrors the per-line math used when an order is actually created, so the
        coupon preview and the placed order show the same tax figure.
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
            rate = self._cart_line_tax_rate(cart_item)
            tax += (discounted_total * rate / Decimal('100')).quantize(Decimal('0.01'))
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

        # Calculate order breakdown (per-product GST, summed across lines).
        discounted_subtotal = subtotal - total_discount
        if discounted_subtotal <= 0:
            # Full-value coupon → zero-total order: shipping + tax are waived so
            # the total is genuinely ₹0 (mirrors the placed-order path, §14.3).
            discounted_subtotal = Decimal('0')
            shipping_charge = Decimal('0')
            tax = Decimal('0')
            total_amount = Decimal('0')
        else:
            shipping_charge = Decimal('0') if discounted_subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_CHARGE
            tax = self._compute_cart_tax(cart, subtotal, total_discount)
            total_amount = discounted_subtotal + shipping_charge + tax

        return Response({
            'valid': True,
            'coupon_code': coupon.code,
            'discount_type': coupon.discount_type,
            'discount_percent': coupon.discount_percent,
            'subtotal': float(subtotal),
            'discount_amount': float(total_discount),
            'discounted_subtotal': float(discounted_subtotal),
            'shipping_charge': float(shipping_charge),
            'tax': float(tax),
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
                # and ordering it must consume that component inventory. Validate
                # every component up front and remember how many units to draw.
                for ci in ProductComboItem.objects.filter(combo=item).select_related('product'):
                    required = ci.quantity * cart_item.quantity
                    if ci.product.stock < required:
                        return Response({
                            'error': f'Insufficient stock for {ci.product.name} (in {item_name}). '
                                     f'Available: {ci.product.stock}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    components.append((ci.product_id, required))

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
                'tax_rate': Decimal(str(getattr(item, 'tax_rate', DEFAULT_TAX_RATE) or 0)),
                'components': components,  # combo component draws (empty for products)
            })
            subtotal += item_price * cart_item.quantity

        # Calculate discount (percent or fixed, clamped to subtotal).
        total_discount = self._calculate_discount(subtotal, coupon) if coupon else Decimal('0')
        discounted_subtotal = subtotal - total_discount

        # A full-value coupon that covers the whole subtotal produces a ZERO-TOTAL
        # order: shipping + tax are waived and it is placed straight as paid with
        # no gateway call (PAYMENT_INTEGRATION_PLAN.md §4.4/§14.3).
        is_zero_total = bool(coupon) and discounted_subtotal <= 0

        # Per-line money (proportional discount + per-product tax). Computed once
        # here so the OrderItem rows, the order header tax, and the grand total
        # all agree exactly — the header tax is the SUM of the line taxes, which
        # also fixes the old paisa-level mismatch from a flat order-level tax.
        tax = Decimal('0')
        for item_data in cart_items_data:
            item_price = item_data['item_price']
            quantity = item_data['quantity']
            item_total = item_price * quantity

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
                item_tax = (discounted_item_total * item_data['tax_rate'] / Decimal('100')).quantize(Decimal('0.01'))

            item_data['item_discount'] = item_discount
            item_data['discounted_item_price'] = discounted_item_price
            item_data['discounted_item_total'] = discounted_item_total
            item_data['item_tax'] = item_tax
            tax += item_tax

        # Calculate shipping and total
        if is_zero_total:
            total_discount = subtotal            # record the full waiver
            discounted_subtotal = Decimal('0')
            shipping_charge = Decimal('0')
            tax = Decimal('0')
            total_amount = Decimal('0.00')
        else:
            shipping_charge = Decimal('0') if discounted_subtotal >= FREE_SHIPPING_THRESHOLD else SHIPPING_CHARGE
            total_amount = (discounted_subtotal + shipping_charge + tax).quantize(Decimal('0.01'))

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

                # Create order
                order = Order.objects.create(
                    user=request.user,
                    subtotal=subtotal,
                    discount_amount=total_discount,
                    shipping_charge=shipping_charge,
                    tax=tax,
                    total_amount=total_amount,
                    coupon=coupon,
                    status=order_status,
                    payment_status=order_payment_status,
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
                        'final_price': discounted_item_total,
                    }
                    
                    # Set product or combo reference based on item type
                    if item_data['item_type'] == 'product':
                        order_item_data['product'] = item_data['product']
                        order_item_data['variant'] = item_data['variant']
                    elif item_data['item_type'] == 'combo':
                        order_item_data['combo'] = item_data['item']

                    OrderItem.objects.create(**order_item_data)
                    
                # Gather quantities for batch stock update. Stock lives on the
                # variant; the legacy Product.stock is kept in sync for the
                # default variant. We track two kinds of Product.stock decrement:
                #   hard_updates   — must NOT oversell (legacy lines + G2 combo
                #                    components); raise if stock is insufficient.
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
                        # G2: draw down each component product's real inventory.
                        for product_id, units in item_data.get('components', []):
                            hard_updates[product_id] = hard_updates.get(product_id, 0) + units

                from products.models import Product, ProductVariant

                # Batch reduce stock for variants (+ mirror default to product)
                if variant_updates:
                    variants = list(ProductVariant.objects.select_for_update().filter(pk__in=variant_updates.keys()))
                    for variant in variants:
                        reduce_by = variant_updates[variant.pk]
                        if variant.stock < reduce_by:
                            raise ValueError(f'Insufficient stock for {variant.product.name}. Available: {variant.stock}')
                        variant.stock -= reduce_by
                        if variant.is_default:
                            mirror_updates[variant.product_id] = mirror_updates.get(variant.product_id, 0) + reduce_by
                    ProductVariant.objects.bulk_update(variants, ['stock'])

                # Batch reduce Product.stock under a row lock. Hard decrements
                # (legacy lines + combo components) are re-checked against the
                # LOCKED row, so two concurrent checkouts for the last unit can
                # never both succeed (G4). Mirror decrements clamp at 0.
                affected = set(hard_updates) | set(mirror_updates)
                if affected:
                    products = list(Product.objects.select_for_update().filter(pk__in=affected))
                    for product in products:
                        hard = hard_updates.get(product.pk, 0)
                        if hard and product.stock < hard:
                            raise ValueError(
                                f'Insufficient stock for {product.name}. Available: {product.stock}'
                            )
                        product.stock -= hard
                        mirror = mirror_updates.get(product.pk, 0)
                        if mirror:
                            product.stock = max(0, product.stock - mirror)
                    Product.objects.bulk_update(products, ['stock'])

                # G5: increment coupon usage under a row lock and re-validate
                # against the LOCKED row, so a max_usage / single-use coupon can
                # never be over-redeemed by concurrent checkouts.
                if coupon:
                    locked_coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
                    reason = locked_coupon.get_invalid_reason(order_amount=subtotal, user=request.user)
                    if reason:
                        raise ValueError(reason)
                    locked_coupon.usage_count = models.F('usage_count') + 1
                    locked_coupon.save(update_fields=['usage_count'])

                # Empty the cart ONLY for orders that are complete at placement:
                # COD (no gateway) and already-paid zero-total coupon orders. A
                # 'pending' ONLINE order intentionally KEEPS the cart until its
                # payment is captured (payments.services.mark_payment_captured
                # clears it then), so an abandoned/failed payment leaves the
                # customer's cart intact to retry — the supersede step above stops
                # the reserved stock from leaking across retries.
                if order.payment_method == 'COD' or order.payment_status == 'paid':
                    locked_cart.items.all().delete()

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
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("You do not have permission to modify this order.")

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

            # Restock BEFORE flipping status, once, only on the transition into
            # 'cancelled' (never on a no-op re-cancel).
            if cancelling:
                restore_order_stock(order)
                order.cancelled_at = timezone.now()

            # Apply the editable fields.
            if 'shipping_address' in data:
                order.shipping_address = data['shipping_address']
            if 'phone_number' in data:
                order.phone_number = data['phone_number']
            if 'payment_status' in data:
                order.payment_status = data['payment_status']
            if 'tracking_number' in data:
                order.tracking_number = (data['tracking_number'] or '').strip()
            order.status = new_status
            if new_status == 'delivered' and order.delivered_at is None:
                order.delivered_at = timezone.now()

            order.save()

        # Side-effect notifications, outside the transaction.
        new_tracking = (order.tracking_number or '').strip()
        status_changed = new_status != old_status
        tracking_added = bool(new_tracking) and new_tracking != old_tracking
        send_order_status_email(order, status_changed=status_changed,
                                tracking_added=tracking_added)

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
        """
        Generate and return a PDF tax invoice / bill for the order.
        Filled dynamically from the order, its user, and its line items.
        get_object() enforces ownership (or staff access) via get_queryset().
        """
        from django.http import HttpResponse

        order = self.get_object()
        try:
            from .invoice import generate_invoice_pdf
            pdf_bytes = generate_invoice_pdf(order)
        except ImportError:
            logger.error("reportlab is not installed; cannot generate invoice PDF")
            return Response(
                {'error': 'Invoice generation is not available on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(f"Invoice generation failed for order {order.id}: {e}")
            return Response(
                {'error': 'Failed to generate invoice'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        filename = f"invoice-ORD-{order.id:06d}.pdf"
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
            'Subtotal', 'Discount', 'Coupon', 'Taxable Amount', 'GST', 'Shipping',
            'Total', 'Items', 'Shipping Address',
        ]

        def rows():
            # Plain iteration (not .iterator()) so get_queryset's
            # prefetch_related('items…') is honoured — .iterator() would drop it.
            for o in queryset:
                user = o.user
                name = (getattr(user, 'name', '') or
                        f"{user.first_name} {user.last_name}".strip() or
                        getattr(user, 'email', '')) if user else 'Guest'
                # Taxable amount = discounted subtotal (tax is charged on it).
                taxable = (o.subtotal or 0) - (o.discount_amount or 0)
                items = '; '.join(
                    f"{i.product_name} x{i.quantity}" for i in o.items.all()
                )
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
                    taxable, o.tax, o.shipping_charge, o.total_amount,
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

        Staff/admin: the full order table, so the response is PAGINATED
        (PAGE_SIZE=12) — bounded work per request and it powers the admin's
        server-side Prev/Next. The admin sort param (applied in get_queryset)
        overrides the default order.

        Customer: only their own orders — a naturally small set that the
        storefront expects as a bare array, so it stays unpaginated.
        """
        queryset = self.get_queryset()
        if not queryset.query.order_by:
            queryset = queryset.order_by('-created_at')

        # CSV export (staff only): stream EVERY filtered row, ignoring pagination,
        # so the admin's accountant gets the whole selection in one file. The
        # active filters (status/date/search/…) already applied in get_queryset.
        if (request.user.is_staff or request.user.is_superuser) and \
                request.query_params.get('export') == 'csv':
            return self._export_orders_csv(queryset)

        if request.user.is_staff or request.user.is_superuser:
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
