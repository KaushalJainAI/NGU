from rest_framework import serializers
from .models import ReceivableAccount, Coupon
from orders.models import Order


class ReceivableAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceivableAccount
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class CouponSerializer(serializers.ModelSerializer):
    # Read-only convenience field so the admin UI can show who a special coupon
    # is bound to without a second lookup.
    assigned_user_email = serializers.EmailField(
        source='assigned_user.email', read_only=True, allow_null=True
    )

    class Meta:
        model = Coupon
        fields = [
            'id',
            'code',
            'discount_type',
            'discount_percent',
            'discount_amount',
            'assigned_user',
            'assigned_user_email',
            'is_active',
            'valid_until',
            'max_usage',
            'usage_count',
            'minimum_order_amount',
        ]
        read_only_fields = ['id', 'usage_count', 'assigned_user_email']

    def validate(self, attrs):
        """Enforce the percent/fixed contract (§14.4): a percent coupon needs a
        1–100 discount_percent; a fixed coupon needs a positive discount_amount."""
        # On partial update, fall back to the instance's current values.
        discount_type = attrs.get('discount_type') or getattr(self.instance, 'discount_type', 'percent')
        if discount_type == 'fixed':
            amount = attrs.get('discount_amount', getattr(self.instance, 'discount_amount', None))
            if amount is None or amount <= 0:
                raise serializers.ValidationError({
                    'discount_amount': 'A fixed coupon needs a positive ₹ amount.'
                })
        else:  # percent
            percent = attrs.get('discount_percent', getattr(self.instance, 'discount_percent', None))
            if percent is None or not (1 <= percent <= 100):
                raise serializers.ValidationError({
                    'discount_percent': 'A percentage coupon needs a value between 1 and 100.'
                })
        return attrs

    def is_valid(self, *, raise_exception=False):
        return super().is_valid(raise_exception=raise_exception)
    
class RecentOrderSerializer(serializers.ModelSerializer):
    customerName = serializers.SerializerMethodField()
    totalAmount = serializers.DecimalField(source='total_amount', max_digits=10, decimal_places=2)
    createdAt = serializers.DateTimeField(source='created_at')
    paymentMethod = serializers.CharField(source='payment_method')
    paymentStatus = serializers.CharField(source='payment_status')

    class Meta:
        model = Order
        fields = ['id', 'customerName', 'totalAmount', 'status', 'createdAt',
                  'paymentMethod', 'paymentStatus']
    
    def get_customerName(self, obj):
        if obj.user:
            name = f"{obj.user.first_name} {obj.user.last_name}".strip()
            return name if name else obj.user.email
        return "Guest"
    
from rest_framework import serializers
from .models import Policy

class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = ['type', 'content']


# ---------------------------------------------------------------------------
# Admin customer directory (read-only)
# ---------------------------------------------------------------------------

class AdminCustomerListSerializer(serializers.Serializer):
    """Row in the admin Customers list. Built from an annotated User queryset
    (order_count / total_spent annotations), hence a plain Serializer."""
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    email = serializers.EmailField()
    phone = serializers.CharField(allow_blank=True, allow_null=True)
    city = serializers.CharField(allow_blank=True, allow_null=True)
    state = serializers.CharField(allow_blank=True, allow_null=True)
    created_at = serializers.DateTimeField()
    order_count = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)

    def get_name(self, obj):
        return (getattr(obj, 'name', '') or f"{obj.first_name} {obj.last_name}".strip()
                or obj.email.split('@')[0])


class AdminCustomerOrderSerializer(serializers.ModelSerializer):
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ['id', 'order_number', 'status', 'payment_method',
                  'total_amount', 'created_at']

    def get_order_number(self, obj):
        return f"ORD-{obj.id:06d}"
