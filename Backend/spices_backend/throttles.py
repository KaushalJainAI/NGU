"""Scoped rate-limit throttles for write-heavy / abuse-prone actions.

Rates live in settings.DEFAULT_THROTTLE_RATES (env-tunable). Each throttle also
records a strike when it denies a request, so repeat offenders surface in the
abuse log for a manual ban decision.
"""
from rest_framework.throttling import UserRateThrottle

from .abuse import flag_suspicious


class _FlaggedThrottle(UserRateThrottle):
    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)
        if not allowed:
            flag_suspicious(request, reason=f"rate_limit:{self.scope}")
        return allowed


class OrderRateThrottle(_FlaggedThrottle):
    scope = "order"          # e.g. 10/min — orders a person can place per minute


class OrderDailyThrottle(_FlaggedThrottle):
    scope = "order_day"      # e.g. 100/day — daily ceiling


class CartWriteThrottle(_FlaggedThrottle):
    scope = "cart_write"     # e.g. 60/min — cart mutations (add/update/sync/clear)


class PaymentRateThrottle(_FlaggedThrottle):
    scope = "payment"        # e.g. 20/min — create-order + verify (HMAC-oracle guard)
