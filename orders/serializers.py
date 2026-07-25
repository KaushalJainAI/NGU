# serializers.py
from rest_framework import serializers
from .models import Order, OrderItem


class OrderCreateSerializer(serializers.Serializer):
    shipping_address = serializers.CharField(max_length=500)
    phone_number = serializers.CharField(max_length=15)
    payment_method = serializers.ChoiceField(choices=['COD', 'ONLINE'])
    # coupon_code = serializers.CharField(max_length=20, required=False, allow_blank=True)


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
    }


# ----- Detail serializer (full) -----

class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemListSerializer(many=True, read_only=True)
    coupon_code = serializers.CharField(source='coupon.code', read_only=True)
    order_number = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="discount_amount"
    )
    tax = serializers.DecimalField(max_digits=10, decimal_places=2)
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
            "status",
            "items",
            "subtotal",
            "tax",
            "shipping_charge",
            "discount",
            "total",
            "shipping_address",
            "phone_number",
            "payment_method",
            "payment_status",
            "payment",
            "tracking_number",
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

class OrderListSerializer(serializers.ModelSerializer):
    coupon_code = serializers.CharField(source='coupon.code', read_only=True)
    order_number = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()
    items = OrderItemListSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, source="discount_amount"
    )
    tax = serializers.DecimalField(max_digits=10, decimal_places=2)
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
            "customer_name",
            "customer_email",
            "status",
            "items",
            "subtotal",
            "tax",
            "shipping_charge",
            "discount",
            "total",
            "shipping_address",
            "phone_number",
            "payment_method",
            "payment_status",
            "payment",
            "tracking_number",
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

