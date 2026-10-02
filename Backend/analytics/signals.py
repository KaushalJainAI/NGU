"""
Decoupled server-side signal capture for analytics.

The analytics app *subscribes* to model lifecycle events rather than being
called inline from other apps' views. This keeps analytics a self-contained,
removable module: the orders app no longer needs to know analytics exists.

Purchase events power the recommendation engine and the logged-in funnel. We
record them on the order's ``post_save`` but defer the actual work to
``transaction.on_commit`` so the order's items are fully committed and visible
before we read them (order creation runs inside a single atomic block).
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def register():
    """Wire up receivers. Called from AnalyticsConfig.ready()."""
    from orders.models import Order

    @receiver(post_save, sender=Order, dispatch_uid='analytics_order_purchase')
    def _on_order_created(sender, instance, created, **kwargs):
        if not created:
            return
        # Read items only after the surrounding transaction commits.
        transaction.on_commit(lambda: _record(instance))


def _record(order):
    from .services import record_purchase_events
    try:
        record_purchase_events(order)
    except Exception as exc:  # pragma: no cover - defensive; analytics must never break checkout
        logger.warning(f"analytics purchase capture failed for order {getattr(order, 'id', '?')}: {exc}")
