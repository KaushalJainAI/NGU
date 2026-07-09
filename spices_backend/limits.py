"""
Single source of truth for input/abuse limits.

Every value an external client can influence is bounded here so it can never
reach a layer that cannot tolerate an extreme value (DB column limits, Decimal
precision, memory). Each limit is tunable per-environment via an env var; the
defaults are the agreed safe values. Keep this file dependency-free (only
python-decouple) so it can be imported from settings, serializers, views and
throttles without circular imports.
"""
from decimal import Decimal
from decouple import config

# --- Cart / order quantities -------------------------------------------------
# A single line can never request more than this many units. Caps `price * qty`
# far below the money column limit (numeric(10,2) -> ₹99,999,999.99) for any
# realistic unit price, so checkout can never overflow.
MAX_ITEM_QUANTITY = config("MAX_ITEM_QUANTITY", default=100, cast=int)

# Maximum number of distinct lines in one cart.
MAX_CART_ITEMS = config("MAX_CART_ITEMS", default=50, cast=int)

# Maximum number of items accepted in a single cart-sync payload.
MAX_SYNC_ITEMS = config("MAX_SYNC_ITEMS", default=100, cast=int)

# Hard ceiling on any computed order money value, kept under the numeric(10,2)
# column limit as a belt-and-suspenders guard behind MAX_ITEM_QUANTITY.
MAX_ORDER_TOTAL = config("MAX_ORDER_TOTAL", default=9_999_999, cast=int)

# --- Pricing (shipping / tax) ------------------------------------------------
# Flat shipping fee charged below the free-shipping threshold, and the
# post-discount subtotal (in rupees) at/above which shipping becomes free.
SHIPPING_CHARGE = config("SHIPPING_CHARGE", default=Decimal("69"), cast=Decimal)
FREE_SHIPPING_THRESHOLD = config("FREE_SHIPPING_THRESHOLD", default=Decimal("500"), cast=Decimal)

# Fallback GST rate (%) used only when a product/combo has no tax_rate set.
DEFAULT_TAX_RATE = config("DEFAULT_TAX_RATE", default=Decimal("5"), cast=Decimal)

# --- Reviews -----------------------------------------------------------------
MAX_REVIEW_COMMENT = config("MAX_REVIEW_COMMENT", default=2000, cast=int)

# --- Search ------------------------------------------------------------------
MAX_SEARCH_Q = config("MAX_SEARCH_Q", default=200, cast=int)
SEARCH_TOP_K_MAX = config("SEARCH_TOP_K_MAX", default=100, cast=int)
SEARCH_THRESHOLD_MIN = config("SEARCH_THRESHOLD_MIN", default=0, cast=int)
SEARCH_THRESHOLD_MAX = config("SEARCH_THRESHOLD_MAX", default=100, cast=int)

# --- Abuse tracking ----------------------------------------------------------
# Rolling window (seconds) over which "strikes" (rejected extreme/abusive
# requests) are counted per client IP, and the count at which we log loudly so
# an operator can decide to ban. Banning itself is manual (see abuse.block_ip).
ABUSE_STRIKE_WINDOW = config("ABUSE_STRIKE_WINDOW", default=300, cast=int)
ABUSE_STRIKE_ALERT = config("ABUSE_STRIKE_ALERT", default=20, cast=int)


def clamp(value, low, high):
    """Clamp value into [low, high]."""
    return max(low, min(high, value))
