from rest_framework import serializers
from .models import Payment, PaymentMethod


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'order', 'payment_id', 'payment_gateway', 'amount', 'status', 'created_at']


class CreateOrderSerializer(serializers.Serializer):
    """Input for POST /api/payments/create-order/."""
    order_id = serializers.IntegerField()


class VerifyPaymentSerializer(serializers.Serializer):
    """Input for POST /api/payments/verify/ — the three fields Razorpay Checkout
    hands back to the browser."""
    razorpay_order_id = serializers.CharField(max_length=200)
    razorpay_payment_id = serializers.CharField(max_length=200)
    razorpay_signature = serializers.CharField(max_length=512)

   
class PaymentMethodSerializer(serializers.ModelSerializer):
    masked_display = serializers.ReadOnlyField()
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = ['id', 'user', 'user_email', 'payment_type', 'is_default', 
                  'is_active', 'upi_id', 'card_last_four', 'card_brand', 
                  'card_expiry_month', 'card_expiry_year', 'gateway_token', 
                  'gateway_name', 'bank_name', 'wallet_provider', 
                  'masked_display', 'created_at', 'updated_at']
        read_only_fields = ['user', 'created_at', 'updated_at']
        extra_kwargs = {
            'gateway_token': {'write_only': True},
        }

    def validate(self, attrs):
        """
        Validate payment method data based on payment type
        """
        payment_type = attrs.get('payment_type')
        
        if payment_type == 'UPI':
            if not attrs.get('upi_id'):
                raise serializers.ValidationError({
                    'upi_id': 'UPI ID is required for UPI payment method'
                })
        
        elif payment_type == 'CARD':
            required_fields = ['card_last_four', 'card_brand', 'gateway_token']
            for field in required_fields:
                if not attrs.get(field):
                    raise serializers.ValidationError({
                        field: f'{field} is required for card payment method'
                    })
            
            # Validate expiry
            month = attrs.get('card_expiry_month')
            year = attrs.get('card_expiry_year')
            if month and (month < 1 or month > 12):
                raise serializers.ValidationError({
                    'card_expiry_month': 'Month must be between 1 and 12'
                })
        
        elif payment_type == 'NETBANKING':
            if not attrs.get('bank_name'):
                raise serializers.ValidationError({
                    'bank_name': 'Bank name is required for net banking'
                })
        
        elif payment_type == 'WALLET':
            if not attrs.get('wallet_provider'):
                raise serializers.ValidationError({
                    'wallet_provider': 'Wallet provider is required for wallet payment'
                })
        
        return attrs

    def create(self, validated_data):
        # Set user from request context
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class PaymentMethodCreateSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for creating payment methods
    """
    class Meta:
        model = PaymentMethod
        fields = ['payment_type', 'is_default', 'upi_id', 'card_last_four', 
                  'card_brand', 'card_expiry_month', 'card_expiry_year', 
                  'gateway_token', 'gateway_name', 'bank_name', 'wallet_provider']