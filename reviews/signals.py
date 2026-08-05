"""Cache invalidation for review changes.

`GET /api/products/` (and the homepage sections row) are cached for
CACHE_TTL_MEDIUM and embed each product's `average_rating` / `reviews_count`.
Nothing here used to listen to Review, so posting, hiding, or deleting a review
left those aggregates stale for up to five minutes: an admin would hide a review,
see it vanish from the moderation list, and still find its stars on the shop —
which reads as "the hide button doesn't work".
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
import logging

from products.cache import (
    invalidate_combo_cache,
    invalidate_product_cache,
)
from .models import Review

logger = logging.getLogger(__name__)


def _invalidate_for(review):
    """Bust whichever catalogue cache embeds this review's aggregates."""
    if review.item_type == 'combo':
        invalidate_combo_cache()
    else:
        invalidate_product_cache()


@receiver(post_save, sender=Review)
def invalidate_cache_on_review_save(sender, instance, **kwargs):
    # Covers create, edit, hide/unhide and feature/unfeature — every one of
    # them can change what the storefront should be showing.
    _invalidate_for(instance)
    logger.info("Catalogue cache invalidated (review saved): %s", instance.pk)


@receiver(post_delete, sender=Review)
def invalidate_cache_on_review_delete(sender, instance, **kwargs):
    _invalidate_for(instance)
    logger.info("Catalogue cache invalidated (review deleted): %s", instance.pk)
