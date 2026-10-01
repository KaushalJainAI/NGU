from django.db import models
from django.conf import settings


class UserEvent(models.Model):
    """
    A single behavioral interaction by a logged-in user.

    These rows are the raw signal that powers personalized recommendations
    (see products/personalization.py). Kept deliberately lightweight so the
    write path on POST /api/events/ stays cheap; aggregation happens at read
    time (or via a periodic rollup) rather than here.
    """

    EVENT_TYPE_CHOICES = [
        ('view', 'Product View'),
        ('click', 'Product Click'),
        ('add_to_cart', 'Add To Cart'),
        ('remove_from_cart', 'Remove From Cart'),
        ('favorite', 'Favorite'),
        ('search', 'Search'),
        ('purchase', 'Purchase'),
        # Funnel / page-level events (logged-in only; anonymous traffic is
        # tracked separately via DailyAnonStat counters — see analytics/anon.py).
        ('page_view', 'Page View'),
        ('checkout_started', 'Checkout Started'),
        ('checkout_completed', 'Checkout Completed'),
        ('checkout_abandoned', 'Checkout Abandoned'),
        # AP11: voice-ordering funnel (short names — event_type is capped at
        # 20 chars). Fired by the storefront for "say your shopping list".
        ('voice_used', 'Voice Input Used'),
        ('voice_confirmed', 'Voice Proposal Confirmed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='events',
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)

    # Optional targets — which entity the event is about. All nullable because
    # not every event references one (e.g. a bare search has only a query).
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    combo = models.ForeignKey(
        'products.ProductCombo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    category = models.ForeignKey(
        'products.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    query = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    session_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'event_type']),
            models.Index(fields=['product']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.event_type}:{self.product_id or self.query}"


class UserGeo(models.Model):
    """
    Coarse, consent-based location for a single user.

    Captured only after the user explicitly shares their location on the
    storefront (browser geolocation -> reverse geocode). Deliberately coarse:
    we never persist precise GPS coordinates here. ``lat_coarse``/``lng_coarse``
    are rounded to ~city-block resolution (3 decimals) so they cannot pinpoint
    a home, while ``city``/``state``/``pincode_prefix`` drive (future) regional
    recommendation ranking. See products/personalization.py (W_GEO slot).

    One row per user (latest known location); updating overwrites it.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='geo',
    )
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    # First 3 digits of the Indian PIN code — region, not exact locality.
    pincode_prefix = models.CharField(max_length=3, blank=True)
    # Rounded to 3 decimals (~110 m) at the API boundary; never raw GPS.
    lat_coarse = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
    )
    lng_coarse = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Location'
        verbose_name_plural = 'User Locations'
        indexes = [
            models.Index(fields=['state']),
            models.Index(fields=['pincode_prefix']),
        ]

    def __str__(self):
        loc = ', '.join(filter(None, [self.city, self.state])) or 'unknown'
        return f"{self.user_id}: {loc}"


# ---------------------------------------------------------------------------
# Rollup tables
#
# These are *read-time* aggregates for the admin Insights dashboard. They are
# never written by request/response views — only by the ``rollup_analytics``
# management command, which recomputes a day's rows idempotently from the
# source signals (orders + UserEvent + the anonymous Redis counters). Keeping
# them pre-aggregated means the dashboard reads stay fast and constant-time
# regardless of how large the raw event/order tables grow, and the raw events
# remain prunable. See ANALYTICS.md.
# ---------------------------------------------------------------------------


class DailySalesRollup(models.Model):
    """One row per day of sales KPIs, sourced from the orders app."""

    date = models.DateField(unique=True, db_index=True)
    orders = models.PositiveIntegerField(default=0)
    units = models.PositiveIntegerField(default=0)
    # GROSS revenue — the amount actually collected, so it reconciles against
    # gateway settlements. The GST and delivery components below are reported
    # ALONGSIDE it, never subtracted from it.
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # GST collected from customers on the day's sales (output tax) — goods GST
    # PLUS the 18% on delivery. A record of money taken, NOT the amount to
    # remit: that is this minus input tax credit on purchases, which this
    # system does not track and leaves to the owner's books.
    gst_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Money refunded and the GST reversed with it, bucketed by the date the
    # REFUND happened (not the sale) — a credit note reduces output tax in its
    # own period, so this must never rewrite an already-filed month.
    refunds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Delivery fees charged to customers vs what the couriers charged us.
    # `shipping_cost` is admin-entered per order, so it is 0 until recorded.
    shipping_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # The 18% GST on those delivery fees, already counted inside gst_collected.
    # Broken out so the delivery slab can be reported on its own for GSTR-1
    # without re-querying every order.
    shipping_tax_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # COD cash confirmed received on this day, bucketed by CONFIRMATION date —
    # the order it settles is usually older, since couriers remit in batches.
    # A cash-ledger figure: deliberately unrelated to `revenue`, which accrues at
    # order date and does not move when the money actually turns up.
    cod_collected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    aov = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    coupon_orders = models.PositiveIntegerField(default=0)
    coupon_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    new_customers = models.PositiveIntegerField(default=0)
    returning_customers = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name = 'Daily Sales Rollup'

    @property
    def net_gst_collected(self):
        """Tax actually held for the day: collected minus reversed by refunds.

        Deliberately NOT called "payable". What is remitted is this minus input
        tax credit on purchases, which this system does not track and does not
        try to guess — see docs/ANALYTICS.md.
        """
        return (self.gst_collected or 0) - (self.gst_refunded or 0)

    def __str__(self):
        return f"{self.date}: {self.orders} orders / ₹{self.revenue}"


class DailyFunnelRollup(models.Model):
    """Logged-in funnel: count of each UserEvent type per day."""

    date = models.DateField(db_index=True)
    event_type = models.CharField(max_length=20)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-date']
        unique_together = ('date', 'event_type')
        indexes = [models.Index(fields=['date'])]

    def __str__(self):
        return f"{self.date} {self.event_type}: {self.count}"


class SearchTermStat(models.Model):
    """Per-day search term frequency, flagging zero-result queries."""

    date = models.DateField(db_index=True)
    term = models.CharField(max_length=255)
    count = models.PositiveIntegerField(default=0)
    zero_result = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date', '-count']
        unique_together = ('date', 'term')
        indexes = [models.Index(fields=['date', '-count'])]

    def __str__(self):
        flag = ' (0 results)' if self.zero_result else ''
        return f"{self.date} '{self.term}' x{self.count}{flag}"


class DailyAnonStat(models.Model):
    """
    Pre-aggregated counters for anonymous (logged-out) traffic.

    Storage is bounded by ``days × metric × dimension-cardinality`` — it does
    NOT grow with visitor count. A million anonymous visits add zero rows; they
    only bump existing counters. Counters are incremented in Redis on the hot
    path and flushed here periodically (see analytics/anon.py). When Redis is
    unavailable (tests/dev) increments are written here directly.

    ``dimension_key`` is empty for the day/metric total, otherwise a coarse,
    non-identifying bucket like ``device:mobile``, ``state:Maharashtra``,
    ``city:Pune`` or ``source:google``.
    """

    METRIC_CHOICES = [
        ('page_view', 'Page View'),
        ('product_view', 'Product View'),
        ('add_to_cart', 'Add To Cart'),
        ('search', 'Search'),
        ('search_zero_result', 'Search (Zero Result)'),
        ('checkout_started', 'Checkout Started'),
        ('checkout_completed', 'Checkout Completed'),
    ]

    date = models.DateField(db_index=True)
    metric = models.CharField(max_length=32, choices=METRIC_CHOICES)
    dimension_key = models.CharField(max_length=64, blank=True, default='')
    count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-date']
        unique_together = ('date', 'metric', 'dimension_key')
        indexes = [models.Index(fields=['date', 'metric'])]
        verbose_name = 'Daily Anonymous Stat'

    def __str__(self):
        dim = self.dimension_key or 'total'
        return f"{self.date} {self.metric}[{dim}]: {self.count}"
