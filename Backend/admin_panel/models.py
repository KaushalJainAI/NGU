from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal


class Expense(models.Model):
    """One business expense, entered by an admin. Feeds the monthly summary."""
    CATEGORIES = [
        ('raw_material', 'Raw material / purchases'),
        ('packaging', 'Packaging'),
        ('marketing', 'Marketing'),
        ('rent_utilities', 'Rent & utilities'),
        ('salary', 'Salary & wages'),
        ('other', 'Other'),
    ]
    PAYMENT_MODES = [('cash', 'Cash'), ('bank', 'Bank transfer'), ('upi', 'UPI'), ('card', 'Card')]

    date = models.DateField(db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    vendor = models.CharField(max_length=120, blank=True, default='')
    description = models.CharField(max_length=255, blank=True, default='')
    # Total paid, GST INCLUDED.
    amount = models.DecimalField(max_digits=12, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])
    # GST contained inside `amount` (0 when the bill has none).
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                     validators=[MinValueValidator(0)])
    # True when this GST can be claimed back as input tax credit.
    itc_eligible = models.BooleanField(default=False)
    bill_number = models.CharField(max_length=60, blank=True, default='')
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='bank')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']

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
    
class DeletedRecord(models.Model):
    """Recycle Bin entry for a row removed through an admin DELETE.

    Products, combos, sizes and orders are soft-deleted on their own tables (an
    `is_active` / `is_deleted` flag) because history points at them. Everything
    else an admin can delete — a coupon, a review, an expense, a gallery image,
    a payment account, a contact message — used to be a plain SQL DELETE with no
    way back. Those rows now land here first: `payload` holds the serialized row
    (plus whatever its deletion cascaded to or nulled), and `restore` puts it
    back under its original primary key. See admin_panel/recycle.py.

    A snapshot table rather than a `deleted_at` column on each model, on
    purpose: a soft-delete flag has to be remembered by every query that ever
    reads the table (rating averages, coupon validation, the books summary…),
    and one forgotten filter resurrects a deleted row somewhere it matters.
    Here the row is genuinely gone until it is restored.
    """
    # Short machine name the panel groups and translates by, e.g. 'coupon'.
    kind = models.CharField(max_length=40, db_index=True)
    model_label = models.CharField(max_length=100)   # 'admin_panel.coupon'
    object_pk = models.CharField(max_length=64)
    # What the admin sees in the bin — captured at delete time, because the row
    # it describes no longer exists to be asked.
    label = models.CharField(max_length=255)
    preview_url = models.CharField(max_length=500, blank=True, default='')
    payload = models.JSONField()
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    deleted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-deleted_at', '-id']

    def __str__(self):
        return f"{self.kind}: {self.label}"


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
    


    

