from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

# Create your models here.

class ReceivableAccount(models.Model):
    """
    Model to store receivable account information
    """
    account_holder_name = models.CharField(max_length=255)
    upi_id = models.CharField(max_length=255, unique=True)
    bank_name = models.CharField(max_length=255, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)
    ifsc_code = models.CharField(max_length=20, blank=True)
    branch_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Receivable Account'
        verbose_name_plural = 'Receivable Accounts'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.account_holder_name} - {self.upi_id}"
        
    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_default:
                ReceivableAccount.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
    

class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('percent', 'Percentage'),
        ('fixed', 'Fixed amount (₹)'),
    ]

    code = models.CharField(max_length=20, unique=True)
    # discount_type='percent' uses discount_percent; 'fixed' uses discount_amount.
    discount_type = models.CharField(
        max_length=10, choices=DISCOUNT_TYPE_CHOICES, default='percent'
    )
    discount_percent = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        null=True, blank=True,
        help_text="Discount percentage (1-100) — used when discount_type='percent'"
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Flat ₹ off — used when discount_type='fixed'"
    )
    # Single-user special coupon: only this customer may redeem. null = global.
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='assigned_coupons',
        help_text="If set, only this customer can use the coupon."
    )
    is_active = models.BooleanField(default=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    max_usage = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum global uses")
    usage_count = models.PositiveIntegerField(default=0)
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def get_invalid_reason(self, order_amount=None, user=None):
        """Return a specific, user-facing reason this coupon cannot be applied,
        or None if it is valid. The message states the ACTUAL problem so the user
        can act on it (top up the order, stop retrying an expired code…)."""
        from django.utils import timezone
        if not self.is_active:
            return "This coupon is no longer active."
        if self.assigned_user_id and (user is None or getattr(user, 'id', None) != self.assigned_user_id):
            return "This coupon is not available for your account."
        if self.valid_until and self.valid_until < timezone.now():
            return "This coupon has expired."
        if self.max_usage is not None and self.usage_count >= self.max_usage:
            return "This coupon has reached its usage limit."
        if order_amount is not None and order_amount < self.minimum_order_amount:
            shortfall = self.minimum_order_amount - order_amount
            return (f"Add ₹{shortfall:.0f} more to use this coupon "
                    f"(minimum order ₹{self.minimum_order_amount:.0f}).")
        return None

    def is_valid(self, order_amount=None, user=None):
        """Backwards-compatible boolean; the specific reason lives in
        get_invalid_reason()."""
        return self.get_invalid_reason(order_amount, user=user) is None

    def discount_for(self, amount):
        """Absolute ₹ discount this coupon grants on `amount`, clamped so the
        discount never exceeds the subtotal (the total floors at ₹0). Handles
        both percent and fixed coupons."""
        amount = Decimal(str(amount))
        if amount <= 0:
            return Decimal('0.00')
        if self.discount_type == 'fixed':
            raw = Decimal(str(self.discount_amount or 0))
        else:
            pct = Decimal(str(self.discount_percent or 0))
            raw = amount * pct / Decimal('100')
        return min(raw, amount).quantize(Decimal('0.01'))

    def __str__(self):
        return self.code
    
class Policy(models.Model):
    POLICY_TYPES = [
        ('shipping', 'Shipping'),
        ('return', 'Return'),
        ('privacy', 'Privacy'),
    ]
    type = models.CharField(max_length=16, choices=POLICY_TYPES, unique=True)
    content = models.TextField()

    def __str__(self):
        return f"{self.get_type_display()} Policy"
    


    

