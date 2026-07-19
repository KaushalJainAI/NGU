from django.db import models
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from products.models import Product, ProductVariant
from admin_panel.models import Coupon  # Add this import
import uuid


def delivery_bill_storage():
    """LOCAL filesystem storage for the admin-only delivery bill.

    Returned as a callable so migrations reference this function (not a baked-in
    absolute path). It forces local disk regardless of the Cloudinary/S3 default
    media backend, into `PRIVATE_MEDIA_ROOT` — a directory that is NOT served
    over any URL. The bill is therefore only ever reachable by streaming through
    the staff-gated `delivery_bill` endpoint, never via a public CDN URL, and
    arbitrary types (PDF included) are stored verbatim.
    """
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


def delivery_bill_upload_path(instance, filename):
    """Obscured, per-order path for the admin-only delivery bill.

    The file is never served from its storage URL — only streamed through the
    admin-gated `delivery_bill` endpoint — but a UUID filename keeps the object
    key unguessable as defence in depth.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
    return f"delivery_bills/order_{instance.id or 'new'}/{uuid.uuid4().hex}.{ext}"


class Order(models.Model):
    """Order Model with Coupon Support"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delivering', 'Delivering')
    ]

    PAYMENT_METHOD_CHOICES = [
        ('COD', 'Cash on Delivery'),
        ('ONLINE', 'Online Payment'),
        ('razorpay', 'Razorpay'),
    ]

    # Standardised payment_status vocabulary (PAYMENT_INTEGRATION_PLAN.md §1b.2).
    # 'processing' is the "captured at Razorpay but our /verify/ hasn't confirmed
    # yet" window — surfaced to the customer as "Confirming your payment…".
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        # Set by L3 reconciliation when an ONLINE order is abandoned past the
        # payment TTL: the order is cancelled and its stock released. Distinct
        # from 'failed' (an actual gateway decline) so ops can tell an
        # explicitly-rejected/expired checkout apart from a hard failure.
        ('rejected', 'Payment Rejected'),
        ('refunded', 'Refunded'),
    ]

    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    
    # Shipping Details
    shipping_address = models.TextField()
    phone_number = models.CharField(max_length=15)  # Renamed for consistency with API
    
    # Order Details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    
    # Pricing (with discount support)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, help_text="Original subtotal before discount")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total discount applied")
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Tax calculated on discounted amount")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Final amount to pay")
    
    # Coupon
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')

    # Shipment tracking (set by admin once the parcel is dispatched). Adding a
    # value triggers a "your order is on its way" email to the customer.
    tracking_number = models.CharField(max_length=100, blank=True, default='')

    # Delivery bill (admin-only). A scan/photo/PDF of the courier or delivery
    # receipt the admin uploads for their own records. Deliberately NOT exposed
    # in any customer-facing serializer or storage URL — it is streamed only
    # through the staff-gated `delivery_bill` endpoint.
    delivery_bill = models.FileField(
        upload_to=delivery_bill_upload_path, storage=delivery_bill_storage,
        blank=True, null=True,
        help_text="Admin-only courier/delivery receipt. Never shown to customers.",
    )
    delivery_bill_uploaded_at = models.DateTimeField(blank=True, null=True)

    # Soft delete (Recycle Bin). A deleted order is hidden from the normal admin
    # list but retained so it can be restored. Distinct from 'cancelled' status:
    # cancellation is a business outcome (stock restored, customer notified),
    # deletion is an admin housekeeping action that can be undone.
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['is_deleted', '-created_at']),
        ]

    def __str__(self):
        return f"Order #{self.order_id}"

    @property
    def coupon_code(self):
        """Get coupon code if applied"""
        return self.coupon.code if self.coupon else None


class OrderItem(models.Model):
    """Individual items in an order with discount tracking"""
    ITEM_TYPE_CHOICES = [
        ('product', 'Product'),
        ('combo', 'Combo'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    # The specific size purchased. Nullable for combos and historical rows; the
    # human-readable size is also snapshotted in product_weight for permanence.
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.PROTECT, null=True, blank=True,
        related_name='order_items'
    )
    combo = models.ForeignKey(
        'products.ProductCombo', 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='order_items'
    )
    item_type = models.CharField(max_length=10, choices=ITEM_TYPE_CHOICES, default='product')
    product_name = models.CharField(max_length=200)
    product_weight = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    
    # Pricing (with discount support)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Original price per unit")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total discount for this item")
    discounted_price = models.DecimalField(max_digits=10, decimal_places=2, default= 0, help_text="Price per unit after discount")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Tax for this item")
    final_price = models.DecimalField(max_digits=10, decimal_places=2, default = 0, help_text="Total price for this item")
    
    class Meta:
        indexes = [
            models.Index(fields=['order', 'product']),
            models.Index(fields=['order', 'combo']),
        ]

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    @property
    def original_subtotal(self):
        """Original subtotal before discount"""
        return self.price * self.quantity

    @property
    def savings(self):
        """Amount saved on this item"""
        return self.discount_amount
