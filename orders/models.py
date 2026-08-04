from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator
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
        ('delivering', 'Delivering'),
        # Money went back to the customer. Distinct from 'cancelled': a cancelled
        # order may never have been paid, whereas 'refunded' asserts a payment was
        # taken AND returned — which is what reverses the GST liability.
        ('refunded', 'Refunded'),
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

    # --- Structured destination (for GST place of supply) -------------------
    # `shipping_address` is a free-text blob the frontend assembles from the
    # checkout form, which is fine for a courier label and useless for tax: the
    # CGST/SGST vs IGST decision needs to know the destination STATE. Checkout
    # has always asked for state and pincode as their own fields — it just
    # flattened them on the way out — so these capture what was already typed.
    #
    # Blank on orders placed before this existed; the place-of-supply snapshot
    # below is what anything tax-related reads, never these.
    shipping_state = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Destination state as the customer entered it. Free text — "
                  "place_of_supply_state_code is the resolved, authoritative value.")
    shipping_pincode = models.CharField(
        max_length=10, blank=True, default='',
        help_text="Destination PIN code as entered. Reported alongside place of "
                  "supply on GST returns.")

    # --- GST place of supply ------------------------------------------------
    # Two-digit GST state code of the DESTINATION, snapshotted at checkout. It
    # decides the tax HEADS on the invoice — equal to the seller's state means
    # CGST + SGST, anything else means IGST for the same amount — and it is the
    # key GSTR-1 Table 7 (B2C others) is reported by.
    #
    # A snapshot, not a lookup: re-deriving it from the address later would let
    # an admin's address correction silently re-head an invoice that has already
    # been filed. See orders/place_of_supply.py.
    #
    # BLANK means "placed before this was captured". Those orders were billed and
    # filed as intra-state, so `is_interstate('')` is False by design and their
    # reprinted bills still match the returns they were filed on.
    place_of_supply_state_code = models.CharField(
        max_length=2, blank=True, default='', db_index=True,
        help_text="GST state code of the destination (e.g. '23' = Madhya Pradesh). "
                  "Blank = historical order, treated as intra-state.")

    # Order Details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    
    # Pricing (with discount support)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, help_text="Original subtotal before discount")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total discount applied")
    # NET delivery fee — GST EXCLUSIVE, unlike goods. See `shipping_tax` below.
    shipping_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="GST on the GOODS at the discounted amount. When tax_inclusive is "
                  "True this is CONTAINED IN subtotal (disclosure only); on legacy "
                  "orders it was ADDED to reach total_amount. Does NOT include GST "
                  "on delivery — see shipping_tax, and use total_tax to report both.")
    # GST on the delivery fee (SAC 9968, 18%), charged ON TOP of shipping_charge
    # because the fee is quoted net — the opposite convention to goods, whose MRP
    # already contains their GST.
    #
    # Kept in its OWN column rather than folded into `tax` because the two are
    # different slabs on the GST return (goods 0%/5%, delivery 18%) and because
    # `tax` is load-bearing for the tax_inclusive branch above: adding an
    # exclusive figure into an inclusive field would break every legacy invoice
    # reprint. Anything reporting total output tax must read `total_tax`.
    #
    # Orders placed before delivery was taxed carry 0 here and are correct as-is.
    shipping_tax = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="GST charged on the delivery fee, ADDED on top of shipping_charge. "
                  "0 on free-shipping orders and on orders placed before delivery "
                  "was taxed.")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Final amount to pay")
    # Which pricing convention this order was placed under. Prices became
    # GST-inclusive (MRP) for all new orders; rows written before that change are
    # backfilled False and keep their tax-added totals untouched. The invoice
    # renderer branches on this so a reprinted historical bill still adds up.
    tax_inclusive = models.BooleanField(
        default=True,
        help_text="True: prices include GST (tax is part of subtotal). "
                  "False (legacy): GST was added on top of subtotal.")
    # What the COURIER actually charged to deliver this order, entered by the
    # admin after dispatch. Pairs with `shipping_charge` (what the customer paid)
    # to give real delivery margin instead of a guess.
    #
    # ADMIN-PRIVATE — this is internal cost data. Like `delivery_bill` it must
    # never appear in a customer-facing serializer; exposing it would show every
    # customer the store's supplier pricing and margin.
    shipping_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Actual courier cost for this order (admin-entered, ₹0 = not recorded). "
                  "ADMIN-ONLY — never expose to customers.")

    # --- Refunds -----------------------------------------------------------
    # Denormalised running totals of the OrderRefund ledger below, kept in sync by
    # `record_refund()`. Stored so order lists/exports don't need a join, but the
    # ledger is the source of truth — never write these directly.
    refunded_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Total money returned to the customer across all refunds.")
    refunded_tax = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="GST reversed by those refunds. SUBTRACTED from GST collected "
                  "when reporting what is owed to the government.")
    refunded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the MOST RECENT refund was recorded. Per-refund dates live "
                  "on OrderRefund — reporting attributes GST reversal by those.")

    # --- Inventory ---------------------------------------------------------
    # Stamped the first time this order's stock is given back — by a cancel, by
    # L3's stuck-payment auto-cancel, or by a refund. Three independent paths can
    # restock the same order (cancel it, then refund it), and without a marker the
    # second would credit inventory a second time and invent stock that never
    # existed. `restore_order_stock()` reads and sets this; nothing else should.
    stock_restored_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="When this order's stock was returned to inventory. Set once; "
                  "guarantees cancel + refund can't both credit the same units.")


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

    # --- COD cash collection -----------------------------------------------
    # A COD order takes no payment at checkout, so nothing in the system knew
    # whether the cash ever arrived — it sat at payment_status='pending' forever,
    # there was no "cash the courier is still holding" figure, and a COD return
    # could not be recorded at all (the refund guard demands proof money was
    # taken). An admin ticks "Paid in cash" once the money is in hand, which
    # stamps these and flips payment_status to 'paid'.
    #
    # DELIBERATELY NOT a side effect of marking the order delivered: the courier
    # usually remits days later, and auto-ticking on delivery would record cash
    # that has not arrived — exactly the fiction this field exists to remove.
    #
    # This is a CASH fact, not a tax one. GST is accrued at order date regardless
    # (time of supply for goods is the invoice, not the payment), so ticking this
    # must never move a GST figure.
    cod_paid_at = models.DateTimeField(
        blank=True, null=True, db_index=True,
        help_text="When an admin confirmed the COD cash was received. NULL on a COD "
                  "order means the money is still outstanding.")
    cod_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        blank=True, null=True, related_name='cod_confirmations',
        help_text="Admin who ticked 'Paid in cash'. Recorded because confirming "
                  "receipt of cash is the highest-trust action in the panel.")

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

    @property
    def total_tax(self):
        """ALL output GST on this order: goods + delivery.

        `tax` alone is the goods figure and understates the liability by the GST
        on the delivery fee. Every surface that reports "GST collected" — the
        rollup, the dashboard tile, the daily digest, the CSV export — must use
        this, not `tax`.
        """
        return (self.tax or Decimal('0')) + (self.shipping_tax or Decimal('0'))

    @property
    def place_of_supply_name(self):
        """Readable place of supply, e.g. "Madhya Pradesh".

        Falls back to the seller's own state for historical orders, which is
        exactly how they were billed — see `place_of_supply_state_code`.
        """
        from .place_of_supply import seller_state_code, state_name
        return state_name(self.place_of_supply_state_code or seller_state_code())

    @property
    def is_interstate(self):
        """True when this order's GST is IGST rather than CGST + SGST."""
        from .place_of_supply import is_interstate
        return is_interstate(self.place_of_supply_state_code)

    @property
    def gst_heads(self):
        """This order's TOTAL output GST split into heads: cgst / sgst / igst.

        The split of `total_tax` — goods plus delivery — because that is the
        liability figure every reporting surface uses. The three always sum back
        to `total_tax` exactly.
        """
        from .place_of_supply import split_gst
        return split_gst(self.total_tax, self.place_of_supply_state_code)

    @property
    def cod_payment_outstanding(self):
        """True when this is a COD order whose cash has not been confirmed.

        The money the courier is still holding. ONLINE orders are never
        outstanding in this sense — their money either arrived through the
        gateway or the order was cancelled.
        """
        return self.payment_method == 'COD' and self.cod_paid_at is None


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
    # SNAPSHOT of the GST rate charged on this line. Stored rather than read back
    # from the product because the product's rate can change later, and a bill
    # must always reproduce the rate that was actually applied. Drives the
    # per-slab breakup shown on the invoice and order detail.
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="GST %% applied to this line at order time (snapshot).")
    # SNAPSHOT of the product's HSN code, for the same reason as `tax_rate`: a
    # product re-classified next year must not rewrite last year's invoice, and
    # the HSN summary in a GST return is built per PERIOD from the lines that
    # were actually billed. Blank on combo lines — a combo is a mixed supply and
    # its HSN lives on the per-component rows below.
    hsn_code = models.CharField(
        max_length=8, blank=True, default='',
        help_text="HSN code billed on this line at order time (snapshot).")
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


class OrderItemComponent(models.Model):
    """One component of a COMBO order line, with the GST it carried.

    A combo is a single priced line to the customer but several taxable goods to
    the GST return — a box mixing 0% papad with 5% masala is a mixed supply, and
    a bill reporting it at one blended rate is unauditable. So checkout splits
    the charged line amount back across the components (linearly by MRP share,
    see ``orders.pricing.allocate_combo_components``) and writes one of these per
    component. ``orders.pricing.order_tax_breakdown`` reads them to build the
    per-slab rows on the invoice.

    Everything here is a SNAPSHOT, for the same reason ``OrderItem`` snapshots
    ``product_name``: a reprinted invoice must reproduce the rate and amount
    actually charged, whatever the catalogue says today. ``variant`` is kept as
    a PROTECTed FK for reporting (which SKU actually moved), not as the source
    of any figure on the bill.

    Rows exist only for orders placed after this split shipped. Combo lines
    without them are historical and fall back to ``OrderItem.tax_rate``.
    """

    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name='components'
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.PROTECT, related_name='order_item_components'
    )
    # Snapshots — the bill must not depend on the catalogue still agreeing.
    product_name = models.CharField(max_length=200)
    variant_label = models.CharField(max_length=50, blank=True)
    # TOTAL units of this size the line consumed: per-combo quantity x line
    # quantity, matching what was drawn from stock.
    quantity = models.PositiveIntegerField()
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="GST %% on this component at order time (snapshot).")
    hsn_code = models.CharField(
        max_length=8, blank=True, default='',
        help_text="HSN code of this component at order time (snapshot).")
    # This component's share of the line's post-discount, GST-INCLUSIVE amount.
    # These sum EXACTLY to OrderItem.final_price — the allocator hands its
    # rounding residual to the largest component to guarantee it.
    allocated_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        indexes = [models.Index(fields=['order_item'])]

    def __str__(self):
        return f"{self.quantity} x {self.product_name} ({self.variant_label})"

    @property
    def savings(self):
        """Amount saved on this item"""
        return self.discount_amount


class InvoiceCounter(models.Model):
    """The running invoice number for one series. One row per series.

    A GST invoice series must be continuous within a financial year, which means
    the number cannot be derived from anything that has gaps — and `Order.id`
    has plenty (every abandoned checkout and cancelled order burns one). So the
    number comes from here instead: a counter bumped ONLY when an invoice is
    actually issued.

    Allocation takes a row lock (`allocate_invoice_number`), so two concurrent
    captures cannot hand out the same number. The lock is held for the width of
    one UPDATE, not the caller's whole transaction.
    """

    series = models.CharField(
        max_length=16, unique=True,
        help_text="Series this counter belongs to, e.g. 'NM/25-26' (one per FY).")
    last_number = models.PositiveIntegerField(
        default=0, help_text="Highest number issued in this series so far.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.series} @ {self.last_number}"


class Invoice(models.Model):
    """The issued tax invoice for an order — number, date, and frozen contents.

    ONE invoice per order (OneToOne), deliberately. A tax invoice is not a view
    of an order, it is a document issued once against a supply: it is never
    edited and never re-issued, because a second document for the same supply
    would bill it twice in the series. Corrections are a SEPARATE document — a
    credit note — which is what the `OrderRefund` ledger already records.

    Three things this fixes over rendering `ORD-{id}` on the fly:

    1. **The number is real.** Allocated from `InvoiceCounter` at issue time, so
       the series is continuous. `Order.id` skips every cancelled or abandoned
       order.
    2. **A reprint is identical to the original.** `snapshot` holds the seller
       details, buyer details, lines, totals and GST summary as they were when
       the invoice was issued. The renderer reads ONLY this — never live
       settings and never the live order — so changing `SELLER_ADDRESS` (or an
       admin editing the shipping address) cannot alter a bill already given to
       a customer. A document that changes after issue is not a document.
    3. **It only exists once it should.** A row here IS the assertion that a
       taxable supply happened; no row means the endpoint has nothing to serve,
       so an unpaid order can no longer produce a page headed TAX INVOICE.

    See `orders/invoicing.py` for when one is issued and what goes in `snapshot`.
    """

    order = models.OneToOneField(
        Order, on_delete=models.PROTECT, related_name='invoice',
        help_text="The supply this invoice bills. PROTECTed: an order with an "
                  "issued invoice is an accounting record and must not vanish.")
    # The customer-visible identity of the document. Unique across all series;
    # `series` is stored separately so a FY's invoices can be listed without
    # parsing the string.
    number = models.CharField(
        max_length=16, unique=True, db_index=True,
        help_text="Full invoice number, e.g. 'NM/25-26/000123'. GST caps this at "
                  "16 characters (alphanumerics, '-' and '/' only).")
    series = models.CharField(
        max_length=16, db_index=True,
        help_text="Series the number was drawn from — one per financial year.")
    sequence = models.PositiveIntegerField(
        help_text="Position within `series`. Continuous by construction.")
    # The TAX POINT. Distinct from Order.created_at (which can precede it) and
    # from any later reprint. Everything on the document is as of this instant.
    issued_at = models.DateTimeField(
        db_index=True,
        help_text="When the invoice was issued. The date printed on the bill.")
    # Denormalised from the snapshot for querying/reconciliation without parsing
    # JSON — e.g. "total invoiced value this quarter". The snapshot remains the
    # authority for what is PRINTED.
    total_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Grand total as invoiced (frozen copy of Order.total_amount).")
    total_tax = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="All output GST on the document: goods + delivery.")
    snapshot = models.JSONField(
        help_text="Everything the PDF prints, frozen at issue. See "
                  "orders.invoicing.build_invoice_snapshot for the shape.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['series', 'sequence'],
                                    name='uniq_invoice_series_sequence'),
        ]
        indexes = [models.Index(fields=['series', 'sequence'])]

    def __str__(self):
        return self.number


class OrderRefund(models.Model):
    """One refund against an order — the ledger that reverses GST liability.

    Why a ledger rather than a couple of columns on Order:

    1. **Refunds can be partial and repeated.** A customer returns one item this
       week and another next month; each reverses its own slice of GST.
    2. **GST is reversed in the period the refund happens, not the period of the
       sale.** A credit note reduces output tax in its own month. Attributing a
       March refund back to a January sale would retroactively change a return you
       have already filed. Reporting therefore buckets by `created_at` HERE, not
       by the order's date.
    3. **Idempotency.** Razorpay can redeliver `refund.processed`; `reference`
       holds the gateway refund id under a unique constraint so a replay is a
       no-op instead of double-reversing the tax.
    """

    SOURCE_CHOICES = [
        ('gateway', 'Gateway webhook'),   # Razorpay refund.processed
        ('admin', 'Recorded by admin'),   # COD returns / manual settlements
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='refunds')
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)],
        help_text="Money returned to the customer in this refund (GST-inclusive).")
    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="GST contained in `amount` — the output tax this refund reverses.")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='gateway')
    # Gateway refund id (rfnd_…) when known. Unique so a redelivered webhook can
    # never create a second ledger row; NULL for manual entries, and NULLs do not
    # collide under a unique index.
    reference = models.CharField(max_length=100, blank=True, null=True, unique=True)
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['order', 'created_at'])]

    def __str__(self):
        return f"Refund {self.amount} on ORD-{self.order_id:06d}"
