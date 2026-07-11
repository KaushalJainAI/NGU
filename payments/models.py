from django.db import models
from orders.models import Order
from users.models import User
from django.core.validators import RegexValidator


class Payment(models.Model):
    """Payment Model for tracking payments"""
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_GATEWAY_CHOICES = [
        ('razorpay', 'Razorpay'),
        ('cod', 'Cash on Delivery'),
    ]

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    # For Razorpay this holds the razorpay_order_id (exists earliest, unique per
    # order) — see the payment_id convention in PAYMENT_INTEGRATION_PLAN.md §12.
    payment_id = models.CharField(max_length=200, unique=True)
    payment_gateway = models.CharField(max_length=20, choices=PAYMENT_GATEWAY_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    # First-class column for the captured payment id (the razorpay_payment_id),
    # in addition to the copy kept in transaction_details — easier reconciliation.
    razorpay_payment_id = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    # Error code/description from a payment.failed event, for support + retry UX.
    failure_reason = models.CharField(max_length=255, blank=True, null=True)
    failure_code = models.CharField(max_length=64, blank=True, null=True)
    transaction_details = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment {self.payment_id} - {self.status}"


class PaymentEvent(models.Model):
    """Append-only audit trail. Every payment state transition writes one row,
    inside the same atomic transaction as the state change, so history can never
    disagree with state (PAYMENT_INTEGRATION_PLAN.md §7.6a)."""
    SOURCE_CHOICES = [
        ('client', 'Client callback'),
        ('webhook', 'Webhook'),
        ('reconcile', 'Reconciliation job'),
        ('admin', 'Admin action'),
        ('system', 'System'),
    ]

    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name='events', null=True, blank=True
    )
    # Kept even when payment is null (e.g. orphan_payment / signature_invalid on
    # an order with no Payment row yet) so nothing fails silently.
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='payment_events', null=True, blank=True
    )
    event_type = models.CharField(max_length=64)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='system')
    from_status = models.CharField(max_length=20, blank=True, null=True)
    to_status = models.CharField(max_length=20, blank=True, null=True)
    message = models.TextField(blank=True, default='')
    # True for events a human needs to look at (exceptions queue).
    is_exception = models.BooleanField(default=False)
    # True once the exception has been acted on / dismissed by an admin.
    resolved = models.BooleanField(default=False)
    raw_payload = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['is_exception', 'resolved']),
            models.Index(fields=['payment', '-created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} ({self.source}) @ {self.created_at:%Y-%m-%d %H:%M}"


class ProcessedWebhookEvent(models.Model):
    """Idempotency ledger keyed on Razorpay's x-razorpay-event-id header. The
    unique constraint — not the advisory exists() check — is the authoritative
    guard against double-applying a redelivered webhook (§7.2)."""
    event_id = models.CharField(max_length=200, unique=True)
    event_type = models.CharField(max_length=64, blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['received_at'])]

    def __str__(self):
        return self.event_id


class PaymentMethod(models.Model):
    """
    Model to store user payment methods (NEVER store raw card numbers)
    """
    PAYMENT_TYPES = [
        ('UPI', 'UPI'),
        ('CARD', 'Card'),
        ('NETBANKING', 'Net Banking'),
        ('WALLET', 'Wallet'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # For UPI
    upi_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        validators=[RegexValidator(
            regex=r'^[\w\.\-]+@[\w]+$',
            message='Enter a valid UPI ID (e.g., user@paytm)'
        )]
    )

    # For Cards - ONLY store last 4 digits and token from payment gateway
    card_last_four = models.CharField(max_length=4, blank=True, null=True)
    card_brand = models.CharField(max_length=20, blank=True, null=True)
    card_expiry_month = models.PositiveSmallIntegerField(blank=True, null=True)
    card_expiry_year = models.PositiveSmallIntegerField(blank=True, null=True)
    
    # Payment gateway token/reference
    gateway_token = models.CharField(max_length=255, blank=True, null=True)
    gateway_name = models.CharField(max_length=50, blank=True, null=True)

    # For Net Banking
    bank_name = models.CharField(max_length=100, blank=True, null=True)

    # For Wallets
    wallet_provider = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = 'Payment Method'
        verbose_name_plural = 'Payment Methods'
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        if self.payment_type == 'UPI':
            return f"{self.user.email} - UPI ({self.upi_id})"
        elif self.payment_type == 'CARD':
            return f"{self.user.email} - {self.card_brand} ****{self.card_last_four}"
        elif self.payment_type == 'NETBANKING':
            return f"{self.user.email} - Net Banking ({self.bank_name})"
        else:
            return f"{self.user.email} - {self.wallet_provider}"

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Ensure only one default payment method per user
            if self.is_default:
                PaymentMethod.objects.filter(
                    user=self.user, 
                    is_default=True
                ).exclude(pk=self.pk).update(is_default=False)

    @property
    def masked_display(self):
        """Return a masked version for display"""
        if self.payment_type == 'UPI':
            return self.upi_id
        elif self.payment_type == 'CARD':
            return f"{self.card_brand} ending in {self.card_last_four}"
        elif self.payment_type == 'NETBANKING':
            return f"{self.bank_name}"
        else:
            return f"{self.wallet_provider} Wallet"
