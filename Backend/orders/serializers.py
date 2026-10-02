# serializers.py
from decimal import Decimal

from rest_framework import serializers
from .models import Order, OrderItem, OrderRefund
from .pricing import order_tax_breakdown


class OrderCreateSerializer(serializers.Serializer):
    shipping_address = serializers.CharField(max_length=500)
    phone_number = serializers.CharField(max_length=15)
    payment_method = serializers.ChoiceField(choices=['COD', 'ONLINE'])
    # Structured destination, for the GST place of supply. OPTIONAL by design:
    # checkout sends them (it has asked for both all along and merely flattened
    # them into shipping_address), but admin-created and legacy API callers do
    # not, and an order must never fail to place over a tax-reporting field.
    # When absent, the state is recovered by scanning shipping_address, and
    # failing that the seller's own state stands in — see place_of_supply.py.
    shipping_state = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default='')
    shipping_pincode = serializers.CharField(
        max_length=10, required=False, allow_blank=True, default='')


# ----- Shared item serializer for list/detail (aligned with frontend) -----

class OrderItemListSerializer(serializers.ModelSerializer):
    item_type = serializers.CharField()
    product_id = serializers.SerializerMethodField()
    combo_id = serializers.SerializerMethodField()
    variant_id = serializers.SerializerMethodField()
    product_name = serializers.CharField()
    weight = serializers.CharField(source='product_weight')
    image = serializers.SerializerMethodField()  # Add image field
    quantity = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "item_type",
            "product_id",
            "combo_id",
            "variant_id",
            "product_name",
            "weight",
            "image",  # Include image in fields
            "quantity",
            "price",
            "total",
            # Snapshot, so an order detail page reprints the classification the
            # bill was raised under rather than the catalogue's current one.
            # Blank on combo lines and on orders placed before it was captured.
            "hsn_code",
        ]

    def get_product_id(self, obj):
        return obj.product.id if obj.product else None

    def get_combo_id(self, obj):
        return obj.combo.id if obj.combo else None

    def get_variant_id(self, obj):
        return obj.variant_id

    def get_image(self, obj):
        """Get absolute image URL for product or combo"""
        request = self.context.get('request')
        image_url = None
        
        if obj.item_type == 'product' and obj.product and obj.product.image:
            image_url = obj.product.image.url
        elif obj.item_type == 'combo' and obj.combo and obj.combo.image:
            image_url = obj.combo.image.url
            
        if image_url and request:
            return request.build_absolute_uri(image_url)
        return image_url

    def get_total(self, obj):
        # Prefer final_price if present, else price * quantity
        if hasattr(obj, "final_price") and obj.final_price is not None:
            return obj.final_price
        return obj.price * obj.quantity


# ----- Shared admin-only payment detail -----

def _admin_payment_detail(order, request):
    """Return the Razorpay payment detail for an order — but ONLY for staff.

    Customers keep seeing just `payment_method`/`payment_status`; this nested
    object (transaction id + instrument + failure reason) is admin-panel only.
    Returns None for non-staff requests and for orders with no Payment row
    (e.g. COD). The instrument fields are populated from the webhook — see
    payments.services._extract_instrument_details.
    """
    if not (request and request.user and
            (request.user.is_staff or request.user.is_superuser)):
        return None
    pay = getattr(order, 'payment', None)  # OneToOne reverse; may not exist
    if pay is None:
        return None
    details = pay.transaction_details or {}
    return {
        'gateway': pay.payment_gateway,
        'status': pay.status,
        'razorpay_payment_id': pay.razorpay_payment_id,
        'method': details.get('method'),
        'vpa': details.get('vpa'),
        'card_last4': details.get('card_last4'),
        'card_network': details.get('card_network'),
        'card_type': details.get('card_type'),
        'bank': details.get('bank'),
        'wallet': details.get('wallet'),
        'failure_code': pay.failure_code,
        'failure_reason': pay.failure_reason,
        # Gateway's cut. Admin-only like the rest of this block — it is our cost
        # structure, not the customer's business. 0 means "not reported yet"
        # (a /verify/-only capture has no fee until the webhook lands), not free.
        'gateway_fee': str(pay.gateway_fee or 0),
        'gateway_tax': str(pay.gateway_tax or 0),
        'net_settlement': str(pay.net_settlement),
    }


# ----- Shared money behaviour for both order serializers -----

class OrderRefundSerializer(serializers.ModelSerializer):
    """A single refund on an order. Safe for customers — it is their own money
    coming back; only `source`/`note` are staff-flavoured, so they stay out."""

    credit_note_number = serializers.SerializerMethodField()

    class Meta:
        model = OrderRefund
        fields = ['id', 'amount', 'tax_amount', 'created_at', 'credit_note_number']

    def get_credit_note_number(self, obj):
        """Serial of the credit note evidencing this refund (`CN-000012`).

        Derived from the row's PK, so it costs no query and no column — see
        `orders.invoice.credit_note_number`. Exposed on every surface that shows
        a refund so the document can be cited without downloading it first.
        """
        from .invoice import credit_note_number
        return credit_note_number(obj)


class OrderMoneyMixin:
    """GST breakup + admin-private cost handling, shared by list and detail.

    Both serializers feed customer-facing surfaces ("My Orders" reads the LIST
    response), so neither may leak the courier cost and both must expose the same
    breakup. Kept as a mixin rather than cross-assigned methods because zero-arg
    `super()` binds to its defining class and would break if borrowed.
    """

    def get_tax_breakdown(self, obj):
        return order_tax_breakdown(obj)

    def get_total_tax(self, obj):
        """All output GST on the order: goods + delivery.

        Returned as a string like every other money field here, rather than
        letting DRF pass the raw Decimal through as a float.
        """
        return str(obj.total_tax)

    def get_taxable_value(self, obj):
        """Goods value net of the GST contained in it (inclusive orders only).

        None for legacy tax-exclusive orders, where `subtotal` was already net.
        """
        if not getattr(obj, 'tax_inclusive', True):
            return None
        return str((obj.subtotal or Decimal('0')) - (obj.tax or Decimal('0')))

    def get_place_of_supply(self, obj):
        """Where this supply was made, and how its GST is therefore headed.

        The amounts don't change with the place of supply — the same 5% is
        either CGST 2.5 + SGST 2.5 or IGST 5 — so this block adds heads to the
        existing `total_tax`, it does not add tax. `code` is blank on historical
        orders placed before it was captured; those are intra-state by
        definition (see the model field) and `name` still resolves, so the UI
        never has to render an empty place of supply.
        """
        heads = obj.gst_heads
        return {
            'code': obj.place_of_supply_state_code or '',
            'name': obj.place_of_supply_name,
            'is_interstate': obj.is_interstate,
            'cgst': str(heads['cgst']),
            'sgst': str(heads['sgst']),
            'igst': str(heads['igst']),
        }

    def get_invoice(self, obj):
        """The issued tax invoice's identity, or None if none has been issued.

        Drives whether a "Download invoice" button is shown at all. Without it
        the UI would offer the download on every order and the customer would
        hit a 409 on the ones that have no invoice yet — a pending payment, or a
        COD parcel not yet dispatched.

        Only the number and issue date: the document itself is a PDF from the
        invoice endpoint, and the snapshot is not something any client needs.
        """
        invoice = getattr(obj, 'invoice', None)  # OneToOne reverse; may not exist
        if invoice is None:
            return None
        return {'number': invoice.number, 'issued_at': invoice.issued_at}

    def to_representation(self, instance):
        """Strip the admin-private courier cost from customer responses.

        `shipping_cost` is what WE paid the courier — internal margin data. It is
        declared in `fields` so staff get it, and removed here for everyone else,
        mirroring how `delivery_bill` is kept admin-only.
        """
        data = super().to_representation(instance)
        request = self.context.get('request')
        if not (request and request.user and request.user.is_staff):
            data.pop('shipping_cost', None)
        return data


# ----- Detail serializer (full) -----

class OrderDetailSerializer(OrderMoneyMixin, serializers.ModelSerializer):
    items = OrderItemListSerializer(many=True, read_only=True)
    coupon_code = serializers.CharField(source='coupon.code', read_only=True)
    order_number = serializers.SerializerMethodField()
    # Issued tax invoice ({number, issued_at}) or None. See OrderMoneyMixin.
    invoice = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="discount_amount"
    )
    tax = serializers.DecimalField(max_digits=10, decimal_places=2)
    # Whether `tax` is CONTAINED IN `subtotal` (True — all current orders) or was
    # ADDED to reach `total` (False — orders placed before inclusive pricing).
    # The UI must branch on this or a historical order's breakdown won't add up.
    tax_inclusive = serializers.BooleanField(read_only=True)
    # Per-GST-slab breakup (0% papad vs 5% spices) so the customer's bill shows
    # what was taxed, not just the total. See `order_tax_breakdown`.
    tax_breakdown = serializers.SerializerMethodField()
    taxable_value = serializers.SerializerMethodField()
    total_tax = serializers.SerializerMethodField()
    # Destination state + the CGST/SGST/IGST heads that follow from it. Same
    # money as `total_tax`, split the way the return wants it.
    place_of_supply = serializers.SerializerMethodField()
    # Refunds: what went back to the customer, and the GST reversed with it.
    # Visible to the customer — it is their own money.
    refunds = OrderRefundSerializer(many=True, read_only=True)
    # Delivery fee actually charged on this order (0 when the order cleared the
    # free-shipping threshold). Exposed so the order breakdown adds up to `total`.
    shipping_charge = serializers.DecimalField(max_digits=10, decimal_places=2)
    total = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="total_amount"
    )
    # Admin-only metadata: whether a delivery bill has been uploaded and when.
    # Only a boolean + timestamp are exposed — never the storage URL — so this is
    # harmless even on a customer's own order response.
    has_delivery_bill = serializers.SerializerMethodField()
    # Admin-only nested Razorpay payment detail (None for customers / COD).
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "invoice",
            "status",
            "items",
            "subtotal",
            "tax",
            "tax_inclusive",
            "tax_breakdown",
            "taxable_value",
            "place_of_supply",
            "refunds",
            "refunded_amount",
            "refunded_tax",
            "refunded_at",
            "shipping_charge",
            "shipping_tax",
            "total_tax",
            "shipping_cost",
            "cod_paid_at",
            "discount",
            "total",
            "shipping_address",
            "phone_number",
            "payment_method",
            "payment_status",
            "payment",
            "tracking_number",
            "courier_name",
            "tracking_url",
            "coupon_code",
            "has_delivery_bill",
            "delivery_bill_uploaded_at",
            "created_at",
            "updated_at",
        ]

    def get_order_number(self, obj):
        return f"ORD-{obj.id:06d}"

    def get_has_delivery_bill(self, obj):
        return bool(obj.delivery_bill)

    def get_payment(self, obj):
        return _admin_payment_detail(obj, self.context.get('request'))


# ----- List serializer (richer, matches frontend Order interface) -----

class OrderListSerializer(OrderMoneyMixin, serializers.ModelSerializer):
    coupon_code = serializers.CharField(source='coupon.code', read_only=True)
    order_number = serializers.SerializerMethodField()
    # Issued tax invoice ({number, issued_at}) or None. See OrderMoneyMixin.
    invoice = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()
    items = OrderItemListSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="discount_amount"
    )
    tax = serializers.DecimalField(max_digits=10, decimal_places=2)
    # See OrderDetailSerializer — needed here too so the order cards in "My
    # Orders" and the admin table render the GST line under the right convention.
    tax_inclusive = serializers.BooleanField(read_only=True)
    # See OrderDetailSerializer — "My Orders" renders the same GST breakup as
    # checkout, so the per-slab rows must be on the list response too.
    tax_breakdown = serializers.SerializerMethodField()
    taxable_value = serializers.SerializerMethodField()
    total_tax = serializers.SerializerMethodField()
    # Destination state + the CGST/SGST/IGST heads that follow from it. Same
    # money as `total_tax`, split the way the return wants it.
    place_of_supply = serializers.SerializerMethodField()
    # Refunds: what went back to the customer, and the GST reversed with it.
    # Visible to the customer — it is their own money.
    refunds = OrderRefundSerializer(many=True, read_only=True)
    # See OrderDetailSerializer — the delivery fee is part of the breakdown the
    # customer's order card renders, so it must be present on the list response too.
    shipping_charge = serializers.DecimalField(max_digits=10, decimal_places=2)
    total = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="total_amount"
    )
    # Admin-only: the staff order list is the admin dashboard, so surface whether
    # a delivery bill exists (boolean + timestamp only, never the URL) to drive
    # the "View bill" vs "Upload bill" state in the admin UI.
    has_delivery_bill = serializers.SerializerMethodField()
    # Admin-only nested Razorpay payment detail (None for customers / COD). The
    # admin panel renders its order-detail dialog from the list response, so the
    # detail must be present here.
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "invoice",
            "customer_name",
            "customer_email",
            "status",
            "items",
            "subtotal",
            "tax",
            "tax_inclusive",
            "tax_breakdown",
            "taxable_value",
            "place_of_supply",
            "refunds",
            "refunded_amount",
            "refunded_tax",
            "refunded_at",
            "shipping_charge",
            "shipping_tax",
            "total_tax",
            "shipping_cost",
            "cod_paid_at",
            "discount",
            "total",
            "shipping_address",
            "phone_number",
            "payment_method",
            "payment_status",
            "payment",
            "tracking_number",
            "courier_name",
            "tracking_url",
            "has_delivery_bill",
            "delivery_bill_uploaded_at",
            "created_at",
            "updated_at",
            "coupon_code",
            "is_deleted",
            "deleted_at",
        ]

    def get_has_delivery_bill(self, obj):
        return bool(obj.delivery_bill)

    def get_payment(self, obj):
        return _admin_payment_detail(obj, self.context.get('request'))

    def get_order_number(self, obj):
        return f"ORD-{obj.id:06d}"

    def get_customer_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.email
        return "Guest"
    
    def get_customer_email(self, obj):
        return obj.user.email if obj.user else None

