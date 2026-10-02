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

# Max total (in rupees) allowed for an ONLINE (Razorpay) order. UPI has a
# per-transaction cap of ₹1,00,000; orders above this can only be paid via COD.
MAX_ONLINE_ORDER_TOTAL = config("MAX_ONLINE_ORDER_TOTAL", default=100_000, cast=int)

# --- Cash on delivery abuse caps (AP7b/S7) -----------------------------------
# A COD order reserves stock with no money down, so unverified throwaways can
# drain the shelf. Two bounds (owner-tunable via env, see AUDIT §7.5):
# value per order, and how many unfinished COD orders one account may hold.
COD_MAX_VALUE = config("COD_MAX_VALUE", default=Decimal("5000"))
# An order counts as "open" while it can still tie up stock or cash:
# placed through in-transit. Delivered (goods reached the customer),
# cancelled and refunded are terminal and don't count.
COD_OPEN_STATUSES = ('pending', 'confirmed', 'processing', 'shipped', 'delivering')
COD_MAX_OPEN = config("COD_MAX_OPEN", default=3, cast=int)

# --- Pricing (shipping / tax) ------------------------------------------------
# Flat shipping fee charged below the free-shipping threshold, and the
# post-discount subtotal (in rupees) at/above which shipping becomes free.
#
# ⚠ UNLIKE GOODS, SHIPPING IS PRICED **EXCLUSIVE** OF GST. Product MRPs contain
# their GST (see orders/pricing.py); the delivery fee does not — SHIPPING_CHARGE
# is the net fee and SHIPPING_TAX_RATE is added on top, so the customer pays
# 59.00 + 10.62 = 69.62. The two conventions coexist deliberately: the goods
# figure is a shelf price the customer already knows, while the delivery fee is
# a service billed at its own SAC rate. `Order.shipping_charge` therefore stores
# the NET fee and `Order.shipping_tax` the GST on it — never fold one into the
# other, or the invoice's GST summary stops reconciling.
#
# ⚠ THE ENV VAR IS DELIBERATELY RENAMED — read this before "tidying" it back.
# The old name was SHIPPING_CHARGE, and every deployed .env pins it to 69 from
# the era when delivery was untaxed. Keeping the name would have made the meaning
# of that number change under the deployments still holding it: 69 stopped being
# "what the customer pays for delivery" and became "the net fee", so an
# un-updated environment would silently start billing 69 + 18% = 81.42.
#
# Neither order of a manual fix is safe either — changing the env before the code
# ships bills 59 with NO tax (undercharging), and shipping the code first
# overcharges until someone remembers the env. Renaming removes the window
# entirely: a stale SHIPPING_CHARGE is now simply ignored, the correct default
# applies everywhere, and `check_pricing_config` below warns if the dead variable
# is still lying around.
SHIPPING_CHARGE_NET = config("SHIPPING_CHARGE_NET", default=Decimal("59"), cast=Decimal)
# Back-compat alias: the rest of the codebase (and the tests) refer to
# SHIPPING_CHARGE, and there is no value in churning every call site for a
# settings rename that only exists to orphan a stale env value.
SHIPPING_CHARGE = SHIPPING_CHARGE_NET
# GST on delivery (SAC 9968, courier services). Distinct from DEFAULT_TAX_RATE:
# goods here are 0%/5%, the delivery service is 18%.
SHIPPING_TAX_RATE = config("SHIPPING_TAX_RATE", default=Decimal("18"), cast=Decimal)
# Set when a deployment still carries the pre-2026-08-04 variable, so startup can
# say so out loud. Read only for the warning — it never affects pricing.
LEGACY_SHIPPING_CHARGE = config("SHIPPING_CHARGE", default=None)
# Post-discount subtotal at/above which delivery is free. The comparison is `>=`,
# so an order of exactly ₹499 ships free.
#
# ⚠ Keep this in step with VITE_FREE_SHIPPING_THRESHOLD in the storefront AND with
# every .env. Until 2026-08-05 the code default was 499 while all six env files and
# the storefront default said 500, so the cutoff silently moved by ₹1 depending on
# whether an environment happened to set the variable — invisible until a customer
# is charged delivery on an order the site had promised was free. 499 is the
# intended number; the env files were the ones that had drifted.
FREE_SHIPPING_THRESHOLD = config("FREE_SHIPPING_THRESHOLD", default=Decimal("499"), cast=Decimal)

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
