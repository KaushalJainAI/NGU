"""Small helpers for recording behavioral events from server-side code."""
import logging

from .models import UserEvent

logger = logging.getLogger(__name__)


def record_purchase_events(order):
    """
    Emit one ``purchase`` UserEvent per product line in a completed order.

    Called from the order-creation flow so purchase signal is reliable even if
    the client never fires it. Best-effort: never let analytics break checkout.
    """
    try:
        events = []
        for item in order.items.select_related('product').all():
            if item.product_id is None and item.combo_id is None:
                continue
            events.append(UserEvent(
                user=order.user,
                event_type='purchase',
                product_id=item.product_id,
                combo_id=item.combo_id,
                category_id=getattr(item.product, 'category_id', None),
                metadata={'order_id': str(order.order_id), 'quantity': item.quantity},
            ))
        if events:
            UserEvent.objects.bulk_create(events)
        # New purchase signal — drop cached recommendations so it shows next load.
        from products.personalization import invalidate_user_recommendations
        invalidate_user_recommendations(order.user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Failed to record purchase events for order {getattr(order, 'id', '?')}: {exc}")
